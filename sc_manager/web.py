from __future__ import annotations
import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from .core import Store, AppError

ASSETS = Path(__file__).parent / 'static'

class AccountInput(BaseModel):
    name: str = Field(min_length=1, max_length=32)

class TrackInput(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    genre: str | None = Field(default=None, max_length=100)
    sharing: str | None = None

def create_app(store=None, run_worker=True):
    store = store or Store(demo=os.getenv('SCM_DEMO') == '1')
    stop = threading.Event()
    def work():
        while not stop.is_set():
            try:
                store.work_once()
            except Exception:
                pass  # Keep polling; upstream errors are stored as safe job messages.
            stop.wait(1)

    @asynccontextmanager
    async def lifespan(app):
        thread = threading.Thread(target=work, daemon=True)
        if run_worker:
            thread.start()
        yield
        stop.set()
        if run_worker:
            await asyncio.to_thread(thread.join, 2)

    app = FastAPI(title='SC Manager', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store = store
    hosts = ['localhost', '127.0.0.1', '[::1]']
    for origin in (os.getenv('SCM_REDIRECT_URI', ''), os.getenv('SCM_PUBLIC_URL', '')):
        if urlparse(origin).hostname:
            hosts.append(urlparse(origin).hostname)
    if os.getenv('CODESPACE_NAME'):
        hosts.append(os.environ['CODESPACE_NAME'] + '-8085.' + os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'app.github.dev'))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.middleware('http')
    async def local_security(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and request.headers.get('x-scm-request') != '1':
            return JSONResponse({'detail': 'Use the SC Manager interface for this action.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return JSONResponse({'detail': 'The operation could not complete. Check the account and try again.'}, status_code=500)

    @app.get('/')
    def index():
        return FileResponse(ASSETS / 'index.html')

    @app.get('/health')
    def health():
        return {'ok': True, 'demo': store.demo}

    @app.get('/api/state')
    def state():
        return {'demo': store.demo, 'accounts': store.accounts(), 'jobs': store.jobs(),
                'oauth_configured': bool(os.getenv('SOUNDCLOUD_CLIENT_ID') and os.getenv('SOUNDCLOUD_CLIENT_SECRET'))}

    @app.post('/api/accounts/connect')
    def connect(data: AccountInput):
        if store.demo:
            raise AppError('Demo accounts are already connected. Start without --demo for real accounts.')
        return {'url': store.oauth_start(data.name)}

    @app.get('/auth/callback')
    def callback(state: str = '', code: str = ''):
        if not state or not code:
            return RedirectResponse('/?login=failed', status_code=303)
        try:
            store.oauth_finish(state, code)
        except AppError:
            return RedirectResponse('/?login=failed', status_code=303)
        return RedirectResponse('/?login=success', status_code=303)

    @app.post('/api/accounts/{account}/disconnect')
    def disconnect(account: str):
        store.disconnect(account)
        return {'ok': True}

    @app.get('/api/tracks/{account}')
    def tracks(account: str):
        return {'tracks': store.tracks(account)}

    @app.patch('/api/tracks/{account}/{track_id}')
    def edit(account: str, track_id: str, data: TrackInput):
        return store.edit_track(account, track_id, data.model_dump(exclude_none=True))

    @app.post('/api/uploads')
    def upload(account: str = Form(...), audio: UploadFile = File(...),
               artwork: UploadFile | None = File(default=None), title: str = Form(''),
               description: str = Form(''), genre: str = Form(''), tags: str = Form(''),
               sharing: str = Form('private'), scheduled: str = Form('')):
        store.account(account)
        when = None
        if scheduled:
            try:
                date = datetime.fromisoformat(scheduled.replace('Z', '+00:00'))
                if date.tzinfo is None:
                    raise ValueError()
                when = date.timestamp()
            except ValueError:
                raise AppError('Schedule must include a timezone.')
        staged = []
        try:
            path = store.stage(audio.file, audio.filename or '')
            staged.append(path)
            cover = store.stage(artwork.file, artwork.filename or '', artwork=True) if artwork and artwork.filename else None
            if cover:
                staged.append(cover)
            job = store.enqueue(account, path, title or Path(audio.filename or 'Untitled').stem,
                artwork=cover, scheduled=when, description=description[:4000], genre=genre[:100],
                tag_list=tags[:1000], sharing=sharing)
            return {'id': job}
        except Exception:
            for path in staged:
                Path(path).unlink(missing_ok=True)
            raise
        finally:
            audio.file.close()
            if artwork:
                artwork.file.close()

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id: str):
        store.cancel(job_id)
        return {'ok': True}

    app.mount('/static', StaticFiles(directory=ASSETS), name='static')
    return app

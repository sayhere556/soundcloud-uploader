from __future__ import annotations
import asyncio
import io
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response, JSONResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from .core import Store, AppError, validate_art

ASSET_CONTENT = {}
ASSETS = Path(__file__).parent / 'static'

class NameInput(BaseModel):
    name: str = Field(min_length=1,max_length=32)
class LabelInput(BaseModel):
    label: str = Field(min_length=1,max_length=60)
class ConnectionInput(BaseModel):
    client_id: str = Field(min_length=1,max_length=512)
    client_secret: str = Field(min_length=1,max_length=2048)
    redirect_uri: str = Field(min_length=1,max_length=2048)
class ItemInput(BaseModel):
    asset: str
    title: str = Field(min_length=1,max_length=200)
class SubmitInput(BaseModel):
    account: str
    items: list[ItemInput] = Field(min_length=1,max_length=100)
    tape_title: str = Field(default='',max_length=200)
    visibility: str | None = None
    art: dict | None = None
    request_id: str

def create_app(store=None, run_worker=True):
    store=store or Store(); stop=threading.Event()
    def work():
        while not stop.is_set():
            try: store.work_once()
            except Exception: pass
            stop.wait(.7)
    @asynccontextmanager
    async def lifespan(app):
        thread=threading.Thread(target=work,daemon=True)
        if run_worker: thread.start()
        yield
        stop.set()
        if run_worker: await asyncio.to_thread(thread.join,2)
    app=FastAPI(title='sc / upload desk',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store
    hosts=['localhost','127.0.0.1','[::1]']
    for url in (os.getenv('SCM_REDIRECT_URI',''),os.getenv('SCM_PUBLIC_URL','')):
        if urlparse(url).hostname: hosts.append(urlparse(url).hostname)
    if os.getenv('CODESPACE_NAME'):
        hosts.append(os.environ['CODESPACE_NAME']+'-8085.'+os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN','app.github.dev'))
    @app.middleware('http')
    async def security(request,call_next):
        allowed=hosts+[urlparse(store.redirect_uri()).hostname]
        if request.url.hostname not in allowed: return Response('Invalid host',status_code=400)
        if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-scm-request')!='1':
            return JSONResponse({'detail':'Open the upload desk to perform this action.'},status_code=403)
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"})
        return response
    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc): return JSONResponse({'detail':'Check the supplied fields.'},status_code=422)
    @app.exception_handler(AppError)
    async def problem(request,exc): return JSONResponse({'detail':str(exc)},status_code=400)
    @app.exception_handler(Exception)
    async def unexpected(request,exc): return JSONResponse({'detail':'The operation could not complete. Try again after checking the supplied files.'},status_code=500)
    def asset(name):
        return ASSET_CONTENT[name] if name in ASSET_CONTENT else (ASSETS/name).read_text()
    @app.get('/')
    def index(): return HTMLResponse(asset('index.html'))
    @app.get('/static/{name}')
    def static(name:str):
        types={'app.js':'application/javascript','style.css':'text/css'}
        if name not in types: return Response(status_code=404)
        return Response(asset(name),media_type=types[name])
    @app.get('/health')
    def health(): return {'ok':True}
    @app.get('/api/state')
    def state():
        return {'accounts':store.accounts(),'defaults':store.defaults(),'connection':store.connection_info()}
    @app.post('/api/connection')
    def connection(data:ConnectionInput):
        return store.save_connection_settings(data.client_id,data.client_secret,data.redirect_uri)
    @app.post('/api/accounts/{account}/label')
    def label(account:str,data:LabelInput): return store.label_account(account,data.label)
    @app.get('/api/submissions/{request_id}')
    def submission(request_id:str): return store.submission_status(request_id)
    @app.post('/api/defaults')
    def defaults(data:dict): return store.save_defaults(data)
    @app.post('/api/accounts/{account}/import')
    def import_account(account:str,token_file:UploadFile=File(...)):
        try: return store.import_account(account,token_file.file)
        finally: token_file.file.close()
    @app.post('/api/accounts/connect')
    def connect(data:NameInput):
        return {'url':store.oauth_start(data.name)}
    @app.post('/api/accounts/{account}/disconnect')
    def disconnect(account:str): store.disconnect(account); return {'ok':True}
    @app.get('/auth/callback')
    def callback(state:str='',code:str=''):
        try:
            if not state or not code: raise AppError('Invalid callback.')
            store.oauth_finish(state,code)
        except AppError: return RedirectResponse('/?login=failed',status_code=303)
        return RedirectResponse('/?login=success',status_code=303)
    @app.post('/api/stage')
    def stage(audio:UploadFile=File(...)):
        try: return {'asset':store.stage_audio(audio.file,audio.filename or '')}
        finally: audio.file.close()
    @app.post('/api/artwork')
    def artwork(image:UploadFile=File(...)):
        try: return {'asset':store.save_art(image.file)}
        finally: image.file.close()
    @app.get('/api/artwork/{asset}')
    def artwork_image(asset:str): return Response(store.art_path(asset).read_bytes(),media_type='image/png')
    @app.post('/api/artwork/preview')
    def preview(data:dict):
        rendered=store.render_art(data)
        return Response(rendered,media_type='image/jpeg') if rendered is not None else Response(status_code=204)
    @app.post('/api/submit')
    def submit(data:SubmitInput):
        return store.submit(data.account,[item.model_dump() for item in data.items],data.tape_title,data.visibility,data.art,data.request_id)
    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id:str): store.cancel(job_id); return {'ok':True}
    return app

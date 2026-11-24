"""Shared account, API and durable queue services for the CLI and dashboard."""
from __future__ import annotations
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import time
from contextlib import contextmanager, ExitStack
from urllib.parse import urlencode, quote
import httpx
from filelock import FileLock, Timeout
from dotenv import load_dotenv

AUDIO = {'.wav', '.wave', '.flac', '.mp3', '.aiff', '.aif', '.m4a', '.ogg'}
ART = {'.jpg', '.jpeg', '.png'}
MAX_AUDIO = 4 * 1024**3
MAX_ART = 20 * 1024**2
API = 'https://api.soundcloud.com'
AUTH = 'https://secure.soundcloud.com'

class AppError(Exception):
    pass

class Store:
    def __init__(self, root=None, demo=False):
        load_dotenv(override=False)
        self.demo = demo
        self.root = Path(root or os.getenv('SCM_DATA_DIR', '.sc-manager-demo' if demo else '.sc-manager')).resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in ('accounts', 'uploads'):
            (self.root / name).mkdir(mode=0o700, exist_ok=True)
        self.db_path = self.root / 'manager.sqlite3'
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, account TEXT NOT NULL, title TEXT NOT NULL,
                audio TEXT NOT NULL, artwork TEXT, metadata TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued', created REAL NOT NULL,
                scheduled REAL NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
                error TEXT, result TEXT);
              CREATE TABLE IF NOT EXISTS oauth (
                state TEXT PRIMARY KEY, account TEXT NOT NULL, verifier TEXT NOT NULL,
                redirect TEXT NOT NULL, created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS demo_tracks (
                id TEXT PRIMARY KEY, account TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
        self.db_path.chmod(0o600)
        if demo:
            for account, username in [('main', 'Midnight Studio'), ('alt', 'After Hours'), ('label', 'Night Shift Records')]:
                path = self.account_path(account)
                if not path.exists():
                    self.save_account(account, {'username': username, 'demo': True})

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def account_path(self, account):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,32}', account):
            raise AppError('Account name must be 1–32 letters, numbers, dashes or underscores.')
        return self.root / 'accounts' / (account + '.json')

    def account(self, account):
        path = self.account_path(account)
        if not path.exists():
            raise AppError('Connect this account first.')
        return json.loads(path.read_text())

    def save_account(self, account, data):
        path = self.account_path(account)
        temp = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w') as out:
                json.dump(data, out)
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)

    def accounts(self):
        result = []
        for path in sorted((self.root / 'accounts').glob('*.json')):
            data = self.account(path.stem)
            result.append({'name': path.stem, 'username': data.get('username', path.stem), 'connected': True})
        return result

    def credentials(self):
        cid, secret = os.getenv('SOUNDCLOUD_CLIENT_ID'), os.getenv('SOUNDCLOUD_CLIENT_SECRET')
        if not cid or not secret:
            raise AppError('Set SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET, then restart the app.')
        return {'client_id': cid, 'client_secret': secret}

    def oauth_start(self, account):
        self.account_path(account)
        credentials = self.credentials()
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        state = secrets.token_urlsafe(32)
        redirect = os.getenv('SCM_REDIRECT_URI', 'http://127.0.0.1:8085/auth/callback')
        with self.db() as db:
            db.execute('DELETE FROM oauth WHERE created < ?', (time.time() - 600,))
            db.execute('INSERT INTO oauth VALUES (?,?,?,?,?)', (state, account, verifier, redirect, time.time()))
        return AUTH + '/authorize?' + urlencode({'client_id': credentials['client_id'], 'redirect_uri': redirect,
            'response_type': 'code', 'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state})

    def oauth_finish(self, state, code):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM oauth WHERE state=?', (state,)).fetchone()
            db.execute('DELETE FROM oauth WHERE state=?', (state,))
        if not row or row['created'] < time.time() - 600:
            raise AppError('Login expired or invalid. Start again from Accounts.')
        with FileLock(str(self.account_path(row['account'])) + '.lock'):
            tokens = self.token_exchange({'grant_type': 'authorization_code', 'code': code,
                'code_verifier': row['verifier'], 'redirect_uri': row['redirect']})
            self.save_account(row['account'], tokens)
        profile = self.request(row['account'], 'GET', '/me')
        with FileLock(str(self.account_path(row['account'])) + '.lock'):
            tokens = self.account(row['account'])
            tokens['username'] = profile.get('username', row['account'])
            self.save_account(row['account'], tokens)
        return row['account']

    def token_exchange(self, fields):
        try:
            response = httpx.post(AUTH + '/oauth/token', data={**self.credentials(), **fields}, timeout=30)
        except httpx.HTTPError:
            raise AppError('SoundCloud authentication could not be reached. Try connecting again.') from None
        if response.status_code != 200:
            raise AppError(f'SoundCloud authentication failed ({response.status_code}). Reconnect the account.')
        data = response.json()
        if not data.get('access_token'):
            raise AppError('SoundCloud returned no access token.')
        data['obtained_at'] = time.time()
        return data

    def token(self, account):
        with FileLock(str(self.account_path(account)) + '.lock'):
            data = self.account(account)
            if time.time() >= data.get('obtained_at', 0) + data.get('expires_in', 0) - 60:
                if not data.get('refresh_token'):
                    raise AppError('Session expired. Reconnect this account.')
                fresh = self.token_exchange({'grant_type': 'refresh_token', 'refresh_token': data['refresh_token']})
                data.update(fresh)
                self.save_account(account, data)
            return data['access_token']

    def request(self, account, method, path, **kwargs):
        token = self.token(account)
        try:
            with httpx.Client(base_url=API, timeout=httpx.Timeout(900, connect=30), follow_redirects=False) as client:
                response = client.request(method, path, headers={'Authorization': 'OAuth ' + token, 'Accept': 'application/json'}, **kwargs)
        except httpx.HTTPError:
            raise AppError('SoundCloud connection interrupted. Check SoundCloud before retrying an upload.') from None
        if not response.is_success:
            raise AppError(f'SoundCloud returned {response.status_code}. Check account access, quota and input. No automatic retry was made.')
        return response.json() if response.content else {}

    @staticmethod
    def public_track(track):
        return {key: track.get(key) for key in ('id', 'urn', 'title', 'description', 'genre', 'sharing', 'permalink_url', 'duration', 'playback_count', 'created_at')}

    def tracks(self, account, limit=50):
        self.account(account)
        if self.demo:
            with self.db() as db:
                rows = db.execute('SELECT payload FROM demo_tracks WHERE account=? ORDER BY rowid DESC', (account,)).fetchall()
            return [json.loads(row[0]) for row in rows]
        result = self.request(account, 'GET', '/me/tracks', params={'limit': max(1, min(200, limit)), 'linked_partitioning': 'true'})
        return [self.public_track(item) for item in (result if isinstance(result, list) else result.get('collection', []))]

    def edit_track(self, account, track_id, fields):
        if not fields or set(fields) - {'title', 'description', 'genre', 'sharing'}:
            raise AppError('No supported track changes provided.')
        if 'sharing' in fields and fields['sharing'] not in ('private', 'public'):
            raise AppError('Visibility must be private or public.')
        if 'title' in fields and not fields['title'].strip():
            raise AppError('Title cannot be blank.')
        if self.demo:
            with self.db() as db:
                row = db.execute('SELECT payload FROM demo_tracks WHERE id=? AND account=?', (str(track_id), account)).fetchone()
                if not row:
                    raise AppError('Track not found.')
                track = json.loads(row[0]); track.update(fields)
                db.execute('UPDATE demo_tracks SET payload=? WHERE id=?', (json.dumps(track), str(track_id)))
            return track
        return self.public_track(self.request(account, 'PUT', '/tracks/' + quote(str(track_id), safe=''), json={'track': fields}))

    def disconnect(self, account):
        with FileLock(str(self.account_path(account)) + '.lock'):
            with self.db() as db:
                active = db.execute("SELECT 1 FROM jobs WHERE account=? AND state IN ('queued','uploading')", (account,)).fetchone()
            if active:
                raise AppError('Finish or cancel this account’s queued uploads before disconnecting.')
        if not self.demo:
            self.request(account, 'POST', '/disconnect')
        self.account_path(account).unlink(missing_ok=True)

    def stage(self, source, filename, artwork=False):
        suffix = Path(filename).suffix.lower()
        if suffix not in (ART if artwork else AUDIO):
            raise AppError('Choose a JPG/PNG cover.' if artwork else 'Choose a WAV, FLAC, MP3, AIFF, M4A or OGG file.')
        dest = self.root / 'uploads' / (secrets.token_hex(16) + suffix)
        limit = MAX_ART if artwork else MAX_AUDIO
        count = 0
        try:
            with dest.open('xb') as out:
                while chunk := source.read(1024 * 1024):
                    count += len(chunk)
                    if count > limit:
                        raise AppError('File exceeds the 20 MB cover or 4 GB audio limit.')
                    out.write(chunk)
            if count == 0:
                raise AppError('The selected file is empty.')
            return str(dest)
        except Exception:
            dest.unlink(missing_ok=True)
            raise

    def enqueue(self, account, audio, title, artwork=None, scheduled=None, **metadata):
        self.account(account)
        if not title.strip() or len(title) > 200:
            raise AppError('Title must contain 1–200 characters.')
        if metadata.get('sharing', 'private') not in ('private', 'public'):
            raise AppError('Visibility must be private or public.')
        metadata.setdefault('sharing', 'private')
        job_id = secrets.token_hex(8)
        with self.db() as db:
            db.execute('INSERT INTO jobs(id,account,title,audio,artwork,metadata,created,scheduled) VALUES(?,?,?,?,?,?,?,?)',
                (job_id, account, title.strip(), audio, artwork, json.dumps(metadata), time.time(), scheduled or time.time()))
        return job_id

    def jobs(self):
        with self.db() as db:
            rows = db.execute('SELECT id,account,title,state,created,scheduled,progress,error,result FROM jobs ORDER BY created DESC LIMIT 200').fetchall()
        return [dict(row) for row in rows]

    def cancel(self, job_id):
        with self.db() as db:
            cursor = db.execute("UPDATE jobs SET state='cancelled' WHERE id=? AND state='queued'", (job_id,))
        if not cursor.rowcount:
            raise AppError('Only waiting uploads can be cancelled.')

    def work_once(self):
        try:
            with FileLock(str(self.root / 'worker.lock'), timeout=0):
                return self._work_locked()
        except Timeout:
            return False

    def _work_locked(self):
        with self.db() as db:
            # Owning the worker lock proves any older uploading row was interrupted.
            db.execute("UPDATE jobs SET state='needs_review',error='Worker interrupted. Check SoundCloud before uploading again.' WHERE state='uploading'")
            db.execute('BEGIN IMMEDIATE') if not db.in_transaction else None
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND scheduled<=? ORDER BY created LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return False
            db.execute("UPDATE jobs SET state='uploading',progress=5 WHERE id=?", (row['id'],))
        try:
            if self.demo:
                for value in (20, 45, 75, 95):
                    time.sleep(0.25)
                    with self.db() as db:
                        db.execute('UPDATE jobs SET progress=? WHERE id=?', (value, row['id']))
                track = {'id': row['id'], 'title': row['title'], **json.loads(row['metadata']), 'playback_count': 0, 'duration': 0}
                with self.db() as db:
                    db.execute('INSERT INTO demo_tracks VALUES(?,?,?)', (row['id'], row['account'], json.dumps(track)))
            else:
                with ExitStack() as stack:
                    audio = stack.enter_context(open(row['audio'], 'rb'))
                    files = {'track[asset_data]': (Path(row['audio']).name, audio, 'application/octet-stream')}
                    if row['artwork']:
                        cover = stack.enter_context(open(row['artwork'], 'rb'))
                        files['track[artwork_data]'] = (Path(row['artwork']).name, cover, mimetypes.guess_type(row['artwork'])[0])
                    fields = {'track[title]': row['title']}
                    fields.update({f'track[{k}]': str(v) for k,v in json.loads(row['metadata']).items() if v is not None})
                    track = self.public_track(self.request(row['account'], 'POST', '/tracks', data=fields, files=files))
            with self.db() as db:
                db.execute("UPDATE jobs SET state='succeeded',progress=100,result=? WHERE id=?", (json.dumps(track), row['id']))
            for path in (row['audio'], row['artwork']):
                if path:
                    Path(path).unlink(missing_ok=True)
        except Exception as exc:
            message = str(exc) if isinstance(exc, AppError) else 'Upload interrupted. Check SoundCloud before submitting it again.'
            with self.db() as db:
                db.execute("UPDATE jobs SET state='needs_review',error=? WHERE id=?", (message, row['id']))
        return True

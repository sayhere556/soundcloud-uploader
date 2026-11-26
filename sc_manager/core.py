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

class AccountStore:
    def __init__(self, root=None):
        load_dotenv(override=False)
        self.root = Path(root or os.getenv('SCM_DATA_DIR', '.sc-manager')).resolve()
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
            ''')
        self.db_path.chmod(0o600)

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
        result=[]
        for path in sorted((self.root/'accounts').glob('*.json')):
            data=self.account(path.stem)
            result.append({'name':path.stem,'label':data.get('label',path.stem),
                'username':data.get('username',path.stem),'connected':True})
        return result
    def label_account(self, account, label):
        label=label.strip()
        if not 1<=len(label)<=60: raise AppError('Use a label of 1–60 characters.')
        with FileLock(str(self.account_path(account))+'.lock'):
            data=self.account(account);data['label']=label;self.save_account(account,data)
        return {'ok':True}

    def settings(self):
        path=self.root/'app-settings.json'
        return json.loads(path.read_text()) if path.exists() else {}
    def credentials(self):
        saved=self.settings()
        cid=os.getenv('SOUNDCLOUD_CLIENT_ID') or saved.get('client_id')
        secret=os.getenv('SOUNDCLOUD_CLIENT_SECRET') or saved.get('client_secret')
        if not cid or not secret: raise AppError('Add your SoundCloud app credentials in Accounts → Connection settings.')
        return {'client_id':cid,'client_secret':secret}
    def redirect_uri(self):
        return os.getenv('SCM_REDIRECT_URI') or self.settings().get('redirect_uri') or 'http://127.0.0.1:8085/auth/callback'
    def connection_info(self):
        try: self.credentials(); configured=True
        except AppError: configured=False
        return {'configured':configured,'redirect_uri':self.redirect_uri(),
                'managed_by_environment':bool(os.getenv('SOUNDCLOUD_CLIENT_ID') or os.getenv('SOUNDCLOUD_CLIENT_SECRET'))}
    def save_connection_settings(self, client_id, client_secret, redirect_uri):
        if self.connection_info()['managed_by_environment']:
            raise AppError('Credentials are already supplied by the environment. Update them there.')
        client_id=client_id.strip(); client_secret=client_secret.strip(); redirect_uri=redirect_uri.strip()
        parsed=urlparse(redirect_uri)
        if not client_id or not client_secret or len(client_id)>512 or len(client_secret)>2048:
            raise AppError('Enter both SoundCloud app credentials.')
        if (parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path!='/auth/callback'
            or (parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'))):
            raise AppError('Use an HTTPS callback ending in /auth/callback, or HTTP on localhost.')
        with FileLock(str(self.root/'app-settings.lock')):
            dest=self.root/'app-settings.json';tmp=dest.with_name('app-settings.'+secrets.token_hex(8)+'.tmp')
            try:
                fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w') as out: json.dump({'client_id':client_id,'client_secret':client_secret,'redirect_uri':redirect_uri},out)
                os.replace(tmp,dest)
            finally: tmp.unlink(missing_ok=True)
        return self.connection_info()

    def oauth_start(self, account):
        self.account_path(account)
        credentials = self.credentials()
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        state = secrets.token_urlsafe(32)
        redirect = self.redirect_uri()
        with self.db() as db:
            db.execute('DELETE FROM oauth WHERE created < ?', (time.time() - 600,))
            db.execute('INSERT INTO oauth VALUES (?,?,?,?,?)', (state, account, verifier, redirect, time.time()))
        return AUTH + '/authorize?' + urlencode({'client_id': credentials['client_id'], 'redirect_uri': redirect,
            'response_type': 'code', 'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': state})

    def oauth_finish(self, state, code):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM oauth WHERE state=?',(state,)).fetchone()
            db.execute('DELETE FROM oauth WHERE state=?',(state,))
        if not row or row['created']<time.time()-600 or not code:
            raise AppError('Login expired or invalid. Start again from Accounts.')
        tokens=self.token_exchange({'grant_type':'authorization_code','code':code,
            'code_verifier':row['verifier'],'redirect_uri':row['redirect']})
        try:
            response=httpx.get(API+'/me',headers={'Authorization':'OAuth '+tokens['access_token']},timeout=30)
            if not response.is_success: raise AppError('Could not verify the connected account. Try linking again.')
            profile=response.json()
        except httpx.HTTPError: raise AppError('Could not verify the connected account. Try linking again.') from None
        with FileLock(str(self.account_path(row['account']))+'.lock'):
            previous=self.account(row['account']) if self.account_path(row['account']).exists() else {}
            if previous.get('user_id') and str(previous['user_id'])!=str(profile.get('id')):
                raise AppError('This is a different SoundCloud account. Add it with a new account name.')
            tokens.update(username=profile.get('username',row['account']),user_id=profile.get('id'),label=previous.get('label',row['account']))
            self.save_account(row['account'],tokens)
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



    def disconnect(self, account):
        # Serialize with uploads so disconnect cannot race a playlist request.
        try:
            with FileLock(str(self.root/'worker.lock'),timeout=0):
                with self.db() as db:
                    active=db.execute("SELECT 1 FROM jobs WHERE account=? AND state IN ('queued','uploading')",(account,)).fetchone()
                    tape=db.execute("SELECT 1 FROM tapes WHERE account=? AND state IN ('queued','creating')",(account,)).fetchone()
                if active or tape: raise AppError('Finish or cancel this account’s waiting uploads before disconnecting.')
                self.request(account, 'POST', '/disconnect')
                with FileLock(str(self.account_path(account))+'.lock'):
                    self.account_path(account).unlink(missing_ok=True)
                if self.defaults().get('account')==account: self.save_defaults({'account':''})
        except Timeout: raise AppError('An upload is in progress. Try disconnecting after it finishes.') from None

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




    def work_once(self):
        try:
            with FileLock(str(self.root / 'worker.lock'), timeout=0):
                return self._work_locked()
        except Timeout:
            return False


# Upload desk: persistent defaults, image preparation and ordered tapes.
import io
import math
import warnings
from urllib.parse import urlparse
from PIL import Image, ImageOps

BASE_DEFAULTS = {'visibility': 'private', 'art': {'source': 'none', 'color': '#000000',
    'asset': '', 'url': '', 'fit': 'crop', 'fill': '#ffffff', 'zoom': 1.0, 'x': 0.5, 'y': 0.5}}


def validate_art(options):
    art = {**BASE_DEFAULTS['art'], **options}
    if set(options) - set(BASE_DEFAULTS['art']):
        raise AppError('Unknown artwork setting.')
    if art['source'] not in ('none', 'solid', 'file') or art['fit'] not in ('crop','fill'):
        raise AppError('Choose no artwork, a solid color or an image, and crop or fill.')
    for field in ('color','fill'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', art[field]):
            raise AppError('Colors must be six-digit hex values, such as #111111.')
    for field, low, high in (('zoom',1,4),('x',0,1),('y',0,1)):
        art[field] = float(art[field])
        if not math.isfinite(art[field]) or not low <= art[field] <= high:
            raise AppError('Crop position or zoom is out of range.')
    if art['asset'] and not re.fullmatch(r'[a-f0-9]{32}\.png', art['asset']):
        raise AppError('Invalid artwork asset.')
    if len(art['url']) > 2048:
        raise AppError('Artwork reference is too long.')
    return art

class Store(AccountStore):
    def __init__(self, root=None):
        super().__init__(root)
        (self.root / 'artwork').mkdir(mode=0o700, exist_ok=True)
        with self.db() as db:
            columns = {r['name'] for r in db.execute('PRAGMA table_info(jobs)')}
            for name, type_ in [('tape_id','TEXT'),('position','INTEGER DEFAULT 0')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {type_}')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS tapes (
                id TEXT PRIMARY KEY, account TEXT, title TEXT, sharing TEXT, artwork TEXT,
                state TEXT DEFAULT 'queued', created REAL, error TEXT, result TEXT);
              CREATE TABLE IF NOT EXISTS staged_audio (
                id TEXT PRIMARY KEY, path TEXT, created REAL, used INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, result TEXT);
            ''')

    def defaults(self):
        path = self.root / 'defaults.json'
        saved = json.loads(path.read_text()) if path.exists() else {}
        legacy=saved.get('art',{})
        if legacy.get('source')=='pinterest':
            legacy['source']='file' if legacy.get('asset') else 'none';legacy['url']=''
        return {'account':saved.get('account',''), 'visibility': saved.get('visibility','private'),
                'art': validate_art(saved.get('art', BASE_DEFAULTS['art']))}

    def save_defaults(self, data):
        if set(data) - {'account','visibility','art'}:
            raise AppError('Unknown default setting.')
        with FileLock(str(self.root / 'defaults.lock')):
            current = self.defaults()
            current.update(data)
            if current.get('account'): self.account(current['account'])
            if current['visibility'] not in ('private','public'):
                raise AppError('Default visibility must be private or public.')
            current['art'] = validate_art(current['art'])
            if current['art']['source'] not in ('none','solid') and not current['art']['asset']:
                raise AppError('Load an image before saving it as the default.')
            if current['art']['asset']:
                self.art_path(current['art']['asset'])
            dest = self.root / 'defaults.json'
            tmp = dest.with_suffix('.tmp')
            tmp.write_text(json.dumps(current, indent=2)); tmp.chmod(0o600)
            os.replace(tmp, dest)
        return current

    def art_path(self, asset):
        if not re.fullmatch(r'[a-f0-9]{32}\.png', asset):
            raise AppError('Invalid artwork reference.')
        path = self.root / 'artwork' / asset
        if not path.is_file():
            raise AppError('Artwork is missing. Load it again.')
        return path

    def save_art(self, source):
        raw = source.read(MAX_ART + 1)
        if len(raw) > MAX_ART:
            raise AppError('Artwork must be 20 MB or smaller.')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > 40_000_000:
                        raise AppError('Artwork is too large. Use an image below 40 megapixels.')
                    image = ImageOps.exif_transpose(image).convert('RGBA')
                    image.thumbnail((4000,4000), Image.Resampling.LANCZOS)
                    asset = secrets.token_hex(16) + '.png'
                    image.save(self.root / 'artwork' / asset, format='PNG')
                    return asset
        except AppError:
            raise
        except Exception:
            raise AppError('This image could not be opened. Use a JPG, PNG or WebP image.') from None


    def render_art(self, options, size=3000):
        art = validate_art(options)
        if art['source']=='none': return None
        canvas = Image.new('RGB',(size,size), art['color'] if art['source']=='solid' else art['fill'])
        if art['source'] != 'solid':
            with Image.open(self.art_path(art['asset'])) as image:
                image = image.convert('RGBA')
                scale = (max if art['fit']=='crop' else min)(size/image.width, size/image.height) * art['zoom']
                width, height = max(1,round(image.width*scale)), max(1,round(image.height*scale))
                left, top = round((size-width)*art['x']), round((size-height)*art['y'])
                # Render directly into the output square: panoramic inputs must not
                # allocate an enormous intermediate image when cropped or zoomed.
                sx, sy = image.width / width, image.height / height
                layer = image.transform((size,size), Image.Transform.AFFINE,
                    (sx,0,-left*sx,0,sy,-top*sy), Image.Resampling.BICUBIC,
                    fillcolor=(0,0,0,0))
                canvas.paste(layer, (0,0), layer)
        out=io.BytesIO(); canvas.save(out,format='JPEG',quality=94,subsampling=0)
        return out.getvalue()

    def stage_audio(self, stream, filename):
        path = self.stage(stream, filename)
        asset = Path(path).name
        with self.db() as db:
            db.execute('INSERT INTO staged_audio(id,path,created) VALUES(?,?,?)',(asset,path,time.time()))
        return asset

    def submit(self, account, items, tape_title='', visibility=None, art=None, request_id=None):
        self.account(account)
        if not items or len(items)>100:
            raise AppError('Choose between 1 and 100 audio files.')
        defaults = self.defaults(); visibility = visibility or defaults['visibility']
        if visibility not in ('public','private'): raise AppError('Invalid visibility.')
        tape_title = tape_title.strip()
        if len(tape_title)>200: raise AppError('Tape title is too long.')
        seen=set()
        for item in items:
            if set(item) != {'asset','title'} or not isinstance(item['title'],str) or not 1<=len(item['title'].strip())<=200:
                raise AppError('Every track needs a title of 1–200 characters.')
            if item['asset'] in seen: raise AppError('The same staged file cannot be submitted twice.')
            seen.add(item['asset'])
        request_id = request_id or secrets.token_hex(16)
        if not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', request_id): raise AppError('Invalid submission identifier.')
        with self.db() as db:
            prior = db.execute('SELECT result FROM submissions WHERE id=?',(request_id,)).fetchone()
        if prior: return json.loads(prior['result'])
        cover = self.render_art(art or defaults['art'])
        tape_id = secrets.token_hex(8) if tape_title else None
        created=time.time(); output=[]; copies=[]
        try:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                prior=db.execute('SELECT result FROM submissions WHERE id=?',(request_id,)).fetchone()
                if prior: return json.loads(prior['result'])
                for position,item in enumerate(items):
                    row=db.execute('SELECT * FROM staged_audio WHERE id=? AND used=0',(item['asset'],)).fetchone()
                    if not row or not Path(row['path']).is_file(): raise AppError('A file was already submitted or is missing. Add it again.')
                    job=secrets.token_hex(8)
                    cover_path=None
                    if cover is not None:
                        cover_path=self.root/'uploads'/(job+'.jpg'); cover_path.write_bytes(cover); copies.append(cover_path)
                    db.execute('INSERT INTO jobs(id,account,title,audio,artwork,metadata,created,scheduled,tape_id,position) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (job,account,item['title'].strip(),row['path'],str(cover_path) if cover_path else None,json.dumps({'sharing':visibility}),created+position/1e6,created,tape_id,position))
                    db.execute('UPDATE staged_audio SET used=1 WHERE id=?',(item['asset'],))
                    output.append(job)
                if tape_id:
                    tape_cover=None
                    if cover is not None:
                        tape_cover=self.root/'uploads'/(tape_id+'-tape.jpg'); tape_cover.write_bytes(cover); copies.append(tape_cover)
                    db.execute('INSERT INTO tapes(id,account,title,sharing,artwork,created) VALUES(?,?,?,?,?,?)',
                      (tape_id,account,tape_title,visibility,str(tape_cover) if tape_cover else None,created))
                result={'jobs':output,'tape_id':tape_id}
                db.execute('INSERT INTO submissions VALUES(?,?)',(request_id,json.dumps(result)))
            return result
        except Exception:
            for path in copies: path.unlink(missing_ok=True)
            raise

    def jobs(self):
        with self.db() as db:
            rows=db.execute('SELECT id,account,title,state,created,progress,error,result,tape_id,position FROM jobs ORDER BY created DESC LIMIT 200').fetchall()
        return [dict(row) for row in rows]

    def tapes(self):
        with self.db() as db:
            rows=db.execute('SELECT id,account,title,sharing,state,created,error,result FROM tapes ORDER BY created DESC LIMIT 100').fetchall()
        return [dict(row) for row in rows]

    def cancel(self, job_id):
        with self.db() as db:
            row=db.execute('SELECT tape_id,state FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row or row['state']!='queued': raise AppError('Only waiting uploads can be cancelled.')
            if row['tape_id']:
                db.execute("UPDATE tapes SET state='cancelled' WHERE id=?",(row['tape_id'],))
                db.execute("UPDATE jobs SET state='cancelled' WHERE tape_id=? AND state='queued'",(row['tape_id'],))
            else:
                db.execute("UPDATE jobs SET state='cancelled' WHERE id=?",(job_id,))

    def _work_locked(self):
        with self.db() as db:
            db.execute("UPDATE tapes SET state='needs_review',error='Interrupted. Check SoundCloud before submitting again.' WHERE state='creating' OR id IN (SELECT tape_id FROM jobs WHERE state='uploading')")
            db.execute("UPDATE jobs SET state='needs_review',error='Interrupted. Check SoundCloud before submitting again.' WHERE state='uploading'")
            row=db.execute("""SELECT j.* FROM jobs j LEFT JOIN tapes t ON j.tape_id=t.id
                WHERE j.state='queued' AND j.scheduled<=? AND (j.tape_id IS NULL OR
                (t.state='queued' AND NOT EXISTS (SELECT 1 FROM jobs prior WHERE prior.tape_id=j.tape_id AND prior.position<j.position AND prior.state!='succeeded')))
                ORDER BY j.created LIMIT 1""",(time.time(),)).fetchone()
            if row: db.execute("UPDATE jobs SET state='uploading',progress=5 WHERE id=?",(row['id'],))
        if row:
            try:
                with ExitStack() as stack:
                    audio=stack.enter_context(open(row['audio'],'rb'))
                    cover=stack.enter_context(open(row['artwork'],'rb')) if row['artwork'] else None
                    files={'track[asset_data]':(Path(row['audio']).name,audio,'application/octet-stream')}
                    if cover: files['track[artwork_data]']=('cover.jpg',cover,'image/jpeg')
                    fields={'track[title]':row['title'],**{f'track[{k}]':str(v) for k,v in json.loads(row['metadata']).items() if v is not None}}
                    track=self.public_track(self.request(row['account'],'POST','/tracks',data=fields,files=files))
                with self.db() as db:
                    db.execute("UPDATE jobs SET state='succeeded',progress=100,result=? WHERE id=?",(json.dumps(track),row['id']))
                for path in (row['audio'],row['artwork']):
                    if path: Path(path).unlink(missing_ok=True)
            except Exception as exc:
                message=str(exc) if isinstance(exc,AppError) else 'Upload interrupted. Check SoundCloud before submitting again.'
                with self.db() as db:
                    db.execute("UPDATE jobs SET state='needs_review',error=? WHERE id=?",(message,row['id']))
                    if row['tape_id']:
                        db.execute("UPDATE tapes SET state='needs_review',error=? WHERE id=?",(message,row['tape_id']))
                return True
        with self.db() as db:
            tape=db.execute("""SELECT t.* FROM tapes t WHERE t.state='queued'
                AND EXISTS(SELECT 1 FROM jobs WHERE tape_id=t.id)
                AND NOT EXISTS(SELECT 1 FROM jobs WHERE tape_id=t.id AND state!='succeeded') ORDER BY t.created LIMIT 1""").fetchone()
            if tape:
                db.execute("UPDATE tapes SET state='creating' WHERE id=?",(tape['id'],))
                tracks=[json.loads(r['result']) for r in db.execute('SELECT result FROM jobs WHERE tape_id=? ORDER BY position',(tape['id'],))]
        if tape:
            try:
                urns=[track.get('urn') or 'soundcloud:tracks:'+str(track['id']) for track in tracks]
                with ExitStack() as stack:
                    cover=stack.enter_context(open(tape['artwork'],'rb')) if tape['artwork'] else None
                    raw=self.request(tape['account'],'POST','/playlists',data={
                        'playlist[title]':tape['title'],'playlist[sharing]':tape['sharing'],
                        'playlist[tracks][][urn]':','.join(urns)},files={'playlist[artwork_data]':('cover.jpg',cover,'image/jpeg')} if cover else None)
                playlist={key:raw.get(key) for key in ('id','urn','title','sharing','permalink_url')}
                with self.db() as db:
                    db.execute("UPDATE tapes SET state='succeeded',result=? WHERE id=?",(json.dumps(playlist),tape['id']))
                if tape['artwork']: Path(tape['artwork']).unlink(missing_ok=True)
            except Exception as exc:
                message=str(exc) if isinstance(exc,AppError) else 'Playlist creation interrupted. Check SoundCloud before retrying.'
                with self.db() as db:
                    db.execute("UPDATE tapes SET state='needs_review',error=? WHERE id=?",(message,tape['id']))
        return bool(row or tape)

    def submission_status(self, request_id):
        with self.db() as db:
            saved=db.execute('SELECT result FROM submissions WHERE id=?',(request_id,)).fetchone()
            if not saved: raise AppError('Upload not found.')
            result=json.loads(saved['result'])
            jobs=[db.execute('SELECT state,error FROM jobs WHERE id=?',(job,)).fetchone() for job in result['jobs']]
            tape=db.execute('SELECT state,error FROM tapes WHERE id=?',(result['tape_id'],)).fetchone() if result['tape_id'] else None
        problem=next((job for job in jobs if job['state'] in ('needs_review','cancelled')),None)
        if tape and tape['state'] in ('needs_review','cancelled'): problem=tape
        complete=sum(job['state']=='succeeded' for job in jobs)
        status='needs_review' if problem else ('succeeded' if complete==len(jobs) and (not tape or tape['state']=='succeeded') else 'uploading')
        return {'state':status,'completed':complete,'total':len(jobs),'playlist':bool(tape),'error':problem['error'] if problem else None}

    def import_account(self, account, source):
        self.account_path(account)
        raw=source.read(65537)
        if len(raw)>65536: raise AppError('Choose a token JSON file smaller than 64 KB.')
        try: data=json.loads(raw)
        except (ValueError,UnicodeError): raise AppError('This file is not valid JSON.') from None
        if not isinstance(data,dict): raise AppError('The token JSON must contain an object.')
        access=data.get('access_token');refresh=data.get('refresh_token','')
        if not isinstance(access,str) or not access.strip() or len(access)>8192 or not access.isascii() or any(ord(c)<33 or ord(c)==127 for c in access):
            raise AppError('The JSON needs a valid access_token string.')
        if not isinstance(refresh,str) or len(refresh)>8192 or any(c.isspace() for c in refresh):
            raise AppError('The JSON refresh_token must be a string.')
        try:
            expires=float(data.get('expires_in',3600));obtained=float(data.get('obtained_at',time.time()))
            if not math.isfinite(expires) or not math.isfinite(obtained) or not 0<expires<=31536000 or obtained<0: raise ValueError()
        except (TypeError,ValueError): raise AppError('expires_in and obtained_at must be valid numbers.') from None
        tokens={'access_token':access,'refresh_token':refresh,'token_type':str(data.get('token_type','Bearer'))[:32],
            'expires_in':expires,'obtained_at':obtained,'scope':str(data.get('scope',''))[:2048]}
        with FileLock(str(self.account_path(account))+'.lock'):
            if self.account_path(account).exists(): raise AppError('This account name already exists. Use a different name to preserve it.')
            try:
                response=httpx.get(API+'/me',headers={'Authorization':'OAuth '+tokens['access_token']},timeout=30)
                if response.status_code==401: raise AppError('This token has expired or is invalid. Import a fresh JSON file or link with SoundCloud.')
                if not response.is_success: raise AppError('SoundCloud could not validate this token. Import a current token JSON file.')
                profile=response.json()
                if not isinstance(profile,dict) or not profile.get('id'): raise AppError('SoundCloud could not identify this account.')
            except httpx.HTTPError: raise AppError('SoundCloud could not be reached. No account was saved.') from None
            except ValueError: raise AppError('SoundCloud returned an unreadable account response. No account was saved.') from None
            tokens.update(username=profile.get('username',account),user_id=profile['id'],label=account)
            self.save_account(account,tokens)
        return {'name':account,'username':tokens['username'],'connected':True}

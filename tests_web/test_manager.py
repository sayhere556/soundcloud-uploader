import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import pytest
import httpx
from PIL import Image
from fastapi.testclient import TestClient
from sc_manager.core import Store, AppError, validate_art
from sc_manager.web import create_app
from sc_manager.cli import main

HEADERS={'X-SCM-Request':'1'}
@pytest.fixture
def store(tmp_path): return Store(tmp_path/'data',demo=True)
@pytest.fixture
def client(store):
    with TestClient(create_app(store,run_worker=False),base_url='http://localhost') as result: yield result

def stage(store,name='mix.wav'):
    return store.stage_audio(io.BytesIO(b'RIFF-test-wave'),name)

def test_upload_desk_has_no_track_management(client):
    page=client.get('/').text
    assert 'Upload desk' in page and 'Tape' in page
    assert all(text not in page for text in ('Your tracks','Edit track','Upload activity','Load sample files','DEMO'))
    assert '3000 × 3000' in page and 'No artwork' in page
    assert all(color in page for color in ('#000000','#ffffff','#6e5191'))
    assert 'jobs' not in client.get('/api/state').json() and 'tapes' not in client.get('/api/state').json()
    assert client.get('/api/tracks/main').status_code==404
    assert client.get('/api/state').json()['defaults']['visibility']=='private'
    assert 'access_token' not in client.get('/api/state').text

def test_defaults_persist_between_cli_and_web(store,client,capsys):
    assert main(['--demo','--data-dir',str(store.root),'defaults','--visibility','public','--art','#123456'])==0
    data=client.get('/api/state').json()['defaults']
    assert data['visibility']=='public' and data['art']['color']=='#123456'
    result=client.post('/api/defaults',headers=HEADERS,json={'visibility':'private','art':data['art']})
    assert result.status_code==200
    assert Store(store.root,demo=True).defaults()['visibility']=='private'

def test_solid_crop_fill_and_saved_image(store):
    solid=Image.open(io.BytesIO(store.render_art({'source':'solid','color':'#ff0000'})))
    assert solid.size==(3000,3000) and solid.getpixel((100,100))[0]>250
    source=Image.new('RGB',(200,100),'red'); source.paste('blue',(100,0,200,100))
    raw=io.BytesIO();source.save(raw,format='PNG');raw.seek(0)
    asset=store.save_art(raw)
    left=Image.open(io.BytesIO(store.render_art({'source':'file','asset':asset,'x':0})))
    right=Image.open(io.BytesIO(store.render_art({'source':'file','asset':asset,'x':1})))
    assert left.getpixel((1500,1500))[0]>250 and right.getpixel((1500,1500))[2]>250
    fill=Image.open(io.BytesIO(store.render_art({'source':'file','asset':asset,'fit':'fill','fill':'#00ff00'})))
    assert fill.getpixel((700,30))[1]>250
    saved=store.save_defaults({'art':{'source':'file','asset':asset,'fit':'fill','fill':'#00ff00'}})
    assert saved['art']['asset']==asset
    assert Store(store.root,demo=True).defaults()['art']['fit']=='fill'

def test_tape_order_visibility_cover_and_exactly_one_playlist(tmp_path,monkeypatch):
    store=Store(tmp_path/'real');store.save_account('main',{'username':'Mock'})
    tracks=[];playlists=[]
    def request(account,method,path,**kwargs):
        assert account=='main' and method=='POST'
        if path=='/tracks':
            assert kwargs['data']['track[sharing]']=='public'
            assert kwargs['files']['track[artwork_data]'][1].read(2)==b'\xff\xd8'
            tracks.append(kwargs['data']['track[title]'])
            return {'id':len(tracks),'urn':f'soundcloud:tracks:{len(tracks)}','title':tracks[-1]}
        assert path=='/playlists'
        playlists.append(kwargs['data'])
        assert kwargs['data']['playlist[sharing]']=='public'
        assert kwargs['files']['playlist[artwork_data]'][1].read(2)==b'\xff\xd8'
        return {'id':9,'title':'Tape'}
    monkeypatch.setattr(store,'request',request)
    items=[{'asset':stage(store,'z.wav'),'title':'Second file first'},{'asset':stage(store,'a.wav'),'title':'First file second'}]
    result=store.submit('main',items,'Tape',visibility='public',art={'source':'solid'},request_id='same-request-123456')
    assert store.submit('main',items,'Tape',visibility='public',request_id='same-request-123456')==result
    for _ in range(4): store.work_once()
    assert tracks==['Second file first','First file second']
    assert len(playlists)==1 and playlists[0]['playlist[tracks][][urn]']=='soundcloud:tracks:1,soundcloud:tracks:2'
    assert store.tapes()[0]['state']=='succeeded'
    assert not store.work_once()

def test_failed_tape_does_not_continue_or_make_playlist(store,monkeypatch):
    store.demo=False
    calls=[]
    def fail(*args,**kwargs): calls.append(args);raise AppError('Check SoundCloud before retrying.')
    monkeypatch.setattr(store,'request',fail)
    store.submit('main',[{'asset':stage(store),'title':'One'},{'asset':stage(store),'title':'Two'}],'Tape')
    assert store.work_once()
    assert not store.work_once()
    assert len(calls)==1 and store.tapes()[0]['state']=='needs_review'

def test_invalid_art_and_path_are_rejected(store):
    with pytest.raises(AppError): validate_art({'zoom':float('nan')})
    with pytest.raises(AppError): validate_art({'fill':'red'})
    with pytest.raises(AppError): store.art_path('../../secrets')
    with pytest.raises(AppError): store.save_art(io.BytesIO(b'not-image'))
    with pytest.raises(AppError): store.account_path('../escape')

def test_pinterest_redirect_and_domain_limits(store,monkeypatch):
    with pytest.raises(AppError): store.pinterest('http://127.0.0.1/private')
    with pytest.raises(AppError): store.pinterest('https://i.pinimg.com.evil.example/image.jpg')
    with pytest.raises(AppError): store.pinterest('https://user:password@i.pinimg.com/image.jpg')
    image=io.BytesIO();Image.new('RGB',(30,30),'blue').save(image,format='PNG')
    def handler(request):
        if request.url.host=='www.pinterest.com': return httpx.Response(200,text='<meta property="og:image" content="https://i.pinimg.com/test.png">')
        return httpx.Response(200,content=image.getvalue())
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    asset=store.pinterest('https://www.pinterest.com/pin/123/')
    assert store.art_path(asset).exists()

def test_stage_submit_and_cancel_api(client,store):
    staged=client.post('/api/stage',headers=HEADERS,files={'audio':('mix.wav',b'RIFF-mock')}).json()
    result=client.post('/api/submit',headers=HEADERS,json={'account':'main','items':[{'asset':staged['asset'],'title':'Mix'}],'request_id':'test-submit-123456'})
    assert result.status_code==200
    job=result.json()['jobs'][0]
    assert client.post('/api/jobs/'+job+'/cancel',headers=HEADERS).status_code==200
    assert not store.work_once()

def test_submit_atomic_on_bad_staged_asset(store):
    asset=stage(store)
    with pytest.raises(AppError): store.submit('main',[{'asset':asset,'title':'Good'},{'asset':'missing.wav','title':'Missing'}],'Tape')
    assert store.jobs()==[] and store.tapes()==[]
    with store.db() as db: assert db.execute('SELECT used FROM staged_audio WHERE id=?',(asset,)).fetchone()[0]==0
    assert len(list((store.root/'uploads').glob('*.jpg')))==0

def test_interrupted_tape_requires_review(store):
    result=store.submit('main',[{'asset':stage(store),'title':'One'},{'asset':stage(store),'title':'Two'}],'Tape')
    with store.db() as db: db.execute("UPDATE jobs SET state='uploading' WHERE id=?",(result['jobs'][0],))
    assert not store.work_once()
    assert store.tapes()[0]['state']=='needs_review'

def test_auth_lock_storage_and_oauth_state(tmp_path,monkeypatch):
    store=Store(tmp_path/'real');calls=[]
    store.save_account('main',{'access_token':'old','refresh_token':'refresh','expires_in':1,'obtained_at':0})
    def exchange(fields): calls.append(fields);return {'access_token':'new','refresh_token':'rotated','expires_in':3600,'obtained_at':time.time()}
    monkeypatch.setattr(store,'token_exchange',exchange)
    assert store.token('main')=='new' and store.token('main')=='new' and len(calls)==1
    assert stat.S_IMODE(store.account_path('main').stat().st_mode)==0o600
    with pytest.raises(AppError): store.oauth_finish('bad','code')

def test_csrf_and_host_limits(client):
    assert client.post('/api/defaults',json={'visibility':'public'}).status_code==403
    assert client.get('/',headers={'host':'untrusted.example'}).status_code==400

def test_standalone_runs_without_source_package(tmp_path):
    root=Path(__file__).resolve().parents[1]
    portable=tmp_path/'portable';portable.mkdir();shutil.copy(root/'sc.py',portable/'sc.py')
    command=[sys.executable,'-I',str(portable/'sc.py')]
    env={**os.environ,'SCM_DATA_DIR':str(portable/'state')}
    result=subprocess.run(command+['--help'],cwd=portable,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'tape' in result.stdout
    audio=portable/'01.wav';audio.write_bytes(b'RIFF-mock')
    result=subprocess.run(command+['--demo','upload',str(audio)],cwd=portable,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'Upload complete.' in result.stdout
    result=subprocess.run(command+['--demo','tape','Portable tape',str(audio)],cwd=portable,env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert 'Tape playlist created.' in result.stdout

def test_standalone_embeds_web_assets(tmp_path):
    import importlib.util
    root=Path(__file__).resolve().parents[1]
    isolated=tmp_path/'sc.py';shutil.copy(root/'sc.py',isolated)
    spec=importlib.util.spec_from_file_location('portable_sc',isolated);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with TestClient(module.create_app(module.Store(tmp_path/'data',demo=True),run_worker=False),base_url='http://localhost') as client:
        assert 'Upload desk' in client.get('/').text
        assert 'drawArt' in client.get('/static/app.js').text
        assert client.get('/static/style.css').status_code==200


def test_extreme_panorama_renders_bounded(tmp_path):
    from PIL import Image
    import io
    from sc_manager.core import Store
    store=Store(root=tmp_path, demo=True)
    raw=io.BytesIO()
    Image.new('RGB',(4000,1),'red').save(raw,format='PNG')
    raw.seek(0)
    asset=store.save_art(raw)
    result=store.render_art({'source':'file','asset':asset,'zoom':4})
    with Image.open(io.BytesIO(result)) as image:
        assert image.size==(3000,3000)
        assert image.getpixel((1500,1500))[0]>240


def test_no_art_omits_track_and_playlist_multipart(tmp_path,monkeypatch):
    store=Store(tmp_path/'real');store.save_account('main',{'username':'Mock'})
    calls=[]
    def request(account,method,path,**kwargs):
        calls.append(path)
        if path=='/tracks':
            assert 'track[artwork_data]' not in kwargs['files']
            return {'id':len(calls),'urn':f'soundcloud:tracks:{len(calls)}'}
        assert path=='/playlists' and not kwargs.get('files')
        return {'id':99,'title':'No art tape'}
    monkeypatch.setattr(store,'request',request)
    store.save_defaults({'art':{'source':'none'},'account':'main'})
    result=store.submit('main',[{'asset':stage(store),'title':'One'},{'asset':stage(store),'title':'Two'}],'No art tape',request_id='none-art-request-1234')
    assert store.render_art({'source':'none'}) is None
    assert not list((store.root/'uploads').glob('*.jpg'))
    for _ in range(3): store.work_once()
    assert calls==['/tracks','/tracks','/playlists']
    assert store.submission_status('none-art-request-1234')=={'state':'succeeded','completed':2,'total':2,'playlist':True,'error':None}

def test_account_label_and_default_preserve_tokens(store,client):
    store.save_account('main',{'access_token':'mock-secret','refresh_token':'mock-refresh','username':'Mock','user_id':7})
    assert client.post('/api/accounts/main/label',headers=HEADERS,json={'label':'Personal'}).status_code==200
    assert store.account('main')['access_token']=='mock-secret'
    assert client.post('/api/defaults',headers=HEADERS,json={'account':'main','art':{'source':'none'}}).status_code==200
    public=client.get('/api/state')
    assert 'mock-secret' not in public.text and 'mock-refresh' not in public.text
    assert public.json()['accounts'][2]['label']=='Personal'
    assert client.post('/api/accounts/main/disconnect',headers=HEADERS).status_code==200
    assert store.defaults()['account']==''

def test_connection_settings_are_private_and_link_uses_pkce(tmp_path,monkeypatch):
    store=Store(tmp_path/'real')
    for key in ('SOUNDCLOUD_CLIENT_ID','SOUNDCLOUD_CLIENT_SECRET','SCM_REDIRECT_URI'): monkeypatch.delenv(key,raising=False)
    with TestClient(create_app(store,run_worker=False),base_url='http://localhost') as client:
        settings={'client_id':'test-client','client_secret':'test-secret','redirect_uri':'http://127.0.0.1:8085/auth/callback'}
        assert client.post('/api/connection',headers=HEADERS,json=settings).status_code==200
        assert stat.S_IMODE((store.root/'app-settings.json').stat().st_mode)==0o600
        public=client.get('/api/state')
        assert public.json()['connection']['configured'] is True and 'test-secret' not in public.text
        link=client.post('/api/accounts/connect',headers=HEADERS,json={'name':'new'}).json()['url']
        from urllib.parse import parse_qs,urlparse
        query=parse_qs(urlparse(link).query)
        assert query['code_challenge_method']==['S256'] and 'client_secret' not in query
        monkeypatch.setattr(store,'token_exchange',lambda data:{'access_token':'test-access','refresh_token':'test-refresh','expires_in':3600,'obtained_at':time.time()})
        monkeypatch.setattr(httpx,'get',lambda *a,**kw:httpx.Response(200,json={'id':42,'username':'Linked account'}))
        assert client.get('/auth/callback',params={'state':query['state'][0],'code':'code'},follow_redirects=False).status_code==303
        assert store.account('new')['user_id']==42
        with pytest.raises(AppError): store.oauth_finish(query['state'][0],'code')
        assert 'test-access' not in client.get('/api/state').text

def test_failed_reconnect_keeps_existing_account(tmp_path,monkeypatch):
    store=Store(tmp_path/'real')
    monkeypatch.setattr(store,'credentials',lambda:{'client_id':'test','client_secret':'test'})
    store.save_account('main',{'access_token':'keep','user_id':1,'username':'Original'})
    from urllib.parse import urlparse,parse_qs
    state=parse_qs(urlparse(store.oauth_start('main')).query)['state'][0]
    monkeypatch.setattr(store,'token_exchange',lambda data:{'access_token':'different'})
    monkeypatch.setattr(httpx,'get',lambda *a,**kw:httpx.Response(200,json={'id':2,'username':'Other'}))
    with pytest.raises(AppError): store.oauth_finish(state,'code')
    assert store.account('main')['access_token']=='keep'

def test_disconnect_blocks_pending_tape(store):
    store.submit('main',[{'asset':stage(store),'title':'One'}],'Pending')
    with pytest.raises(AppError): store.disconnect('main')
    assert store.account_path('main').exists()

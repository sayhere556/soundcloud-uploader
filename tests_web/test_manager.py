import io
import json
import os
import stat
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sc_manager.core import Store, AppError
from sc_manager.web import create_app
from sc_manager.cli import main

@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / 'demo', demo=True)

@pytest.fixture
def client(store):
    with TestClient(create_app(store, run_worker=False), base_url='http://localhost') as client:
        yield client

HEADERS = {'X-SCM-Request': '1'}

def test_dashboard_and_no_secret_fields(client):
    assert client.get('/').status_code == 200
    assert 'SC Manager' in client.get('/').text
    data = client.get('/api/state').json()
    assert len(data['accounts']) == 3
    assert 'access_token' not in json.dumps(data)
    assert 'client_secret' not in json.dumps(data)

def test_origin_barrier_and_host_check(client):
    assert client.post('/api/jobs/x/cancel').status_code == 403
    assert client.get('/', headers={'host': 'attacker.example'}).status_code == 400

def test_upload_queue_worker_and_edit(client, store):
    response = client.post('/api/uploads', headers=HEADERS, data={'account':'main','title':'Night drive'}, files={'audio':('mix.wav',b'RIFF-test-wave','audio/wav')})
    assert response.status_code == 200
    job_id = response.json()['id']
    assert store.jobs()[0]['state'] == 'queued'
    assert Store(store.root, demo=True).jobs()[0]['id'] == job_id
    assert store.work_once()
    job = store.jobs()[0]
    assert job['state'] == 'succeeded'
    assert list((store.root / 'uploads').iterdir()) == []
    tracks = client.get('/api/tracks/main').json()['tracks']
    assert tracks[0]['sharing'] == 'private'
    updated = client.patch('/api/tracks/main/'+job_id, headers=HEADERS, json={'title':'Revised','sharing':'public'})
    assert updated.status_code == 200
    assert updated.json()['title'] == 'Revised'

def test_schedule_and_cancel(client, store):
    path = store.stage(io.BytesIO(b'wave'), 'a.wav')
    job = store.enqueue('main', path, 'Future', scheduled=time.time()+86400)
    assert not store.work_once()
    assert client.post('/api/jobs/'+job+'/cancel',headers=HEADERS).status_code == 200
    assert store.jobs()[0]['state'] == 'cancelled'
    assert not store.work_once()

def test_invalid_files_and_account_path(client, store):
    response = client.post('/api/uploads',headers=HEADERS,data={'account':'main'},files={'audio':('x.exe',b'bad')})
    assert response.status_code == 400
    assert list((store.root / 'uploads').iterdir()) == []
    with pytest.raises(AppError): store.account_path('../escape')
    with pytest.raises(AppError): store.stage(io.BytesIO(b''),'empty.wav')

def test_interrupted_job_not_retried(store):
    path = store.stage(io.BytesIO(b'wave'), 'a.wav')
    job = store.enqueue('main', path, 'Interrupted')
    with store.db() as db: db.execute("UPDATE jobs SET state='uploading' WHERE id=?",(job,))
    assert not store.work_once()
    assert store.jobs()[0]['state'] == 'needs_review'

def test_cli_and_web_share_queue(store, tmp_path, capsys):
    audio = tmp_path / 'my track.wav'; audio.write_bytes(b'wave')
    assert main(['--demo','--data-dir',str(store.root),'upload',str(audio)]) == 0
    assert store.jobs()[0]['title'] == 'my track'
    assert main(['--demo','--data-dir',str(store.root),'queue']) == 0
    assert 'my track' in capsys.readouterr().out
    assert main(['--demo','--data-dir',str(store.root),'upload','/not-a-real-file.wav']) == 1

def test_token_refresh_is_saved_and_not_exposed(tmp_path, monkeypatch):
    store = Store(tmp_path / 'real')
    store.save_account('main',{'access_token':'expired-secret','refresh_token':'old-refresh','obtained_at':0,'expires_in':1})
    calls=[]
    def exchange(fields):
        calls.append(fields)
        return {'access_token':'new-secret','refresh_token':'new-refresh','obtained_at':time.time(),'expires_in':3600}
    monkeypatch.setattr(store,'token_exchange',exchange)
    assert store.token('main') == 'new-secret'
    assert store.token('main') == 'new-secret'
    assert len(calls) == 1
    assert store.account('main')['refresh_token'] == 'new-refresh'
    assert stat.S_IMODE(store.account_path('main').stat().st_mode) == 0o600
    assert 'secret' not in json.dumps(store.accounts())

def test_oauth_state_rejected_and_one_time(tmp_path, monkeypatch):
    store = Store(tmp_path / 'real')
    monkeypatch.setenv('SOUNDCLOUD_CLIENT_ID','test-client')
    monkeypatch.setenv('SOUNDCLOUD_CLIENT_SECRET','test-secret')
    from urllib.parse import urlparse, parse_qs
    query = parse_qs(urlparse(store.oauth_start('main')).query)
    assert query['code_challenge_method'] == ['S256']
    with pytest.raises(AppError): store.oauth_finish('wrong','code')
    monkeypatch.setattr(store,'token_exchange',lambda fields:{'access_token':'fake','refresh_token':'fake-r','obtained_at':time.time(),'expires_in':3600})
    monkeypatch.setattr(store,'request',lambda *a,**kw:{'username':'Test Artist'})
    assert store.oauth_finish(query['state'][0],'code') == 'main'
    with pytest.raises(AppError): store.oauth_finish(query['state'][0],'code')

def test_live_multipart_stream_and_header(tmp_path, monkeypatch):
    import httpx
    store = Store(tmp_path / 'real')
    store.save_account('main', {'access_token':'test-only','obtained_at':time.time(),'expires_in':3600})
    requests=[]
    def handler(request):
        requests.append(request)
        assert request.headers['authorization'] == 'OAuth test-only'
        body=request.read()
        assert b'track[asset_data]' in body and b'track[sharing]' in body and b'private' in body
        return httpx.Response(201,json={'id':123,'title':'Mix','sharing':'private','secret_token':'must-not-escape'})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    path=store.stage(io.BytesIO(b'RIFF example'),'mix.wav')
    store.enqueue('main',path,'Mix')
    store.work_once()
    assert store.jobs()[0]['state'] == 'succeeded'
    assert 'must-not-escape' not in json.dumps(store.jobs())
    assert len(requests)==1

def test_disconnect_preserves_pending_work(store):
    path=store.stage(io.BytesIO(b'wave'),'mix.wav')
    store.enqueue('main',path,'Mix')
    with pytest.raises(AppError): store.disconnect('main')
    assert store.account_path('main').exists()

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from .core import Store, AppError, AUDIO, validate_art

def login_local(store, account, no_browser=False):
    url=store.oauth_start(account)
    expected=parse_qs(urlparse(url).query)['state'][0]
    callback=parse_qs(urlparse(url).query)['redirect_uri'][0]
    parsed=urlparse(callback)
    port=parsed.port or (8085 if parsed.scheme=='https' else 80)
    if parsed.hostname not in ('127.0.0.1','localhost','::1'): port=8085
    done={'ok':False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            query=parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path!=parsed.path or query.get('state',[''])[0]!=expected:
                self.send_error(400,'Invalid callback'); return
            try:
                store.oauth_finish(expected,query.get('code',[''])[0]); done['ok']=True
                body=b'Connected. You can close this tab and return to the terminal.'
                self.send_response(200)
            except AppError:
                body=b'Connection failed. Return to the terminal and start login again.'
                self.send_response(400); done['error']=True
            self.send_header('Content-Type','text/plain'); self.send_header('Referrer-Policy','no-referrer'); self.end_headers(); self.wfile.write(body)
    try: server=HTTPServer(('127.0.0.1',port),Handler)
    except OSError: raise AppError('The callback port is in use. Connect from the web interface, or stop it before CLI login.') from None
    server.timeout=1
    print(f'Callback listening on http://127.0.0.1:{port}'+parsed.path)
    print('Authorize this account in your browser:\n'+url,flush=True)
    if not no_browser: webbrowser.open(url)
    deadline=time.time()+600
    try:
        while not done['ok'] and not done.get('error') and time.time()<deadline: server.handle_request()
    finally: server.server_close()
    if not done['ok']: raise AppError('Login did not complete. Run login again.')
    print('Connected '+account+'.')

def art_flags(parser):
    parser.add_argument('--art','--cover',dest='art',help='none, hex color, or local image')
    parser.add_argument('--fit',choices=['crop','fill'])
    parser.add_argument('--fill',help='Six-digit hex color behind an image')
    parser.add_argument('--zoom',type=float)
    parser.add_argument('--x',type=float,help='Horizontal crop position, 0–1')
    parser.add_argument('--y',type=float,help='Vertical crop position, 0–1')

def art_from_args(store,args):
    art=dict(store.defaults()['art'])
    if args.art:
        if args.art.lower()=='none': art.update(source='none',asset='',url='')
        elif args.art.startswith('#'): art.update(source='solid',color=args.art,asset='',url='')
        elif args.art.startswith(('http://','https://')): raise AppError('Choose a local image file, a hex color, or none.')
        else:
            with Path(args.art).expanduser().open('rb') as source: asset=store.save_art(source)
            art.update(source='file',asset=asset,url='')
    for field in ('fit','fill','zoom','x','y'):
        if getattr(args,field,None) is not None: art[field]=getattr(args,field)
    return validate_art(art)

def main(argv=None):
    parser=argparse.ArgumentParser(prog='sc.py',description='Standalone SoundCloud uploader. Singles, tapes and an optional web desk.')
    parser.add_argument('--data-dir',help='Private state location (default .sc-manager)')
    parser.add_argument('-a','--account',default=None)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('accounts',help='List connected accounts')
    account_import=sub.add_parser('import-account',help='Import a SoundCloud token JSON file');account_import.add_argument('path')
    login=sub.add_parser('login',help='Standalone OAuth with a temporary callback listener'); login.add_argument('--no-browser',action='store_true')
    defaults=sub.add_parser('defaults',help='Show or save visibility and artwork defaults'); defaults.add_argument('--visibility',choices=['private','public']); art_flags(defaults)
    for command in ('upload','tape'):
        upload=sub.add_parser(command,help='Upload audio files'+(' and create one ordered playlist' if command=='tape' else ''))
        if command=='tape': upload.add_argument('tape_title')
        else: upload.add_argument('--tape',dest='tape_title',default='')
        upload.add_argument('paths',nargs='+'); upload.add_argument('--title')
        visibility=upload.add_mutually_exclusive_group(); visibility.add_argument('--public',action='store_true'); visibility.add_argument('--private',action='store_true')
        upload.add_argument('--queue',action='store_true',help='Only enqueue; otherwise upload now without requiring a web server')
        art_flags(upload)
    sub.add_parser('queue',help='Show upload and tape status')
    cancel=sub.add_parser('cancel',help='Cancel a waiting single or the remaining tracks of its tape'); cancel.add_argument('id')
    worker=sub.add_parser('worker',help='Process saved jobs'); worker.add_argument('--once',action='store_true')
    web=sub.add_parser('web',help='Launch the upload desk'); web.add_argument('--host',default='127.0.0.1'); web.add_argument('--port',type=int,default=8085)
    art=sub.add_parser('art',help='Render a square cover locally'); art.add_argument('--output',required=True); art_flags(art)
    disconnect=sub.add_parser('disconnect'); disconnect.add_argument('--yes',action='store_true')
    args=parser.parse_args(argv)
    try:
        store=Store(args.data_dir)
        args.account=args.account or store.defaults().get('account') or 'main'
        if args.command=='web':
            import uvicorn
            from .web import create_app
            print(f'Upload desk: http://{args.host}:{args.port}',flush=True)
            uvicorn.run(create_app(store),host=args.host,port=args.port,access_log=False,log_level='warning')
        elif args.command=='accounts': print(json.dumps(store.accounts(),indent=2))
        elif args.command=='import-account':
            with Path(args.path).expanduser().open('rb') as source: result=store.import_account(args.account,source)
            print('Imported '+result['username']+' as '+result['name']+'.')
        elif args.command=='login':
            login_local(store,args.account,args.no_browser)
        elif args.command=='defaults':
            art=art_from_args(store,args)
            changed=args.visibility or args.art or any(getattr(args,k) is not None for k in ('fit','fill','zoom','x','y'))
            result=store.save_defaults({'visibility':args.visibility or store.defaults()['visibility'],'art':art}) if changed else store.defaults()
            print(json.dumps(result,indent=2))
        elif args.command=='art':
            destination=Path(args.output).expanduser()
            if destination.exists(): raise AppError('Output already exists. Choose a new filename.')
            rendered=store.render_art(art_from_args(store,args))
            if rendered is None: raise AppError('No artwork is selected. Choose --art before exporting.')
            destination.write_bytes(rendered); print('Wrote '+str(destination))
        elif args.command in ('upload','tape'):
            store.account(args.account); sources=[]
            for raw in args.paths:
                path=Path(raw).expanduser()
                sources.extend(sorted((p for p in path.iterdir() if p.is_file() and p.suffix.lower() in AUDIO),key=lambda p:p.name.casefold()) if path.is_dir() else [path])
            if not sources or len(sources)>100 or any(not p.is_file() or p.suffix.lower() not in AUDIO for p in sources): raise AppError('Choose 1–100 supported audio files.')
            if args.title and len(sources)!=1: raise AppError('--title requires one file.')
            art=art_from_args(store,args); items=[]
            for source in sources:
                with source.open('rb') as stream: asset=store.stage_audio(stream,source.name)
                items.append({'asset':asset,'title':args.title or source.stem})
            sharing='public' if args.public else ('private' if args.private else None)
            result=store.submit(args.account,items,args.tape_title,sharing,art)
            print('Queued '+str(len(items))+' track(s)'+(' as tape '+args.tape_title if args.tape_title else '')+'.',flush=True)
            if not args.queue:
                last=''
                while True:
                    store.work_once()
                    jobs=[job for job in store.jobs() if job['id'] in result['jobs']]
                    tape=next((t for t in store.tapes() if t['id']==result['tape_id']),None)
                    review=next((j for j in jobs if j['state'] in ('needs_review','cancelled')),None)
                    if review or (tape and tape['state'] in ('needs_review','cancelled')): raise AppError((review or tape).get('error') or 'Upload cancelled.')
                    done=sum(j['state']=='succeeded' for j in jobs)
                    message=f'{done}/{len(items)} tracks uploaded'
                    if message!=last: print(message,flush=True); last=message
                    if done==len(items) and (not tape or tape['state']=='succeeded'):
                        print('Tape playlist created.' if tape else 'Upload complete.'); break
                    time.sleep(.3)
        elif args.command=='queue': print(json.dumps({'jobs':store.jobs(),'tapes':store.tapes()},indent=2))
        elif args.command=='cancel': store.cancel(args.id); print('Cancelled waiting uploads.')
        elif args.command=='worker':
            while True:
                store.work_once()
                if args.once: break
                time.sleep(.7)
        elif args.command=='disconnect':
            if not args.yes: raise AppError('Use --yes to disconnect this application.')
            store.disconnect(args.account); print('Disconnected.')
    except (AppError,ValueError,OSError) as exc:
        print('Error: '+(str(exc) if isinstance(exc,(AppError,ValueError)) else 'Could not read or write the requested file.'),file=sys.stderr); return 1
    except KeyboardInterrupt:
        print('Stopped. Check the queue before retrying an interrupted upload.',file=sys.stderr); return 130
    return 0

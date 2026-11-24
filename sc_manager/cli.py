"""CLI entry point; the same Store powers the web interface."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import webbrowser
from .core import Store, AppError, AUDIO

def main(argv=None):
    parser = argparse.ArgumentParser(prog='python manager.py', description='SoundCloud accounts, uploads and a web interface.')
    parser.add_argument('--demo', action='store_true', help='Use isolated fake accounts; never contact SoundCloud')
    parser.add_argument('--data-dir', help='Private state directory (default: .sc-manager)')
    parser.add_argument('-a', '--account', default='main')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('accounts', help='List connected account names; never prints tokens')
    sub.add_parser('login', help='Start OAuth; keep the web server running for the callback')
    listing = sub.add_parser('list', help='List account tracks'); listing.add_argument('--limit', type=int, default=50)
    edit = sub.add_parser('edit', help='Change track metadata'); edit.add_argument('id')
    for field in ('title','description','genre'):
        edit.add_argument('--' + field)
    edit.add_argument('--sharing', choices=['private','public'])
    upload = sub.add_parser('upload', help='Queue one file or a directory; run web/worker to process')
    upload.add_argument('path'); upload.add_argument('--title'); upload.add_argument('--cover')
    upload.add_argument('--description', default=''); upload.add_argument('--genre', default=''); upload.add_argument('--tags', default='')
    visibility = upload.add_mutually_exclusive_group()
    visibility.add_argument('--public', action='store_true'); visibility.add_argument('--private', action='store_true')
    upload.add_argument('--at', help='ISO timestamp with timezone; e.g. 2026-12-01T19:00:00-06:00')
    sub.add_parser('queue', help='Show persisted upload jobs')
    cancel = sub.add_parser('cancel', help='Cancel a waiting upload'); cancel.add_argument('id')
    worker = sub.add_parser('worker', help='Process queued uploads'); worker.add_argument('--once', action='store_true')
    web = sub.add_parser('web', help='Run the dashboard and queue worker')
    web.add_argument('--host', default='127.0.0.1'); web.add_argument('--port', type=int, default=8085)
    disconnect = sub.add_parser('disconnect', help='Revoke this app’s account connection'); disconnect.add_argument('--yes', action='store_true')
    args = parser.parse_args(argv)
    try:
        store = Store(root=args.data_dir, demo=args.demo)
        if args.command == 'web':
            import uvicorn
            from .web import create_app
            print(f'SC Manager: http://{args.host}:{args.port}' + (' (DEMO — no SoundCloud requests)' if args.demo else ''), flush=True)
            uvicorn.run(create_app(store), host=args.host, port=args.port, access_log=False, log_level='warning')
        elif args.command == 'accounts':
            print(json.dumps(store.accounts(), indent=2))
        elif args.command == 'login':
            if args.demo:
                raise AppError('Demo mode already has sample accounts.')
            url = store.oauth_start(args.account)
            print('Open this login URL. Keep the dashboard running for the callback:\n' + url)
            webbrowser.open(url)
        elif args.command == 'list':
            print(json.dumps(store.tracks(args.account, args.limit), indent=2))
        elif args.command == 'edit':
            fields = {key: getattr(args, key) for key in ('title','description','genre','sharing') if getattr(args,key) is not None}
            print(json.dumps(store.edit_track(args.account, args.id, fields), indent=2))
        elif args.command == 'upload':
            store.account(args.account)
            source = Path(args.path).expanduser()
            sources = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in AUDIO) if source.is_dir() else [source]
            if not sources or any(not p.is_file() for p in sources):
                raise AppError('No supported audio files found.')
            if args.title and len(sources) != 1:
                raise AppError('--title requires a single audio file.')
            when = None
            if args.at:
                date = datetime.fromisoformat(args.at.replace('Z', '+00:00'))
                if date.tzinfo is None:
                    raise AppError('--at must include a timezone.')
                when = date.timestamp()
            for source in sources:
                staged = []
                try:
                    with source.open('rb') as stream:
                        path = store.stage(stream, source.name)
                    staged.append(path)
                    cover = None
                    if args.cover:
                        with Path(args.cover).expanduser().open('rb') as stream:
                            cover = store.stage(stream, args.cover, artwork=True)
                        staged.append(cover)
                    job = store.enqueue(args.account, path, args.title or source.stem, artwork=cover, scheduled=when,
                        description=args.description, genre=args.genre, tag_list=args.tags, sharing='public' if args.public else 'private')
                    print(f'Queued {job}: {args.title or source.stem}')
                except Exception:
                    for path in staged:
                        Path(path).unlink(missing_ok=True)
                    raise
            print('Run python manager.py worker, or keep the web interface running, to upload.')
        elif args.command == 'queue':
            print(json.dumps(store.jobs(), indent=2))
        elif args.command == 'cancel':
            store.cancel(args.id); print('Cancelled.')
        elif args.command == 'worker':
            while True:
                store.work_once()
                if args.once:
                    break
                time.sleep(1)
        elif args.command == 'disconnect':
            if not args.yes:
                raise AppError('Use --yes to disconnect this account from this app.')
            store.disconnect(args.account); print('Disconnected.')
    except (AppError, ValueError, OSError) as exc:
        print('Error: ' + (str(exc) if isinstance(exc, (AppError, ValueError)) else 'Could not read or write the requested file.'), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0

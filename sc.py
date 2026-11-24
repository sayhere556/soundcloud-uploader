#!/usr/bin/env python3

import argparse
import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from soundcloud_mcp.client import SoundCloudClient
from soundcloud_mcp import oauth

ACCOUNTS = Path.home() / ".soundcloud-mcp/accounts"


AUDIO_EXT = {".wav", ".flac", ".mp3", ".aiff", ".aif", ".m4a"}

async def main():
    parser = argparse.ArgumentParser(prog="sc")
    parser.add_argument(
        "--account", "-a",
        choices=["main", "alt", "label"],
        default="main"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login")
    sub.add_parser("accounts")

    sub.add_parser("me")

    tracks = sub.add_parser("list")
    tracks.add_argument("--limit", type=int, default=50)

    upload = sub.add_parser("upload")
    upload.add_argument("path")
    upload.add_argument("--title")
    upload.add_argument("--cover")
    upload.add_argument("--description")
    upload.add_argument("--genre")
    upload.add_argument("--tags")

    visibility = upload.add_mutually_exclusive_group()
    visibility.add_argument("--public", action="store_true")
    visibility.add_argument("--private", action="store_true")

    args = parser.parse_args()
    ACCOUNTS.mkdir(mode=0o700, parents=True, exist_ok=True)
    oauth.TOKEN_FILE = ACCOUNTS / f"{args.account}.json"

    if args.command == "accounts":
        for name in ["main", "alt", "label"]:
            status = "Authenticated" if (ACCOUNTS / f"{name}.json").exists() else "Not configured"
            print(f"{name}: {status}")
        return

    if args.command == "login":
        await asyncio.to_thread(
            oauth.run_local_oauth_login,
            open_browser=False
        )
        print(f"Authenticated account: {args.account}")
        return

    client = SoundCloudClient()

    try:
        if args.command == "me":
            print(json.dumps(await client.get_me(), indent=2))

        elif args.command == "list":
            tracks = await client.list_my_tracks(limit=args.limit)
            for track in tracks:
                print(f"{track.get('id')} | {track.get('title')}")

        elif args.command == "upload":
            path = Path(args.path).expanduser()

            if path.is_dir():
                files = sorted(
                    p for p in path.iterdir()
                    if p.is_file() and p.suffix.lower() in AUDIO_EXT
                )
            elif path.is_file():
                files = [path]
            else:
                parser.error("File or directory not found")

            if not files:
                parser.error("No audio files found")

            if args.title and len(files) > 1:
                parser.error("--title requires a single file")

            if args.cover and not Path(args.cover).expanduser().is_file():
                parser.error("Cover artwork not found")

            for file in files:
                print(f"Uploading: {file.name}", flush=True)

                track = await client.upload_track(
                    file_path=str(file),
                    title=args.title or file.stem,
                    description=args.description,
                    genre=args.genre,
                    tag_list=args.tags,
                    sharing="public" if args.public else "private",
                    artwork_path=args.cover,
                )

                print(f"Uploaded: {track.get('title')}")
                print(track.get("permalink_url", ""))

    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

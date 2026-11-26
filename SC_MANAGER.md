# SoundCloud uploader

A standalone CLI and minimal dark web interface for singles and tapes. A tape uploads tracks in your chosen order, then creates one playlist. There is no track management or upload history screen.

## Run

    python -m venv .venv-web
    .venv-web/bin/pip install -r requirements-web.lock
    .venv-web/bin/python sc.py web

Open http://127.0.0.1:8085. Python 3.12+ is recommended. sc.py embeds the application and web assets: it can be copied and run without the project folders. It requires fastapi, uvicorn, httpx, python-multipart, filelock, pillow and python-dotenv.

## Accounts

Open Accounts, choose an account name, select your token JSON file, then Import account. Accepted fields are access_token, token_type, expires_in, refresh_token, scope and obtained_at. The access token is checked with SoundCloud before saving. Existing account names are never overwritten. Expired or invalid access tokens must be replaced with a fresh JSON file or linked through SoundCloud.

CLI equivalent:

    python sc.py -a main import-account /path/to/tokens.json
    python sc.py accounts

Tokens are stored privately with owner-only permissions and are not returned to the browser. Import leaves the original JSON file unchanged. Automatic refresh requires the SoundCloud app credentials that issued the token.

For OAuth linking, expand Or link with SoundCloud. Configure your app under SoundCloud connection settings or privately set SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET. SCM_REDIRECT_URI must exactly match your registered callback; the local default is http://127.0.0.1:8085/auth/callback. SCM_PUBLIC_URL sets the public origin when using a private forwarded URL. Account controls also allow label changes, reconnection and disconnection.

## Uploads and artwork

Select files, edit titles and order, choose Singles or Tape, then upload. Tape creates one playlist after all tracks succeed. Only the current submission status is shown.

Defaults are dropdown menus for account, visibility and artwork. Artwork options: no artwork, solid color, or an uploaded image. Colors: #000000, #ffffff, #6e5191, then Custom. Images support crop or fit with color fill, zoom and position. Generated covers are 3000 x 3000 JPEG. No artwork omits the cover entirely. Pinterest is not supported.

    python sc.py -a main upload song.wav
    python sc.py -a main tape "My tape" 01.wav 02.wav
    python sc.py --help
    python sc.py upload --help

CLI uploads run without the web server. Saved defaults apply unless overridden. Uploads run immediately unless --queue is selected; use worker to process queued work. Interrupted submissions may require review in SoundCloud before resubmitting to avoid duplicates.

## Docker

    docker compose up --build -d

The container runs sc.py as a non-root user, stores state in /data, and binds port 8085 to localhost. Keep credentials in private environment settings; see .env.example. Host and container state are separate unless explicitly shared. Keep this single-user app private.

## Development

Edit sc_manager sources and regenerate the standalone file:

    python tools/build_standalone.py
    .venv-web/bin/python -m pytest tests_web -q
    node --check sc_manager/static/app.js

Tests use temporary directories and mocked services. Real account linking and uploads require valid SoundCloud credentials. The original src/soundcloud_mcp code is preserved.

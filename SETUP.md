# Setup

## Quick start: Linux, macOS, or a VS Code Codespace

Requires Python 3.12 or newer with pip and venv. Open a terminal in the project folder:

    ./setup.sh --start

Setup creates or reuses .venv-web, installs the pinned dependencies, checks them, then starts the app. It does not overwrite settings or accounts. Stop with Ctrl+C. To install without starting, run ./setup.sh.

Open http://127.0.0.1:8085. In a Codespace, open port 8085 from VS Code's Ports panel and keep its visibility Private. If venv is unavailable, install the venv package for your Python version or use Docker below.

On later runs:

    .venv-web/bin/python sc.py web

## Windows PowerShell

With Python 3.12 or newer installed, run from the project folder:

    py -3 -m venv .venv-web
    .\.venv-web\Scripts\python.exe -m pip install -r requirements-web.lock
    .\.venv-web\Scripts\python.exe sc.py web

No environment activation is required. Open http://127.0.0.1:8085.

## Add an account

Open Accounts, enter a name such as main, select your token JSON file, and choose Import account. It accepts access_token, token_type, expires_in, refresh_token, scope and obtained_at. Use valid, current tokens. Existing account names are not overwritten.

For OAuth linking, expand Or link with SoundCloud and configure your SoundCloud app under Connection settings. Register the exact callback http://127.0.0.1:8085/auth/callback. For a Codespace, use its private forwarded HTTPS origin followed by /auth/callback and register that exact URL with SoundCloud.

Automatic token refresh needs the credentials for the SoundCloud app that issued the token. You can enter these under Connection settings or supply SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET privately. The optional .env.example lists environment settings; do not replace an existing .env. Setup does not create or modify it.

## Upload from the command line

Run from this project folder so CLI and web share the same settings:

    .venv-web/bin/python sc.py -a main import-account /path/to/tokens.json
    .venv-web/bin/python sc.py -a main upload /path/to/song.wav
    .venv-web/bin/python sc.py -a main tape "Tape title" 01.wav 02.wav
    .venv-web/bin/python sc.py --help

A tape uploads tracks in the specified order, then creates one playlist. Use --private or --public to override saved visibility; use --art none, --art '#6e5191', or a local image path to override artwork. Default artwork, crop and fill settings can be saved in the UI. Generated covers are 3000 x 3000 pixels.

## Docker

Install Docker with Compose support, then run:

    docker compose up --build -d

Open http://127.0.0.1:8085. No local Python setup is needed. Account linking and JSON import work through the UI. For environment-based settings, create a private .env from .env.example only if one does not already exist.

    docker compose stop
    docker compose start

Docker stores settings and accounts in its named volume. Local Python stores them in .sc-manager. These stores are separate. Keep the volume and .sc-manager to preserve accounts; removing volumes deletes container data. The app is intended for private, single-user access.

## Updates and development

After changing dependencies, rerun ./setup.sh. After editing sc_manager source or web assets, rebuild the standalone file:

    python3 tools/build_standalone.py
    .venv-web/bin/python -m pytest tests_web -q -p no:cacheprovider

sc.py contains the complete app and web assets. It can be copied elsewhere without the source folders, but still needs the packages listed in requirements-web.lock. Keep that file and setup.sh with it for the same setup procedure.

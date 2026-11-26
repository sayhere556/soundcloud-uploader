# SoundCloud upload desk

Standalone sc.py CLI and minimal web UI for singles and tapes. A tape uploads tracks in your chosen order, then creates one playlist. No track management screen.

## Run

    python -m venv .venv-web
    .venv-web/bin/pip install -r requirements-web.lock
    .venv-web/bin/python sc.py --demo web

Open http://127.0.0.1:8085. Demo mode uses fake accounts and never uploads to SoundCloud. Omit --demo for real use.

sc.py embeds all Python application code and web assets; copy it anywhere without the project folders. It still requires third-party packages: fastapi, uvicorn, httpx, python-multipart, filelock and pillow. Python 3.12+ is recommended. CLI uploads run without a web server.

## Accounts

Privately set SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET in your environment. Register the exact callback in SoundCloud: http://127.0.0.1:8085/auth/callback by default. SCM_REDIRECT_URI overrides it; SCM_PUBLIC_URL sets the web origin. Outside Docker Compose, .env is not loaded automatically.

    python sc.py -a main login
    python sc.py accounts

Or run python sc.py web and use Accounts. CLI login opens a temporary callback listener. If that port is already used by the web interface, connect there. In a Codespace, keep forwarding private and forward 8085 to the same local port for the default callback.

Tokens live in .sc-manager, with separate .sc-manager-demo state. Use --data-dir or SCM_DATA_DIR to override. Token files have restricted permissions, not encryption. Existing legacy CLI token files are not imported or overwritten.

## Defaults and artwork

    python sc.py defaults --visibility private --art '#111111'
    python sc.py defaults --art cover.png --fit fill --fill '#ffffff'
    python sc.py defaults --art 'https://www.pinterest.com/pin/YOUR_PIN_ID/'
    python sc.py defaults
    python sc.py art --output preview.jpg

Web and CLI share defaults. Choose Color, Image or Pinterest, adjust the cover, then Save as defaults. Public Pinterest pins, pin.it links and direct i.pinimg.com images are supported. Some pins block loading; use their direct image URL or upload a saved image. There is no Pinterest search or private-board access. Resolved artwork is cached locally for reuse.

Crop fills the square; Fit + fill keeps the image inside a colored square. Zoom and position sliders or dragging adjust the preview. Final artwork is a 1400 × 1400 JPEG with orientation corrected and transparency composited over the fill color. Source files are unchanged.

## Upload

    python sc.py -a main upload song.wav
    python sc.py -a main upload ./wavs --public --art '#eeeeee'
    python sc.py -a main tape 'My tape' intro.wav song.wav outro.wav
    python sc.py -a main upload ./wavs --tape 'My tape'

Explicit files preserve argument order; folders sort by filename, case-insensitively. In the web interface, choose Tape, name it, and use the arrows to reorder tracks. Edit titles before submitting. Visibility and artwork apply to every track and the resulting playlist. The playlist is created only after all tracks succeed.

Uploads run to completion by default. Add --queue to stage for a worker.

    python sc.py queue
    python sc.py worker
    python sc.py cancel JOB_ID

The web server runs a worker automatically. Cancelling a waiting tape item stops the remaining tape; it does not delete completed uploads. Interrupted or uncertain requests need review, with no automatic retry that might duplicate a successful remote upload. Check SoundCloud before resubmitting.

## Docker

    docker compose up --build -d
    docker compose exec sc-manager python sc.py accounts
    docker compose exec sc-manager python sc.py queue

The container uses only sc.py, runs as a non-root user, stores state in a dedicated /data volume, and binds 8085 to localhost. Compose reads settings from a private .env or the process environment; see .env.example. Keep the app private; multi-user login and public hosting are not configured. Browser uploads can stage local files directly. For container CLI uploads, copy the intended files into the container and use their container paths. Host and Docker state are separate unless explicitly shared.

## Development

Edit sc_manager sources, then regenerate the standalone file:

    python tools/build_standalone.py
    .venv-web/bin/python -m pytest tests_web -q
    node --check sc_manager/static/app.js
    docker compose config --quiet

Tests use temporary directories and mocked services, including copying sc.py alone into a fresh directory. Live uploads still require your own SoundCloud app and account.

Audio: WAV/WAVE, FLAC, MP3, AIFF/AIF, M4A and OGG, up to 4 GB per file. Artwork: 20 MB and 40 megapixels maximum. SoundCloud enforces its own format, duration and quota limits. Recent activity shows up to 200 jobs and 100 tapes. Successful uploads remove staged audio copies; originals remain unchanged.

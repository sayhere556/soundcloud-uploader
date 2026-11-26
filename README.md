# soundcloud uploader

Standalone sc.py CLI and minimal dark web interface for singles and ordered tapes. Import account token JSON or link SoundCloud, save upload defaults, and prepare optional 3000 x 3000 artwork.

## Start

On Linux, macOS, or a Codespace with Python 3.12+:

    ./setup.sh --start

Open http://127.0.0.1:8085, then use Accounts to connect. For Docker, Windows, account setup and CLI examples, see [SETUP.md](SETUP.md). More usage details are in [SC_MANAGER.md](SC_MANAGER.md).

## Project files

- sc.py: standalone CLI and web app.
- setup.sh: dependency setup and optional startup.
- sc_manager/: editable application source and web assets.
- tools/: standalone build script.
- tests_web/: automated tests.
- .env.example: optional environment settings for local and Docker use.

Account and upload state stays in .sc-manager or the configured data directory.

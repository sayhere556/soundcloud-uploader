#!/usr/bin/env bash
# Run from any directory. Installs only into this project's virtual environment.
set -euo pipefail
sc_setup_start=0
if [[ $# -gt 1 ]]; then
    printf '%s
' 'Usage: ./setup.sh [--start|--help]' >&2
    exit 2
fi
if [[ $# -eq 1 ]]; then
    case "$1" in
        --start) sc_setup_start=1 ;;
        --help|-h)
            printf '%s
' 'Usage: ./setup.sh [--start]' 'Install dependencies; optionally start the web app on http://127.0.0.1:8085.' 'Requires Python 3.12+ with venv and pip. Existing settings and accounts are preserved.'
            exit 0 ;;
        *) printf '%s
' 'Unknown option. Use ./setup.sh --help.' >&2; exit 2 ;;
    esac
fi
sc_setup_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$sc_setup_dir"
if [[ ! -f sc.py || ! -f requirements-web.lock ]]; then
    printf '%s
' 'Keep setup.sh beside sc.py and requirements-web.lock.' >&2
    exit 1
fi
sc_setup_python=.venv-web/bin/python
if [[ ! -x "$sc_setup_python" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s
' 'Install Python 3.12 or newer, or use Docker. See SETUP.md.' >&2
        exit 1
    fi
    python3 -c 'import sys; sys.exit("Python 3.12 or newer is required.") if sys.version_info < (3,12) else None'
    if ! python3 -m venv .venv-web; then
        printf '%s
' 'Could not create the environment. Install Python venv support, then rerun setup.' >&2
        exit 1
    fi
fi
"$sc_setup_python" -c 'import sys; sys.exit("The existing .venv-web needs Python 3.12 or newer.") if sys.version_info < (3,12) else None'
"$sc_setup_python" -m pip install --disable-pip-version-check --no-input -r requirements-web.lock
"$sc_setup_python" -m pip check
"$sc_setup_python" sc.py --help >/dev/null
printf '
%s
' 'Setup complete.' 'Start web: .venv-web/bin/python sc.py web' 'CLI help: .venv-web/bin/python sc.py --help' 'Open http://127.0.0.1:8085 and use Accounts to import token JSON or link SoundCloud.'
if [[ "$sc_setup_start" -eq 1 ]]; then
    exec "$sc_setup_python" sc.py web
fi

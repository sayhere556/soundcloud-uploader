"""CLI to complete SoundCloud OAuth login."""

import argparse
import json
import sys

from dotenv import load_dotenv

from .config import REDIRECT_URI
from .oauth import OAuthError, build_authorize_url, run_local_oauth_login, _pkce_pair
import secrets


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Authenticate with SoundCloud for soundcloud-mcp")
    parser.add_argument("--no-browser", action="store_true", help="Print URL only, don't open browser")
    parser.add_argument("--print-url", action="store_true", help="Print authorize URL and exit")
    args = parser.parse_args()

    if args.print_url:
        state = secrets.token_urlsafe(16)
        _, challenge = _pkce_pair()
        print(build_authorize_url(state=state, code_challenge=challenge))
        print(f"\nRedirect URI configured: {REDIRECT_URI}")
        return

    try:
        tokens = run_local_oauth_login(open_browser=not args.no_browser)
        from .config import TOKEN_FILE
        print("Authenticated successfully.")
        print(f"Tokens saved to: {TOKEN_FILE}")
        print(json.dumps({k: tokens[k] for k in ("token_type", "expires_in", "scope") if k in tokens}, indent=2))
    except OAuthError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

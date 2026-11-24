"""OAuth 2.1 + PKCE helpers and token storage."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx

from .config import AUTH_BASE, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI, TOKEN_FILE


class OAuthError(RuntimeError):
    pass


def _pkce_pair() -> tuple[str, str]:
    """Match SoundCloud's official sc-api-auth.mjs PKCE generation."""
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _load_tokens() -> dict[str, Any] | None:
    if not TOKEN_FILE.exists():
        return None
    return json.loads(TOKEN_FILE.read_text())


def _save_tokens(data: dict[str, Any]) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, indent=2))
    TOKEN_FILE.chmod(0o600)


def build_authorize_url(*, state: str, code_challenge: str) -> str:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{AUTH_BASE}/authorize?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str, code_verifier: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{AUTH_BASE}/oauth/token",
            headers={
                "accept": "application/json; charset=utf-8",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": code_verifier,
                "code": code,
            },
        )
        if not response.is_success:
            raise OAuthError(f"Token exchange failed ({response.status_code}): {response.text[:300]}")
        payload = response.json()
        payload["obtained_at"] = int(time.time())
        _save_tokens(payload)
        return payload


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{AUTH_BASE}/oauth/token",
            headers={
                "accept": "application/json; charset=utf-8",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
            },
        )
        if not response.is_success:
            raise OAuthError(f"Token refresh failed ({response.status_code}): {response.text[:300]}")
        payload = response.json()
        payload["obtained_at"] = int(time.time())
        _save_tokens(payload)
        return payload


async def get_valid_access_token() -> str:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise OAuthError(
            "Missing SOUNDCLOUD_CLIENT_ID or SOUNDCLOUD_CLIENT_SECRET. "
            "Copy .env.example to .env and add credentials from https://soundcloud.com/you/apps"
        )

    tokens = _load_tokens()
    if not tokens:
        raise OAuthError(
            "Not authenticated. Run: soundcloud-mcp-auth"
        )

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    obtained_at = tokens.get("obtained_at", 0)
    expires_in = tokens.get("expires_in", 3600)

    # Refresh 5 minutes before expiry; SoundCloud refresh tokens are single-use
    if access_token and time.time() < obtained_at + expires_in - 300:
        return access_token

    if not refresh_token:
        raise OAuthError("Access token expired and no refresh token. Run: soundcloud-mcp-auth")

    refreshed = await refresh_access_token(refresh_token)
    return refreshed["access_token"]


def run_local_oauth_login(*, open_browser: bool = True) -> dict[str, Any]:
    """Open browser, capture OAuth callback on localhost, exchange code for tokens."""
    import asyncio

    if not CLIENT_ID or not CLIENT_SECRET:
        raise OAuthError("Set SOUNDCLOUD_CLIENT_ID and SOUNDCLOUD_CLIENT_SECRET in .env first")

    state = secrets.token_urlsafe(16)
    verifier, challenge = _pkce_pair()
    auth_url = build_authorize_url(state=state, code_challenge=challenge)

    parsed = urllib.parse.urlparse(REDIRECT_URI)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    expected_paths = {
        parsed.path or "/callback",
        (parsed.path or "/callback").rstrip("/") or "/",
        ((parsed.path or "/callback").rstrip("/") or "/") + "/",
    }

    result: dict[str, str] = {}
    error: dict[str, str] = {}
    done = False

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle()

        def do_POST(self):
            self._handle()

        def _handle(self):
            nonlocal done
            query = urllib.parse.urlparse(self.path)
            if query.path not in expected_paths:
                self.send_response(404)
                self.end_headers()
                return

            params = urllib.parse.parse_qs(query.query)
            if self.command == "POST":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode() if length else ""
                params.update(urllib.parse.parse_qs(body))

            if params.get("error"):
                error["message"] = params.get("error_description", params["error"])[0]
                body = f"<h1>SoundCloud login failed</h1><p>{error['message']}</p>".encode()
            elif params.get("state", [""])[0] != state:
                error["message"] = "State mismatch"
                body = b"<h1>Invalid state</h1><p>You can close this tab.</p>"
            elif not params.get("code"):
                error["message"] = "Missing authorization code"
                body = b"<h1>Missing code</h1><p>You can close this tab.</p>"
            else:
                result["code"] = params["code"][0]
                body = b"<h1>SoundCloud connected!</h1><p>You can close this tab and return to Cursor.</p>"
                done = True

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = HTTPServer((host, port), CallbackHandler)

    print("SoundCloud OAuth login")
    print(f"Redirect URI (must match app settings exactly): {REDIRECT_URI}")
    print()
    print("If the browser page is blank/white, the redirect URI in your app")
    print("at https://soundcloud.com/you/apps does not match the line above.")
    print("Common fixes:")
    print("  - Use http://127.0.0.1:8765/callback (not localhost)")
    print("  - Include http:// (not https)")
    print("  - No trailing slash")
    print()
    print(f"Authorize URL:\n{auth_url}\n")

    if open_browser:
        print("Opening browser...")
        webbrowser.open(auth_url)
    else:
        print("Paste the authorize URL into your browser manually.")

    server.timeout = 1
    deadline = time.time() + 300
    while time.time() < deadline and not done and "code" not in result and not error:
        server.handle_request()

    server.server_close()

    if error:
        raise OAuthError(error.get("message", "OAuth login failed"))
    if "code" not in result:
        raise OAuthError(
            "Timed out waiting for OAuth callback. "
            "If the SoundCloud page was blank, fix the redirect URI in your app settings."
        )

    return asyncio.run(exchange_code(result["code"], verifier))

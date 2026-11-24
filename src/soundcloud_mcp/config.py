"""Configuration for SoundCloud MCP."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://api.soundcloud.com"
AUTH_BASE = "https://secure.soundcloud.com"

CLIENT_ID = os.getenv("SOUNDCLOUD_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("SOUNDCLOUD_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("SOUNDCLOUD_REDIRECT_URI", "http://127.0.0.1:8765/callback").strip()

_default_token = Path.home() / ".soundcloud-mcp" / "tokens.json"
TOKEN_FILE = Path(os.getenv("SOUNDCLOUD_TOKEN_FILE", str(_default_token))).expanduser()

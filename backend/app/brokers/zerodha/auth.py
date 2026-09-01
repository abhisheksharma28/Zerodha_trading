"""Kite Connect login/session-exchange flow.

Implements exactly what docs/ZERODHA_API_NOTES.md section 1 describes:
there is no password grant, no silent refresh — a human completes login in a
browser, the app receives a one-time `request_token`, and exchanges it for an
`access_token` that is valid until ~6 AM IST the next day.
"""

import hashlib
from urllib.parse import urlencode

KITE_LOGIN_URL = "https://kite.zerodha.com/connect/login"
KITE_API_BASE = "https://api.kite.trade"


def build_login_url(api_key: str) -> str:
    params = {"v": "3", "api_key": api_key}
    return f"{KITE_LOGIN_URL}?{urlencode(params)}"


def build_checksum(api_key: str, request_token: str, api_secret: str) -> str:
    """checksum = SHA-256(api_key + request_token + api_secret) — required by
    POST /session/token. Never log api_secret or the raw checksum input."""
    payload = f"{api_key}{request_token}{api_secret}".encode()
    return hashlib.sha256(payload).hexdigest()

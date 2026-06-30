"""Tiny signed-cookie session helper.

Avoids pulling in itsdangerous / starlette-session just for one cookie.
The cookie body is ``<expiry_unix_seconds>:<hex_hmac>`` where the HMAC
is computed over the expiry with ``WEB_SESSION_SECRET``.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from pi_remote_core import config

COOKIE_NAME = "pi_remote_session"


def _digest(payload: str) -> str:
    return hmac.new(
        config.WEB_SESSION_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def make_token(now: float | None = None) -> str:
    """Return a signed session token that expires in WEB_SESSION_HOURS."""
    if now is None:
        now = time.time()
    expiry = int(now + config.WEB_SESSION_HOURS * 3600)
    body = str(expiry)
    return f"{body}:{_digest(body)}"


def verify_token(token: str | None, now: float | None = None) -> bool:
    if not token:
        return False
    try:
        body, sig = token.rsplit(":", 1)
        expiry = int(body)
    except (ValueError, AttributeError):
        return False
    if not hmac.compare_digest(sig, _digest(body)):
        return False
    return (now or time.time()) < expiry

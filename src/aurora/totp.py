"""Rotating one-time operator tokens (anti-invention, Fase 2).

Eric's mandate: a STATIC operator token is reusable — once Eric types it into the
chat, Claude sees it forever and could replay it to authorize its own bypasses.
The fix is a TOTP-style rotating token that is worthless after ~60s / one use:

  * A SECRET is shared out-of-band between AURORA (env ``AURORA_TOTP_SECRET``, set
    by Eric directly in Render) and the Operator Console artifact (which generates
    the secret in Eric's browser and shows it once to paste into Render). Claude
    NEVER sees the secret.
  * The current token is HMAC-SHA256(secret, counter), where counter = floor(now/60).
    AURORA re-derives it from the shared secret; the Console derives the same value
    in the browser. They match by construction — no token ever travels through
    Claude except the one Eric reads aloud and Claude relays once.
  * A token is single-use: ``aurora.db.try_consume_token`` burns it, so it unlocks
    exactly ONE gate or bypass, then is dead even within its 60s window.

The algorithm is byte-identical to the Web-Crypto implementation in the Operator
Console (``operator_console.html``):
    counter      : floor(unix_seconds / STEP), as 8-byte big-endian
    digest       : HMAC-SHA256(utf8(secret), counter_bytes)
    token        : RFC4648 base32(digest), no padding, first TOKEN_LEN chars
Keep the two in lock-step; ``test_totp.py`` pins a known vector.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Optional

STEP = 60          # token lifetime in seconds (Eric's spec: "validez de un minuto")
TOKEN_LEN = 8      # base32 chars shown to the operator (~40 bits)
SKEW = 1           # also accept the previous window (clock drift + typing delay)


def _secret() -> Optional[bytes]:
    s = os.environ.get("AURORA_TOTP_SECRET")
    return s.strip().encode("utf-8") if s and s.strip() else None


def enabled() -> bool:
    """True when a rotating-token secret is configured. When False, the server
    falls back to the legacy static AURORA_OPERATOR_TOKEN (and tests that never
    set the secret keep exercising the static path)."""
    return _secret() is not None


def _counter(ts: Optional[float] = None) -> int:
    return int((time.time() if ts is None else ts) // STEP)


def token_for_counter(counter: int, secret: Optional[bytes] = None) -> str:
    """The token for an explicit counter — the unit under test and the value the
    browser console computes for the same window."""
    key = secret if secret is not None else _secret()
    if not key:
        raise RuntimeError("AURORA_TOTP_SECRET is not configured")
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")[:TOKEN_LEN]


def current_token(secret: Optional[bytes] = None, ts: Optional[float] = None) -> str:
    return token_for_counter(_counter(ts), secret)


def active_counters(ts: Optional[float] = None) -> tuple[int, ...]:
    c = _counter(ts)
    return tuple(c - i for i in range(SKEW + 1))


def normalize(token: Optional[str]) -> str:
    return (token or "").strip().upper().replace(" ", "")


def verify(token: Optional[str], ts: Optional[float] = None) -> Optional[int]:
    """Return the counter a token is valid for (current or previous window), or
    None if it is invalid / no secret is configured. This does NOT enforce single
    use — the caller burns the (counter, token) pair via db.try_consume_token so a
    read-only check (e.g. the /events feed) can authenticate without consuming."""
    key = _secret()
    tok = normalize(token)
    if not key or not tok:
        return None
    for c in active_counters(ts):
        if hmac.compare_digest(tok, token_for_counter(c, key)):
            return c
    return None

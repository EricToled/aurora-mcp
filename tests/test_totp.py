"""Rotating one-time operator token (anti-invention Fase 2) — algorithm lock.

These tests pin the TOTP algorithm so the Python server and the Web-Crypto
Operator Console can NEVER silently drift. If a refactor changes the byte math,
the pinned vector here fails loudly — and the browser would have stopped matching
AURORA, locking Eric out. The vector is computed by hand from the documented
construction (HMAC-SHA256(secret, counter_be8) -> base32 -> first 8 chars) so it
is independent of the implementation under test.
"""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from aurora import totp


SECRET = "AURORA-TEST-SECRET-DO-NOT-SHIP"
COUNTER = 29_000_000          # a fixed window: unix 1_740_000_000 // 60
TS_IN_WINDOW = COUNTER * totp.STEP + 3   # 3s into that window


def _hand_token(secret: str, counter: int) -> str:
    """Independent reference implementation of the documented construction."""
    digest = hmac.new(secret.encode("utf-8"), counter.to_bytes(8, "big"),
                      hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=")[:totp.TOKEN_LEN]


# --- algorithm shape -------------------------------------------------------- #
def test_token_matches_independent_reference():
    expected = _hand_token(SECRET, COUNTER)
    got = totp.token_for_counter(COUNTER, secret=SECRET.encode("utf-8"))
    assert got == expected


def test_token_is_eight_base32_chars():
    tok = totp.token_for_counter(COUNTER, secret=SECRET.encode("utf-8"))
    assert len(tok) == totp.TOKEN_LEN == 8
    assert tok == tok.upper()
    # base32 alphabet only (A-Z, 2-7), no padding
    assert set(tok) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def test_counter_derives_from_timestamp():
    assert totp._counter(TS_IN_WINDOW) == COUNTER
    assert totp.current_token(secret=SECRET.encode("utf-8"), ts=TS_IN_WINDOW) == \
        _hand_token(SECRET, COUNTER)


# --- enabled() / secret plumbing ------------------------------------------- #
def test_enabled_follows_env(monkeypatch):
    monkeypatch.delenv("AURORA_TOTP_SECRET", raising=False)
    assert totp.enabled() is False
    monkeypatch.setenv("AURORA_TOTP_SECRET", SECRET)
    assert totp.enabled() is True


def test_blank_secret_is_disabled(monkeypatch):
    monkeypatch.setenv("AURORA_TOTP_SECRET", "   ")
    assert totp.enabled() is False
    assert totp._secret() is None


def test_token_for_counter_without_secret_raises(monkeypatch):
    monkeypatch.delenv("AURORA_TOTP_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        totp.token_for_counter(COUNTER)


# --- verify() window + skew ------------------------------------------------- #
def test_verify_accepts_current_window(monkeypatch):
    monkeypatch.setenv("AURORA_TOTP_SECRET", SECRET)
    tok = totp.token_for_counter(COUNTER, secret=SECRET.encode("utf-8"))
    assert totp.verify(tok, ts=TS_IN_WINDOW) == COUNTER


def test_verify_accepts_previous_window_within_skew(monkeypatch):
    monkeypatch.setenv("AURORA_TOTP_SECRET", SECRET)
    prev = totp.token_for_counter(COUNTER - 1, secret=SECRET.encode("utf-8"))
    # Token from the previous minute is still accepted (clock drift + typing).
    assert totp.verify(prev, ts=TS_IN_WINDOW) == COUNTER - 1


def test_verify_rejects_two_windows_old(monkeypatch):
    monkeypatch.setenv("AURORA_TOTP_SECRET", SECRET)
    stale = totp.token_for_counter(COUNTER - 2, secret=SECRET.encode("utf-8"))
    assert totp.verify(stale, ts=TS_IN_WINDOW) is None


def test_verify_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("AURORA_TOTP_SECRET", SECRET)
    tok = totp.token_for_counter(COUNTER, secret=SECRET.encode("utf-8"))
    messy = " " + tok.lower()[:4] + " " + tok.lower()[4:] + " "
    assert totp.verify(messy, ts=TS_IN_WINDOW) == COUNTER


def test_verify_rejects_garbage_and_empty(monkeypatch):
    monkeypatch.setenv("AURORA_TOTP_SECRET", SECRET)
    assert totp.verify("NOPENOPE", ts=TS_IN_WINDOW) is None
    assert totp.verify("", ts=TS_IN_WINDOW) is None
    assert totp.verify(None, ts=TS_IN_WINDOW) is None


def test_verify_without_secret_is_none(monkeypatch):
    monkeypatch.delenv("AURORA_TOTP_SECRET", raising=False)
    # Even a structurally valid token can't verify with no secret (fail-closed).
    tok = _hand_token(SECRET, COUNTER)
    assert totp.verify(tok, ts=TS_IN_WINDOW) is None

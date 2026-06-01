"""Single-use enforcement for rotating operator tokens (anti-invention Fase 2).

totp.verify proves a token is cryptographically valid for ~60s; this ledger is
what makes it unlock EXACTLY ONE action. The replay these tests guard against is
Claude reusing the very code Eric read aloud — valid for the rest of its window,
but already spent.
"""
from __future__ import annotations

import pytest

from aurora import db


@pytest.fixture()
def dbp(tmp_path, monkeypatch):
    p = tmp_path / "tok.db"
    monkeypatch.setattr(db, "DB_PATH", p, raising=False)
    db.init_db(db_path=str(p))
    return str(p)


def test_first_use_burns_then_replay_refused(dbp):
    assert db.try_consume_token(100, "ABCD2345", "bypass", "proj-1", db_path=dbp) is True
    # Same (counter, token) again — a replay inside the window — is refused.
    assert db.try_consume_token(100, "ABCD2345", "bypass", "proj-1", db_path=dbp) is False


def test_same_token_different_window_is_independent(dbp):
    assert db.try_consume_token(100, "ABCD2345", "bypass", None, db_path=dbp) is True
    # A token string that happens to recur in a later window is its own pair.
    assert db.try_consume_token(101, "ABCD2345", "bypass", None, db_path=dbp) is True


def test_different_tokens_same_window_independent(dbp):
    assert db.try_consume_token(100, "AAAA2345", "approval", None, db_path=dbp) is True
    assert db.try_consume_token(100, "BBBB2345", "approval", None, db_path=dbp) is True


def test_feed_excludes_token_values(dbp):
    db.insert_security_event("unauthorized_bypass_attempt", project_id="proj-1",
                             component="gate_prompt_fitness", detail={"note": "x"},
                             db_path=dbp)
    feed = db.get_event_feed(db_path=dbp)
    assert len(feed) == 1
    row = feed[0]
    assert row["event_type"] == "unauthorized_bypass_attempt"
    assert row["resolved"] is False
    # The feed never carries token/secret material.
    assert "token" not in row and "secret" not in row

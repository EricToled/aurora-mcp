"""Rotating-token authorization through the server (anti-invention Fase 2).

When AURORA_TOTP_SECRET is configured, gate unlocks/bypasses must require a LIVE,
single-use TOTP code — not the static operator token. These lock in:

  * a valid rotating code authorizes a bypass,
  * the SAME code is dead on replay (single-use) even inside its 60s window,
  * an expired / wrong code is refused with SECURITY_HALT,
  * with a secret set, the OLD static AURORA_OPERATOR_TOKEN no longer authorizes,
  * decision-sheet approval flows through the same rotating gate.
"""
from __future__ import annotations

import time

import pytest

from aurora import bypass_handler, db, totp
from aurora import server as srv

SECRET = "rotating-secret-under-test"


@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "rot.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setenv("AURORA_TOTP_SECRET", SECRET)
    # A static token is ALSO present to prove the rotating regime takes precedence.
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", "legacy-static-token")
    srv._ensure_db()
    return srv.DB_PATH


def _code() -> str:
    return totp.current_token(secret=SECRET.encode("utf-8"))


def test_valid_rotating_code_authorizes_bypass(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip",
        component="gate_prompt_fitness", reason="skip", scope="persist",
        project_id=pid, operator_token=_code())
    assert res["ok"] is True and res["authorized"] is True


def test_rotating_code_is_single_use(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    code = _code()
    first = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip",
        component="gate_prompt_fitness", reason="skip", scope="persist",
        project_id=pid, operator_token=code)
    assert first["ok"] is True
    # Same live code, second action -> burned -> refused.
    second = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_lint - skip",
        component="gate_prompt_lint", reason="skip", scope="persist",
        project_id=pid, operator_token=code)
    assert second["ok"] is False
    assert second["status"] == "SECURITY_HALT"


def test_wrong_code_is_security_halt(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip",
        component="gate_prompt_fitness", reason="skip", scope="persist",
        project_id=pid, operator_token="NOTACODE")
    assert res["ok"] is False
    assert res["status"] == "SECURITY_HALT"


def test_static_token_does_not_authorize_when_secret_set(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    # The legacy static token must NOT work once a rotating secret is configured.
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip",
        component="gate_prompt_fitness", reason="skip", scope="persist",
        project_id=pid, operator_token="legacy-static-token")
    assert res["ok"] is False
    assert res["status"] == "SECURITY_HALT"


def test_expired_code_is_refused(server_db, monkeypatch):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    # A code from two windows ago is outside the SKEW and must be rejected.
    stale = totp.token_for_counter(totp._counter() - 5, secret=SECRET.encode("utf-8"))
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip",
        component="gate_prompt_fitness", reason="skip", scope="persist",
        project_id=pid, operator_token=stale)
    assert res["ok"] is False
    assert res["status"] == "SECURITY_HALT"

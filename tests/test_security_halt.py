"""Anti-invention enforcement tests (Sprint A) — authenticated override +
SECURITY_HALT.

AURORA's purpose is to STOP any invention and refuse to skip a step. The only
legitimate way to skip a gate is an operator-authorized bypass, proven by the
AURORA_OPERATOR_TOKEN. Claude cannot forge that consent.

These lock in:
  * an unauthenticated bypass attempt is REFUSED with a SECURITY_HALT alarm
    ("Claude está intentando bypasear el sistema") and recorded in security_events,
  * the unauthorized directive is never honored at emit (the gate still blocks),
  * an unresolved security event hard-blocks emit for the whole project,
  * a wrong token is treated exactly like no token,
  * a valid token authorizes the bypass and lets emit proceed,
  * with no AURORA_OPERATOR_TOKEN configured, NO bypass can be authorized
    (fail-closed).
"""
from __future__ import annotations

import pytest

from aurora import bypass_handler, db
from aurora import server as srv

OPERATOR_TOKEN = "test-operator-token"


@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "sec.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", OPERATOR_TOKEN)
    srv._ensure_db()
    return srv.DB_PATH


def test_unauthenticated_bypass_raises_security_halt(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip it",
        component="gate_prompt_fitness", reason="skip it", scope="persist",
        project_id=pid)  # no operator_token
    assert res["ok"] is False
    assert res["status"] == "SECURITY_HALT"
    assert "bypasear el sistema" in res["alarm"]
    # The attempt is recorded as a tamper-evident alarm.
    events = db.get_security_events(pid, db_path=str(server_db))
    assert any(e["event_type"] == "unauthorized_bypass_attempt" for e in events)


def test_unauthenticated_bypass_is_not_honored_at_emit(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip it",
        component="gate_prompt_fitness", reason="skip it", scope="persist",
        project_id=pid)  # no token -> recorded unauthorized
    emit = srv.aurora_emit_execution_pack(pid)
    # An unresolved security event hard-blocks emit entirely.
    assert emit["ok"] is False
    assert emit["status"] == "SECURITY_HALT"


def test_wrong_token_is_rejected_like_no_token(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip it",
        component="gate_prompt_fitness", reason="skip it", scope="persist",
        project_id=pid, operator_token="not-the-real-token")
    assert res["ok"] is False
    assert res["status"] == "SECURITY_HALT"


def test_valid_token_authorizes_bypass(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    srv.aurora_validate_preproduction_packet(packet=_video_packet(), project_id=pid)
    from aurora import gates as gates_pkg
    for gate in gates_pkg.required_gates_for_mode("video_simple"):
        res = srv.aurora_log_bypass(
            operator_text=f"OVERRIDE PERSIST: {gate} - authorized", component=gate,
            reason="authorized", scope="persist", project_id=pid,
            operator_token=OPERATOR_TOKEN)
        assert res["ok"] is True, (gate, res)
        assert res["authorized"] is True
    # Fase 1: also authorize bypassing the final Decision Sheet sign-off.
    srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_decision_sheet_approved - authorized",
        component="gate_decision_sheet_approved", reason="authorized", scope="persist",
        project_id=pid, operator_token=OPERATOR_TOKEN)
    # No security events were raised; emit proceeds.
    assert not db.get_security_events(pid, db_path=str(server_db))
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit


def test_no_token_configured_is_fail_closed(tmp_path, monkeypatch):
    # Token UNset on the server: even a caller-supplied token cannot authorize.
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "noenv.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.delenv("AURORA_OPERATOR_TOKEN", raising=False)
    srv._ensure_db()
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_fitness - skip", component="gate_prompt_fitness",
        reason="skip", scope="persist", project_id=pid, operator_token="anything")
    assert res["ok"] is False
    assert res["status"] == "SECURITY_HALT"


def _video_packet() -> dict:
    return {
        "model": "higgsfield_video_v1",
        "prompt_final": "A lone cellist plays in a candlelit hall, slow dolly-in.",
        "aspect_ratio": "16:9",
        "duration_seconds": 5,
        "shot_list": [{"shot_id": "s1", "description": "cellist, candlelight"}],
        "success_criteria": ["identity stable", "lighting consistent"],
    }

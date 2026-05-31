"""Anti-invention Fase 1 — Decision Sheet approval checkpoint.

Claude may legitimately PROPOSE details the brief never specified (a character's
age, a location's geometry, a lens, a shot duration, a PSP estimate). What is NOT
allowed is sealing an Execution Pack full of prompts built on those proposals
without the operator signing off. These tests lock in:

  * the pure sheet logic (operator-sourced decisions auto-approve; claude/research
    start pending; a sheet is approved only after the authenticated approval AND
    zero pending),
  * emit hard-blocks content modes with DECISION_SHEET_NOT_APPROVED until approved,
  * approval is token-authenticated — an attempt without a valid operator_token is
    REFUSED with a SECURITY_HALT (Claude cannot sign its own proposals),
  * a valid token clears the block,
  * an authorized OVERRIDE of the gate also clears it.
"""
from __future__ import annotations

import pytest

from aurora import bypass_handler, db, decision_sheet
from aurora import server as srv
from tests.test_persistence_v22 import _drive_multishot_to_psp  # proven green path

OPERATOR_TOKEN = "test-operator-token"


@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "ds.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", OPERATOR_TOKEN)
    srv._ensure_db()
    return srv.DB_PATH


# --------------------------------------------------------------------------- #
# Pure module logic
# --------------------------------------------------------------------------- #
def test_operator_decisions_autoapprove_others_pending():
    rows = decision_sheet.normalize_decisions([
        {"category": "character", "item": "lead", "field": "age", "value": 32,
         "source": "claude"},
        {"category": "location", "item": "hall", "field": "geometry",
         "value": "vaulted", "source": "operator"},
        {"category": "cinema", "item": "s1", "field": "lens", "value": "50mm",
         "source": "research"},
    ])
    by_id = {d["id"]: d for d in rows}
    assert by_id["character.lead.age"]["approved"] is False
    assert by_id["location.hall.geometry"]["approved"] is True  # operator-specified
    assert by_id["cinema.s1.lens"]["approved"] is False


def test_unknown_source_falls_back_to_claude_pending():
    rows = decision_sheet.normalize_decisions([
        {"item": "x", "value": 1, "source": "bogus"},
    ])
    assert rows[0]["source"] == "claude"
    assert rows[0]["approved"] is False


def test_duplicate_ids_are_disambiguated():
    rows = decision_sheet.normalize_decisions([
        {"category": "c", "item": "i", "field": "f", "value": 1},
        {"category": "c", "item": "i", "field": "f", "value": 2},
    ])
    assert {r["id"] for r in rows} == {"c.i.f", "c.i.f#1"}


def test_empty_or_all_operator_sheet_still_needs_authenticated_approval():
    # Closes the gaming hole: a sheet with nothing pending is NOT approved until
    # the authenticated approval sets operator_approved.
    sheet = {"decisions": decision_sheet.normalize_decisions([
        {"item": "x", "value": 1, "source": "operator"},
    ]), "operator_approved": False}
    assert decision_sheet.is_approved(sheet) is False
    decision_sheet.apply_approval(sheet, approve="all")
    assert decision_sheet.is_approved(sheet) is True


def test_selective_approval_and_edits():
    sheet = {"decisions": decision_sheet.normalize_decisions([
        {"category": "character", "item": "lead", "field": "age", "value": 32},
        {"category": "cinema", "item": "s1", "field": "lens", "value": "50mm"},
    ]), "operator_approved": False}
    # Approve one, edit the other (edit -> operator-owned + approved).
    decision_sheet.apply_approval(
        sheet, approve=["character.lead.age"],
        edits=[{"id": "cinema.s1.lens", "value": "85mm"}])
    by_id = {d["id"]: d for d in sheet["decisions"]}
    assert by_id["cinema.s1.lens"]["value"] == "85mm"
    assert by_id["cinema.s1.lens"]["source"] == "operator"
    assert decision_sheet.is_approved(sheet) is True


# --------------------------------------------------------------------------- #
# Server / emit integration
#
# _drive_multishot_to_psp drives every production gate green AND approves an
# (empty) Decision Sheet, so a project straight out of it emits clean. To exercise
# the BLOCK we re-create the sheet with a pending claude proposal, which resets the
# approval — proving the checkpoint is the LAST thing standing between green gates
# and a sealed pack.
# --------------------------------------------------------------------------- #
def _proposals() -> list[dict]:
    return [
        {"category": "character", "item": "lead", "field": "age", "value": 32,
         "source": "claude"},
        {"category": "cinema", "item": "s1", "field": "duration_s", "value": 5,
         "source": "claude"},
    ]


def _green(pid: str) -> None:
    _drive_multishot_to_psp(pid)


def test_green_pack_with_approved_sheet_emits(server_db):
    pid = srv.aurora_create_project(
        "quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _green(pid)  # drives gates green + approves an empty sheet
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason") or emit.get("status")


def test_emit_blocks_when_sheet_unapproved(server_db):
    pid = srv.aurora_create_project(
        "quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _green(pid)
    # A new claude proposal resets the approval; the pack must NOT seal.
    res = srv.aurora_create_decision_sheet(pid, _proposals())
    assert res["approved"] is False
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"] is False
    assert emit["status"] == "DECISION_SHEET_NOT_APPROVED"
    assert len(emit["decision_sheet"]["pending"]) == 2


def test_approval_without_token_raises_security_halt(server_db):
    pid = srv.aurora_create_project(
        "quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _green(pid)
    srv.aurora_create_decision_sheet(pid, _proposals())
    res = srv.aurora_approve_decision_sheet(pid)  # no operator_token
    assert res["ok"] is False
    assert res["status"] == "SECURITY_HALT"
    assert any(
        e["event_type"] == "unauthorized_decision_sheet_approval"
        for e in db.get_security_events(pid, db_path=str(server_db))
    )
    # The unresolved alarm now hard-blocks emit entirely.
    assert srv.aurora_emit_execution_pack(pid)["status"] == "SECURITY_HALT"


def test_wrong_token_is_rejected_like_no_token(server_db):
    pid = srv.aurora_create_project(
        "quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _green(pid)
    srv.aurora_create_decision_sheet(pid, _proposals())
    res = srv.aurora_approve_decision_sheet(pid, operator_token="nope")
    assert res["status"] == "SECURITY_HALT"


def test_valid_token_approves_and_seals_the_pack(server_db):
    pid = srv.aurora_create_project(
        "quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _green(pid)
    srv.aurora_create_decision_sheet(pid, _proposals())
    assert srv.aurora_emit_execution_pack(pid)["status"] == "DECISION_SHEET_NOT_APPROVED"
    res = srv.aurora_approve_decision_sheet(pid, operator_token=OPERATOR_TOKEN)
    assert res["ok"] is True and res["approved"] is True
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason") or emit.get("status")


def test_authorized_override_skips_decision_sheet(server_db):
    pid = srv.aurora_create_project(
        "quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _green(pid)
    srv.aurora_create_decision_sheet(pid, _proposals())  # resets approval
    bp = srv.aurora_log_bypass(
        operator_text="OVERRIDE: gate_decision_sheet_approved - operator signs off verbally",
        component="gate_decision_sheet_approved", reason="verbal", scope="current_turn",
        project_id=pid, operator_token=OPERATOR_TOKEN)
    assert bp["ok"] is True and bp["authorized"] is True
    emit = srv.aurora_emit_execution_pack(pid, bypass_ids=[bp["bypass_id"]])
    assert emit["ok"], emit.get("reason") or emit.get("status")

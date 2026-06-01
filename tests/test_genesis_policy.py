"""Genesis-routing policy tests (R11): gpt_image_2 is the DEFAULT genesis model;
deviating to another model requires an operator-acknowledged
``platform_genesis_deviation`` whose rationale survives the whitelist.

Three layers:
  * pure policy (genesis_policy.py),
  * decision-sheet normalize/approval preservation + acknowledgement,
  * emit integration: an unauthorized genesis deviation blocks delivery, an
    authorized one is audited.
"""
from __future__ import annotations

import pytest

from aurora import bypass_handler, db, decision_sheet, genesis_policy
from aurora import server as srv
from aurora.routers import image_model_router

OPERATOR_TOKEN = "test-operator-token"


@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "genesis.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", OPERATOR_TOKEN)
    srv._ensure_db()
    return srv.DB_PATH


def _genesis_decision(value: str, **extra):
    d = {
        "category": "model_routing",
        "item": "character portrait genesis",
        "field": "model",
        "value": value,
        "source": "claude",
    }
    d.update(extra)
    return d


# === pure policy ============================================================
def test_default_genesis_is_gpt_image_2():
    assert genesis_policy.PRIMARY_GENESIS_DEFAULT == "gpt_image_2"


def test_is_genesis_routing_decision_detection():
    assert genesis_policy.is_genesis_routing_decision(_genesis_decision("gpt_image_2"))
    # not a model-routing decision
    assert not genesis_policy.is_genesis_routing_decision(
        {"category": "character", "item": "age", "field": "value", "value": "30"})
    # model routing but not genesis/anchor
    assert not genesis_policy.is_genesis_routing_decision(
        {"category": "model_routing", "item": "video model", "field": "model", "value": "kling"})


def test_default_choice_has_no_problem():
    sheet = {"decisions": decision_sheet.normalize_decisions([_genesis_decision("gpt_image_2")])}
    assert genesis_policy.genesis_deviation_problems(sheet) == []


def test_deviation_without_flag_is_blocked():
    # normalize WITHOUT skeleton injection -> missing flag
    sheet = {"decisions": [
        {"id": "d1", "category": "model_routing", "item": "character genesis",
         "field": "model", "value": "soul_cinematic", "source": "claude"}]}
    probs = genesis_policy.genesis_deviation_problems(sheet)
    assert probs and probs[0]["problem"] == "missing_deviation_flag"


def test_deviation_not_acknowledged_is_blocked():
    decisions = genesis_policy.inject_deviation_skeletons(
        decision_sheet.normalize_decisions([_genesis_decision("soul_cinematic")]))
    sheet = {"decisions": decisions}
    probs = genesis_policy.genesis_deviation_problems(sheet)
    assert probs and probs[0]["problem"] == "not_acknowledged"


def test_acknowledged_but_weak_reason_is_blocked():
    decisions = genesis_policy.inject_deviation_skeletons(
        decision_sheet.normalize_decisions(
            [_genesis_decision("soul_cinematic", rationale="cinematic look")]))
    decisions[0]["platform_genesis_deviation"]["operator_acknowledged"] = True
    sheet = {"decisions": decisions}
    probs = genesis_policy.genesis_deviation_problems(sheet)
    assert probs and probs[0]["problem"] == "weak_reason"


def test_acknowledged_with_whitelist_reason_passes():
    reason = "gpt_image_2 cannot render required on-image text or packaging typography"
    decisions = genesis_policy.inject_deviation_skeletons(
        decision_sheet.normalize_decisions(
            [_genesis_decision("nano_banana_pro", rationale=reason)]))
    decisions[0]["platform_genesis_deviation"]["operator_acknowledged"] = True
    sheet = {"decisions": decisions}
    assert genesis_policy.genesis_deviation_problems(sheet) == []
    auth = genesis_policy.authorized_genesis_deviations(sheet)
    assert auth and auth[0]["chosen_model"] == "nano_banana_pro"


def test_reason_whitelist_rejects_generic():
    for bad in ("cinematic look", "premium quality", "photorealistic", "Claude prefers it"):
        assert not genesis_policy.reason_is_acceptable(bad)


def test_reason_whitelist_accepts_real_person_identity():
    assert genesis_policy.reason_is_acceptable(
        "a real-person identity anchor requires soul_id consent-trained likeness")


# === decision-sheet preservation + acknowledgement =========================
def test_normalize_preserves_deviation_and_rationale():
    out = decision_sheet.normalize_decisions(
        [_genesis_decision("soul_cinematic",
                           platform_genesis_deviation={"deviates": True},
                           rationale="some reason")])
    assert out[0]["platform_genesis_deviation"] == {"deviates": True}
    assert out[0]["rationale"] == "some reason"


def test_inject_skeleton_is_idempotent():
    once = genesis_policy.inject_deviation_skeletons(
        decision_sheet.normalize_decisions([_genesis_decision("soul_cinematic")]))
    twice = genesis_policy.inject_deviation_skeletons(once)
    assert once[0]["platform_genesis_deviation"] is twice[0]["platform_genesis_deviation"] \
        or once[0]["platform_genesis_deviation"] == twice[0]["platform_genesis_deviation"]


def test_approval_sets_operator_acknowledged():
    decisions = genesis_policy.inject_deviation_skeletons(
        decision_sheet.normalize_decisions([_genesis_decision("soul_cinematic")]))
    sheet = {"decisions": decisions, "operator_approved": False}
    decision_sheet.apply_approval(sheet, approve="all")
    assert sheet["decisions"][0]["platform_genesis_deviation"]["operator_acknowledged"] is True


# === routing default ========================================================
def test_router_ranks_gpt_image_2_first_for_genesis():
    res = image_model_router.select_route("genesis")
    assert res["ok"]
    assert res["selected_route"]["model_id"] == "gpt_image_2"


def test_router_ranks_gpt_image_2_first_for_character():
    res = image_model_router.select_route("character")
    assert res["selected_route"]["model_id"] == "gpt_image_2"


# === emit integration =======================================================
def _approve(pid, **kw):
    return srv.aurora_approve_decision_sheet(
        project_id=pid, operator_token=OPERATOR_TOKEN, **kw)


def test_emit_blocks_unauthorized_genesis_deviation(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    # A genesis routing decision that deviates to a non-default model with a weak
    # reason; create injects the skeleton (not acknowledged).
    srv.aurora_create_decision_sheet(
        project_id=pid,
        decisions=[_genesis_decision("soul_cinematic", rationale="cinematic look")])
    # Approve everything (acknowledges the deviation) so the decision-sheet gate
    # passes and we reach the genesis policy check.
    _approve(pid)
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["status"] == "GENESIS_DEVIATION_BLOCKED"
    assert emit["genesis_problems"]


def test_emit_allows_default_genesis(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    srv.aurora_create_decision_sheet(
        project_id=pid, decisions=[_genesis_decision("gpt_image_2")])
    _approve(pid)
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit.get("status") != "GENESIS_DEVIATION_BLOCKED"


def test_emit_allows_authorized_genesis_deviation(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    reason = "gpt_image_2 cannot render required on-image text or packaging typography"
    srv.aurora_create_decision_sheet(
        project_id=pid,
        decisions=[_genesis_decision("nano_banana_pro", rationale=reason)])
    _approve(pid)
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit.get("status") != "GENESIS_DEVIATION_BLOCKED"
    audits = db.get_audits(pid, db_path=str(server_db))
    assert any(a["criterion"] == "GENESIS_DEVIATION_AUTHORIZED" for a in audits)

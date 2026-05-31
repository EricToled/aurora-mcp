"""Anti-invention enforcement tests (Sprint B) — per-step honesty attestation.

Eric's mandate: AURORA must not let Claude run every step and hand over a single
document at the end. It forces step-by-step delivery, and at the END OF EACH STEP
AURORA asks — by design — whether Claude INVENTED any of the information it put in
the report. An honest "yes" BLOCKS the delivery, forces the step to be redone, and
fires the push alert.

These lock in:
  * every content tool appends a mandatory honesty `attestation_required` directive,
  * a clean attestation (invented=False) seals the step,
  * a confession (invented=True) raises a SECURITY_HALT, records an
    `invention_confessed` security event, and orders the step redone (must_redo_step),
  * emit refuses the final document while a required step lacks a CURRENT clean
    attestation (ATTESTATION_REQUIRED),
  * emit hard-blocks (SECURITY_HALT) while a confession is unresolved,
  * a clean RE-attestation of a previously-confessed step clears the alarm and lets
    emit proceed (the "redo the step honestly" path),
  * a gate bypassed by an AUTHORIZED operator override does not require attestation.
"""
from __future__ import annotations

import pytest

from aurora import bypass_handler, db
from aurora import server as srv
from tests.test_persistence_v22 import (  # proven gate-green building blocks
    _multishot_packet,
    _multishot_shot_list,
    _operator_prompt_packet,
    _record_research,
)

OPERATOR_TOKEN = "test-operator-token"


@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "attest.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", OPERATOR_TOKEN)
    srv._ensure_db()
    return srv.DB_PATH


def _drive_gates_green_no_attest(pid: str) -> None:
    """Run S3-S12 of the multishot pipeline so every required gate is recorded
    passing — but DELIBERATELY skip the honesty attestations, so attestation
    enforcement can be tested in isolation."""
    srv.aurora_create_domain_session_lock(
        pid, {"domain": "music", "sub_domain": "classical_performance",
              "project_scope": "video_multishot"})
    srv.aurora_refresh_higgsfield_capabilities(scope="light_session", project_id=pid)
    srv.aurora_create_benchmark_pack(
        pid, [{"url_or_path": "https://ref/quartet.jpg",
               "visual_traits": {"warmth": "high"}}])
    srv.aurora_verify_route(
        pid, "video_generation",
        {"route_type": "mcp_callable", "verified": True,
         "verification_source": "higgsfield_mcp_live", "confidence": 0.95})
    srv.aurora_validate_preproduction_packet(packet=_multishot_packet(), project_id=pid)
    _record_research("higgsfield_video_v1", "video_multishot", pid)
    srv.aurora_record_quality_score(
        pid, "image", {k: 100 for k in (
            "photorealism", "advertising_look", "lighting_quality", "composition",
            "materials_textures", "anatomy_geometry", "brand_product_fidelity",
            "artifact_absence")})
    srv.aurora_record_audit(pid, "identity_consistency", "pass")
    srv.aurora_check_quality_ceiling(pid)
    srv.aurora_validate_biomechanics(
        pid, {"action": "bowing", "scores": {k: 100 for k in (
            "valid_support_points", "center_of_mass_plausible", "joint_range_plausible",
            "object_trajectory_plausible", "contact_mechanics_plausible",
            "equipment_environment_constraints", "no_impossible_movement")}})
    srv.aurora_check_prompt_fitness(pid, _operator_prompt_packet())
    srv.aurora_check_multishot_strategy(pid, _multishot_shot_list())
    srv.aurora_check_anchors_ready(pid)
    srv.aurora_skip_finishing(pid, reason="raw higgsfield output is final")
    srv.aurora_record_psp_components(pid, {k: 100 for k in (
        "gate_compliance", "route_verification", "benchmark_match", "anchor_quality",
        "biomechanical_plausibility", "continuity_readiness", "prompt_fitness")})
    srv.aurora_compute_production_success_probability(pid)
    # Fase 1 (Decision Sheet): operator sign-off. Checked AFTER attestation, so
    # the missing-attestation test still surfaces ATTESTATION_REQUIRED first.
    srv.aurora_create_decision_sheet(pid, [])
    srv.aurora_approve_decision_sheet(pid, operator_token=OPERATOR_TOKEN)


def _attest_all_clean(pid: str) -> None:
    mode = srv.db.get_project(pid, db_path=srv._db())["mode"]
    for step in srv._required_steps_for_mode(mode):
        srv.aurora_attest_step(pid, step, invented=False)


# --- the honesty question is appended to every content step -----------------
def test_content_tool_appends_attestation_directive(server_db):
    pid = srv.aurora_create_project("x", "video_multishot", "perf")["project_id"]
    out = srv.aurora_create_benchmark_pack(
        pid, [{"url_or_path": "https://ref/a.jpg", "visual_traits": {"warmth": "high"}}])
    directive = out.get("attestation_required")
    assert directive is not None
    assert directive["step"] == "benchmark_pack"
    assert directive["mandatory"] is True
    assert "invent" in directive["question"].lower()


# --- a clean attestation seals the step -------------------------------------
def test_clean_attestation_seals_step(server_db):
    pid = srv.aurora_create_project("x", "video_multishot", "perf")["project_id"]
    res = srv.aurora_attest_step(pid, "benchmark_pack", invented=False)
    assert res["ok"] is True
    assert res["sealed_step"] == "benchmark_pack"
    assert res["invented"] is False
    current = db.get_current_step_attestations(pid, db_path=str(server_db))
    assert not current["benchmark_pack"]["invented"]  # stored 0/1


# --- a confession raises the alarm and orders a redo ------------------------
def test_confession_raises_security_halt_and_forces_redo(server_db):
    pid = srv.aurora_create_project("x", "video_multishot", "perf")["project_id"]
    res = srv.aurora_attest_step(
        pid, "preproduction_packet", invented=True,
        invented_fields=["location", "shot_list"], notes="no tenía la locación real")
    assert res["status"] == "SECURITY_HALT"
    assert res["must_redo_step"] == "preproduction_packet"
    assert "operator_action_required" in res
    events = db.get_security_events(pid, db_path=str(server_db))
    assert any(e["event_type"] == "invention_confessed"
               and e["component"] == "preproduction_packet" for e in events)


# --- emit refuses while a required step is unattested -----------------------
def test_emit_blocks_on_missing_attestation(server_db):
    pid = srv.aurora_create_project(
        "Vivaldi quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _drive_gates_green_no_attest(pid)  # every SHAPE gate passes...
    emit = srv.aurora_emit_execution_pack(pid)
    # ...but the TRUTH attestations are missing, so the document is withheld.
    assert emit["ok"] is False
    assert emit["status"] == "ATTESTATION_REQUIRED"
    assert emit["missing_attestations"]  # non-empty
    assert "questions" in emit


# --- emit delivers once every required step is attested clean ---------------
def test_emit_succeeds_after_all_clean_attestations(server_db):
    pid = srv.aurora_create_project(
        "Vivaldi quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _drive_gates_green_no_attest(pid)
    _attest_all_clean(pid)
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason") or emit.get("status")
    assert emit["gate_evaluation"]["all_clear"] is True


# --- a confession hard-blocks emit for the whole project --------------------
def test_emit_hard_blocks_while_confession_unresolved(server_db):
    pid = srv.aurora_create_project(
        "Vivaldi quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _drive_gates_green_no_attest(pid)
    _attest_all_clean(pid)
    # Now confess one step: the unresolved alarm hard-blocks emit entirely.
    srv.aurora_attest_step(pid, "benchmark_pack", invented=True,
                           invented_fields=["url_or_path"])
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"] is False
    assert emit["status"] == "SECURITY_HALT"


# --- redoing the step honestly clears the alarm and lets emit proceed -------
def test_clean_reattestation_clears_alarm(server_db):
    pid = srv.aurora_create_project(
        "Vivaldi quartet, 3 shots", "video_multishot", "performance")["project_id"]
    _drive_gates_green_no_attest(pid)
    _attest_all_clean(pid)
    srv.aurora_attest_step(pid, "benchmark_pack", invented=True,
                           invented_fields=["url_or_path"])
    # Redo the step honestly: a clean re-attestation supersedes the confession
    # and resolves the alarm.
    redo = srv.aurora_attest_step(pid, "benchmark_pack", invented=False)
    assert redo["ok"] is True
    assert not db.get_security_events(pid, db_path=str(server_db))
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason") or emit.get("status")


# --- an AUTHORIZED bypass exempts a gate from the attestation requirement ----
def test_bypassed_gate_needs_no_attestation(server_db):
    pid = srv.aurora_create_project("x", "video_multishot", "perf")["project_id"]
    srv.aurora_validate_preproduction_packet(packet=_multishot_packet(), project_id=pid)
    from aurora import gates as gates_pkg
    # Authorize a bypass for every required gate; with all gates bypassed, emit
    # must proceed WITHOUT any honesty attestations.
    for gate in gates_pkg.required_gates_for_mode("video_multishot"):
        res = srv.aurora_log_bypass(
            operator_text=f"OVERRIDE PERSIST: {gate} - operator authorized",
            component=gate, reason="authorized", scope="persist", project_id=pid,
            operator_token=OPERATOR_TOKEN)
        assert res["ok"] is True
    # Fase 1: also bypass the final Decision Sheet sign-off (operator authorized all).
    srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_decision_sheet_approved - operator authorized",
        component="gate_decision_sheet_approved", reason="authorized", scope="persist",
        project_id=pid, operator_token=OPERATOR_TOKEN)
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason") or emit.get("status")

"""Regression tests for AURORA v2.2 — Bugs #7-#11 + persistence architecture.

These lock in the fixes that let the MULTISHOT pipeline reach the Execution
Pack green:

  #7  prompt fitness scores a rich operator packet sensibly (not ~1).
  #8  validate_preproduction_packet persists; emit reads the same verdict.
  #9  a logged bypass is honored at emit via bypass_ids / current_turn scope.
  #10 continuity gate reads the persisted shot_list packet, not empty state.
  #11 a project can declare "no finishing route required".

The capstone, ``test_full_multishot_path_emits_green``, drives a complete
video_multishot project through the server tools (Vivaldi quartet) and asserts
emit returns all_clear with rendered markdown — the case that let #4-#11 escape.
"""
from __future__ import annotations

import pytest

from aurora import bypass_handler, db
from aurora import server as srv
from aurora.scoring import prompt_fitness_score


# --- shared multishot fixtures ---------------------------------------------
def _operator_prompt_packet() -> dict:
    """A rich prompt packet as an operator would author it (no rubric scores)."""
    return {
        "model": "higgsfield_video_v1",
        "prompt_final": "A string quartet plays Vivaldi in a candlelit hall.",
        "action": "the quartet plays in unison",
        "subject": ["@violinist_soul", "@cellist_soul"],
        "camera": {"body": "ARRI", "focal_mm": 50, "movement": "slow dolly",
                   "aspect_ratio": "16:9"},
        "biomechanical_motion_plan_id": "mp-1",
        "look": "warm baroque chiaroscuro",
        "negative_constraints": ["no modern clothing", "no electric light",
                                 "no extra fingers"],
        "contradictions": [],
    }


def _multishot_shot_list() -> list[dict]:
    """A 3-shot multishot list satisfying BOTH anchor + continuity gates.

    Shot 1 is a simple_start opener (continuity exempt); shots 2-3 carry an
    anchor reference AND a continuity ref so neither gate blocks.
    """
    return [
        {"shot_number": 1, "duration_seconds": 5, "shot_type": "establishing",
         "anchor_strategy": {"case_type": "simple_start",
                             "ff_higgsfield_element_id": "elem-quartet-ff"},
         "continuity": {"continuity_ref_type": "none"}},
        {"shot_number": 2, "duration_seconds": 5, "shot_type": "closeup",
         "anchor_strategy": {"case_type": "continuity_from_previous",
                             "previous_clip_ref": "shot-1-clip",
                             "character_higgsfield_element_id": "elem-violinist"},
         "continuity": {"continuity_ref_type": "last_frame"}},
        {"shot_number": 3, "duration_seconds": 5, "shot_type": "wide",
         "anchor_strategy": {"case_type": "continuity_from_previous",
                             "previous_clip_ref": "shot-2-clip",
                             "location_higgsfield_element_id": "elem-hall"},
         "continuity": {"continuity_ref_type": "last_5s"}},
    ]


def _multishot_packet() -> dict:
    """A complete 12-component preproduction packet for the quartet."""
    return {
        "idea": "A string quartet performs Vivaldi's Four Seasons in a hall.",
        "script": {"beats": ["tuning", "allegro", "adagio", "finale"]},
        "shot_list": _multishot_shot_list(),
        "characters": [{"name": "violinist", "soul_id": "elem-violinist"}],
        "location": {"name": "candlelit baroque concert hall"},
        "props_or_product": [{"name": "violin"}, {"name": "cello"}],
        "visual_style": "warm baroque chiaroscuro, anamorphic 50mm",
        "biomechanical_plan": [{"shot_number": 1, "action": "bowing"}],
        "ff_lf_strategy": "continuity_from_previous",
        "recommended_model": "higgsfield_video_v1",
        "ui_or_mcp_route": "mcp",
        "success_criteria": ["identity stable across shots", "bowing reads as real"],
    }


@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    """Isolate the server on a temp DB + session-state file."""
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "v22.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    srv._ensure_db()
    return srv.DB_PATH


def _drive_multishot_to_psp(pid: str) -> None:
    """Run S3-S12 of the multishot pipeline so every required gate is recorded
    passing. Stops before emit so individual tests can assert on emit."""
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


# --- Bug #7: prompt fitness on a real packet --------------------------------
def test_prompt_fitness_score_real():
    result = prompt_fitness_score.score(_operator_prompt_packet())
    assert result["total_score"] >= 80, result
    assert result["recognized_criteria"] >= 7, result
    assert result["total_score"] >= prompt_fitness_score.THRESHOLD


def test_prompt_fitness_rubric_path_still_100():
    rubric = {k: 100 for k in prompt_fitness_score.WEIGHTS}
    result = prompt_fitness_score.score(rubric)
    assert result["total_score"] == 100
    assert result["recognized_criteria"] == len(prompt_fitness_score.WEIGHTS)


# --- Bug #8: validate persists, emit reads the recorded verdict -------------
def test_preproduction_packet_persists(server_db):
    pid = srv.aurora_create_project("vivaldi", "video_multishot", "performance")["project_id"]
    out = srv.aurora_validate_preproduction_packet(packet=_multishot_packet(), project_id=pid)
    assert out["passed"] is True
    recorded = db.get_latest_gate_evaluations(pid, db_path=str(server_db))
    assert recorded["gate_preproduction_packet"]["status"] == "pass"
    # The shot_list inside the packet is persisted on its own for the multishot
    # + continuity gates to read at emit time (bug #10).
    assert db.get_artifact(pid, "shot_list", db_path=str(server_db))


def test_validate_requires_project_id(server_db):
    # A forgotten project_id kwarg used to persist nothing silently, so emit
    # later read an empty DB and rendered a ceremonial-green-but-empty pack.
    # The tool now refuses without an id instead of failing silently.
    out = srv.aurora_validate_preproduction_packet(packet={"shot_list": [{}]})
    assert out["ok"] is False
    assert "project_id required" in out["error"]


def test_validate_falls_back_to_project_id_in_packet(server_db):
    # If the kwarg is omitted but the packet carries its own project_id, use it —
    # the verdict is still persisted and emit can read it back.
    pid = srv.aurora_create_project("vivaldi", "video_multishot", "performance")["project_id"]
    packet = dict(_multishot_packet(), project_id=pid)
    out = srv.aurora_validate_preproduction_packet(packet=packet)
    assert out["passed"] is True
    recorded = db.get_latest_gate_evaluations(pid, db_path=str(server_db))
    assert recorded["gate_preproduction_packet"]["status"] == "pass"


# --- Bug #9: a logged bypass is honored at emit -----------------------------
def test_bypass_ids_honored_in_emit(server_db):
    pid = srv.aurora_create_project("vivaldi", "video_multishot", "performance")["project_id"]
    # Empty project: prompt_fitness would block. A current_turn bypass + bypass_ids
    # must flip it to "bypassed", not "fail".
    log = srv.aurora_log_bypass(
        operator_text="OVERRIDE gate_prompt_fitness - operator accepts",
        component="gate_prompt_fitness", reason="operator accepts", scope="current_turn",
        project_id=pid)
    assert log["ok"], log
    # Bypass every OTHER required gate via persist so we isolate prompt_fitness.
    from aurora import gates as gates_pkg
    for gate in gates_pkg.required_gates_for_mode("video_multishot"):
        if gate == "gate_prompt_fitness":
            continue
        srv.aurora_log_bypass(operator_text=f"OVERRIDE {gate}", component=gate,
                              reason="isolation", scope="persist", project_id=pid)
    emit = srv.aurora_emit_execution_pack(pid, bypass_ids=[log["bypass_id"]])
    assert emit["ok"], emit.get("reason")
    bypassed = {g["name"] for g in emit["gate_evaluation"]["bypassed_gates"]}
    assert "gate_prompt_fitness" in bypassed, emit["gate_evaluation"]


# --- Bug #10: continuity gate reads the persisted shot_list -----------------
def test_continuity_readiness_reads_persisted_packet(server_db):
    pid = srv.aurora_create_project("vivaldi", "video_multishot", "performance")["project_id"]
    # Only persist the packet (which embeds the shot_list); never call the
    # multishot check tool. emit must still see continuity pass off the packet.
    srv.aurora_validate_preproduction_packet(packet=_multishot_packet(), project_id=pid)
    from aurora.gates import gate_continuity_readiness
    shot_list = db.get_artifact(pid, "shot_list", db_path=str(server_db))
    assert gate_continuity_readiness.check(shot_list).passed is True


# --- Gap #11: declare "no finishing route required" -------------------------
def test_skip_finishing_records_pass(server_db):
    pid = srv.aurora_create_project("vivaldi", "video_simple", "performance")["project_id"]
    out = srv.aurora_skip_finishing(pid, reason="raw output is final")
    assert out["ok"] and out["finishing"]["not_required"] is True
    recorded = db.get_latest_gate_evaluations(pid, db_path=str(server_db))
    assert recorded["gate_upscale_finishing_route"]["status"] == "pass"


def test_finishing_route_message_is_actionable():
    from aurora.gates import gate_upscale_finishing_route as g
    result = g.check(None)
    assert result.passed is False
    msg = " ".join(result.reasons)
    assert "aurora_skip_finishing" in msg
    assert "aurora_propose_video_execution" in msg


def test_finishing_route_not_required_short_circuits():
    from aurora.gates import gate_upscale_finishing_route as g
    result = g.check({"not_required": True, "upscale_route": "outside_aurora", "tools": []})
    assert result.passed is True


# --- Capstone: the full multishot path emits green --------------------------
def test_full_multishot_path_emits_green(server_db):
    pid = srv.aurora_create_project(
        "Vivaldi Four Seasons quartet, 3 shots", "video_multishot", "performance",
    )["project_id"]
    _drive_multishot_to_psp(pid)
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason")
    ev = emit["gate_evaluation"]
    assert ev["all_clear"] is True, ev["blocking_gates"]
    md = emit["markdown"]
    assert md is not None and len(md) > 0
    # No gate may be "fail"; every required multishot gate must be present.
    statuses = {g["name"]: g["status"] for g in ev["gates"]}
    from aurora import gates as gates_pkg
    for gate in gates_pkg.required_gates_for_mode("video_multishot"):
        assert gate in statuses, f"{gate} missing from evaluation"
        assert statuses[gate] != "fail", (gate, statuses[gate])

    # --- the pack must be OPERATIVELY populated, not ceremonially green ------
    # A green pack with blank critical sections is useless (the bug Eric caught):
    # the validated packet's data must reach sections 5 (elements), 7 (UI), and
    # 8 (per-shot execution instructions), and 11 (success criteria).
    assert "violinist" in md, "section 5: element catalogue is empty"
    assert "elem-violinist" in md, "section 5: soul_id from packet not rendered"
    assert "warm baroque chiaroscuro" in md, "section 7: global UI style missing"
    for n in (1, 2, 3):
        assert f"### Shot {n}" in md, f"section 8: shot {n} not rendered"
    assert "elem-quartet-ff" in md, "section 8: shot-1 FF anchor not rendered"
    assert "identity stable across shots" in md, "section 11: success criteria missing"
    # Section 8 must carry the per-shot UI config + MCSLA the operator executes.
    assert "UI config panel por panel" in md
    assert "MCSLA breakdown" in md

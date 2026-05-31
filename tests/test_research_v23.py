"""Regression tests for AURORA v2.3 — research-driven prompt construction.

These lock in the seam that lets AURORA construct platform-specific MCSLA prompts
instead of leaving the operator to remember each model's syntax:

  * aurora_request_platform_research returns a 3-source research brief (or a cached
    dossier).
  * aurora_record_platform_research refuses a dossier that doesn't cover all 3
    mandatory source types.
  * aurora_build_prompt blocks without a fresh dossier, builds with one.
  * gate_platform_syntax_researched blocks emit for BOTH pipelines (image + video)
    when any declared model is unresearched, and is bypassable.
"""
from __future__ import annotations

import pytest

from aurora import bypass_handler, db
from aurora import server as srv
from aurora.gates import gate_platform_syntax_researched as gate


# --- fixtures / helpers -----------------------------------------------------
@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "v23.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    srv._ensure_db()
    return srv.DB_PATH


def _sources(n: int = 3) -> list[dict]:
    all_sources = [
        {"source_type": "official_docs", "url_or_ref": "https://docs/x",
         "fetched_at": "2026-05-30", "verbatim_quote": "Q1"},
        {"source_type": "mcp_introspection", "url_or_ref": "models_explore",
         "fetched_at": "2026-05-30", "verbatim_quote": "Q2"},
        {"source_type": "community_forums", "url_or_ref": "https://reddit/x",
         "fetched_at": "2026-05-30", "verbatim_quote": "Q3"},
    ]
    return all_sources[:n]


def _dossier(model_id: str, output_type: str) -> dict:
    return {
        "model_id": model_id,
        "output_type": output_type,
        "model_display_name": model_id.title(),
        "prompt_template": "{subject}, {action}, {look}, {camera}",
        "prompt_max_chars": 0,
        "forbidden_in_prompt": ["2.35:1 aspect ratio"],
        "continuity_injection": {
            "method": "media_role_start_image",
            "mcp_payload_example": {"medias": [{"roles": ["start_image"]}]},
            "ui_steps": ["click + button"],
            "notes": "inject previous clip",
        },
        "params_schema": [{"name": "duration", "type": "int", "default": 5}],
        "known_gotchas": ["avoid 2.35:1"],
    }


def _record(pid: str, model_id: str, output_type: str):
    return srv.aurora_record_platform_research(
        project_id=pid, model_id=model_id, output_type=output_type,
        syntax_dossier=_dossier(model_id, output_type), sources=_sources(3), ttl_days=30,
    )


# === Base: request / record / build =========================================
def test_request_research_returns_brief_with_3_source_queries(server_db):
    pid = srv.aurora_create_project("x", "video_multishot", "perf")["project_id"]
    out = srv.aurora_request_platform_research(
        project_id=pid, model_id="cinematic_studio_3_0", output_type="video_multishot")
    assert out["ok"] and out["cached"] is False
    brief = out["research_brief"]
    assert set(brief["queries_per_source"].keys()) == {
        "official_docs", "mcp_introspection", "community_forums"}
    assert brief["required_sources_min"] == 3


def test_request_research_returns_cached_when_fresh(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    _record(pid, "veo", "video_simple")
    out = srv.aurora_request_platform_research(
        project_id=pid, model_id="veo", output_type="video_simple")
    assert out["ok"] and out["cached"] is True
    assert out["syntax_dossier"]["model_id"] == "veo"


def test_request_research_requires_project_id(server_db):
    out = srv.aurora_request_platform_research(
        project_id="", model_id="veo", output_type="video_simple")
    assert out["ok"] is False
    assert "project_id required" in out["error"]


def test_record_research_rejects_missing_source_types(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    out = srv.aurora_record_platform_research(
        project_id=pid, model_id="kling_3_0", output_type="video_simple",
        syntax_dossier=_dossier("kling_3_0", "video_simple"),
        sources=_sources(1),  # only official_docs
    )
    assert out["ok"] is False
    assert "missing" in out["error"]
    assert "mcp_introspection" in out["error"]


def test_record_research_persists_with_ttl_and_confidence(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    out = _record(pid, "veo", "video_simple")
    assert out["ok"]
    assert out["confidence"] >= 1.0  # 3 source types + 3 quotes -> capped 1.0
    cached = db.get_latest_syntax_dossier("veo", "video_simple", db_path=str(server_db))
    assert cached and cached["syntax_dossier"]["model_id"] == "veo"


def test_record_research_rejects_dossier_missing_fields(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    out = srv.aurora_record_platform_research(
        project_id=pid, model_id="veo", output_type="video_simple",
        syntax_dossier={"model_id": "veo"},  # missing required fields
        sources=_sources(3),
    )
    assert out["ok"] is False
    assert "dossier missing fields" in out["error"]


def test_build_prompt_blocks_without_dossier(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    out = srv.aurora_build_prompt(
        project_id=pid, model_id="never_researched", output_type="video_simple",
        shot_or_element_data={"subject": "x", "action": "y"})
    assert out["ok"] is False
    assert "research required" in out["error"].lower()
    assert out["next_call"]["tool"] == "aurora_request_platform_research"


def test_build_prompt_requires_valid_output_type(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    out = srv.aurora_build_prompt(
        project_id=pid, model_id="veo", output_type="bogus",
        shot_or_element_data={})
    assert out["ok"] is False
    assert "invalid output_type" in out["error"]


def test_build_prompt_uses_cached_dossier_with_injection(server_db):
    pid = srv.aurora_create_project("x", "video_multishot", "perf")["project_id"]
    _record(pid, "cinematic_studio_3_0", "video_multishot")
    out = srv.aurora_build_prompt(
        project_id=pid, model_id="cinematic_studio_3_0", output_type="video_multishot",
        shot_or_element_data={"subject": "@cellist", "look": "warm chiaroscuro",
                              "action": "play", "camera": {"focal_mm": 50}},
        continuity_strategy={"case_type": "continuity_from_previous",
                             "previous_clip_ref": "shot-1-clip"})
    assert out["ok"]
    assert "@cellist" in out["prompt_final"]
    assert "warm chiaroscuro" in out["prompt_final"]
    assert out["injection_instructions"]["method"] == "media_role_start_image"
    assert out["injection_instructions"]["previous_clip_ref"] == "shot-1-clip"


# === Gate (pure) ============================================================
def test_gate_blocks_when_model_unresearched():
    ctx = {"mode": "video_multishot", "research_coverage": {
        "cinematic_studio_3_0": {"output_type": "video_multishot",
                                 "present": False, "expired": False}}}
    res = gate.check(ctx)
    assert res.passed is False
    assert "aurora_request_platform_research" in " ".join(res.reasons)


def test_gate_blocks_when_dossier_expired():
    ctx = {"mode": "video_simple", "research_coverage": {
        "veo": {"output_type": "video_simple", "present": True, "expired": True}}}
    res = gate.check(ctx)
    assert res.passed is False
    assert "expired" in " ".join(res.reasons)


def test_gate_blocks_when_no_model_declared():
    res = gate.check({"mode": "video_multishot", "research_coverage": {}})
    assert res.passed is False
    assert "no model declared" in " ".join(res.reasons)


def test_gate_passes_when_all_researched():
    ctx = {"mode": "video_multishot", "research_coverage": {
        "cinematic_studio_3_0": {"output_type": "video_multishot",
                                 "present": True, "expired": False}}}
    res = gate.check(ctx)
    assert res.passed is True


# === Emit integration =======================================================
def _video_packet() -> dict:
    return {
        "idea": "x", "script": {"beats": ["a"]},
        "shot_list": [{"shot_number": 1, "duration_seconds": 5, "shot_type": "wide",
                       "function": "establish"}],
        "characters": [{"name": "c", "soul_id": "elem-c"}],
        "location": {"name": "hall"}, "props_or_product": [{"name": "violin"}],
        "visual_style": "warm", "biomechanical_plan": [{"shot_number": 1}],
        "ff_lf_strategy": "simple_start", "recommended_model": "cinematic_studio_3_0",
        "ui_or_mcp_route": "mcp", "success_criteria": ["looks good"],
    }


def test_emit_blocks_on_missing_research(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    srv.aurora_validate_preproduction_packet(packet=_video_packet(), project_id=pid)
    emit = srv.aurora_emit_execution_pack(pid)
    blocking = [g["name"] for g in emit["gate_evaluation"]["blocking_gates"]]
    assert "gate_platform_syntax_researched" in blocking


def test_emit_research_gate_clears_after_recording(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    srv.aurora_validate_preproduction_packet(packet=_video_packet(), project_id=pid)
    _record(pid, "cinematic_studio_3_0", "video_simple")
    emit = srv.aurora_emit_execution_pack(pid)
    blocking = [g["name"] for g in emit["gate_evaluation"]["blocking_gates"]]
    assert "gate_platform_syntax_researched" not in blocking


def test_emit_research_gate_is_bypassable(server_db):
    pid = srv.aurora_create_project("x", "video_simple", "perf")["project_id"]
    srv.aurora_validate_preproduction_packet(packet=_video_packet(), project_id=pid)
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_platform_syntax_researched - know it",
        component="gate_platform_syntax_researched", reason="operator knows syntax",
        scope="persist")
    assert res["ok"]
    emit = srv.aurora_emit_execution_pack(pid)
    bypassed = [g["name"] for g in emit["gate_evaluation"]["bypassed_gates"]]
    assert "gate_platform_syntax_researched" in bypassed


# === Pipeline A (image) =====================================================
def test_request_research_for_image_genesis(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    out = srv.aurora_request_platform_research(
        project_id=pid, model_id="soul_cinematic", output_type="image_genesis")
    assert out["ok"]
    assert out["research_brief"]["output_type"] == "image_genesis"
    docs = out["research_brief"]["queries_per_source"]["official_docs"]
    assert any("genesis" in q.lower() or "still" in q.lower() for q in docs)


def test_request_research_for_image_anchor(server_db):
    pid = srv.aurora_create_project("x", "image", "image_anchor")["project_id"]
    out = srv.aurora_request_platform_research(
        project_id=pid, model_id="soul_cast", output_type="image_anchor")
    assert out["ok"]
    assert out["research_brief"]["output_type"] == "image_anchor"


def test_build_prompt_for_image_has_no_continuity(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    _record(pid, "soul_cinematic", "image_genesis")
    out = srv.aurora_build_prompt(
        project_id=pid, model_id="soul_cinematic", output_type="image_genesis",
        shot_or_element_data={"subject": "cellist seated", "look": "chiaroscuro",
                              "format": {"aspect_ratio": "1:1"}})
    assert out["ok"]
    assert "cellist seated" in out["prompt_final"]
    assert out["mcp_payload"] or out["ui_steps"]
    assert not out.get("injection_instructions")  # image is never multishot


def test_gate_blocks_image_mode_without_research(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    db.insert_element(
        project_id=pid, element_type="character", name="hero",
        sheet={"model_id": "soul_cinematic"}, db_path=str(server_db))
    emit = srv.aurora_emit_execution_pack(pid)
    blocking = [g["name"] for g in emit["gate_evaluation"]["blocking_gates"]]
    assert "gate_platform_syntax_researched" in blocking


def test_propose_image_generation_includes_research_status(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    out = srv.aurora_propose_image_generation(
        project_id=pid, element_brief={"image_type": "genesis", "subject": "x"})
    assert "research_status" in out["proposal"]
    selected = out["proposal"]["selected_route"]["model_id"]
    assert selected in out["proposal"]["research_status"]
    assert "cached" in out["proposal"]["research_status"][selected]

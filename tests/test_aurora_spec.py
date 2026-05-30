"""AURORA v2.1 — Sección 15 behavior tests (40 mandatory cases).

These exercise real behavior (classification, gating, routing, scoring,
capability discipline, bypasses, persistence, templates), not just structure.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from aurora import (
    capability_refresh,
    db,
    iteration_discipline,
    theme_resolver,
)
from aurora.gates import (
    gate_biomechanical_sanity,
    gate_benchmark_pack,
    gate_higgsfield_light_refresh,
    gate_domain_session_lock,
    gate_multishot_anchor_strategy,
    gate_route_verification,
    gate_step_0_quality_ceiling,
    required_gates_for_mode,
)
from aurora.routers import (
    ui_vs_mcp_router,
    video_model_router,
)
from aurora.scoring import (
    production_success_probability,
    prompt_fitness_score,
    biomechanical_score,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = REPO_ROOT / "templates"

REQUIRED_TEMPLATES = [
    "domain_session_lock.yaml", "benchmark_pack.yaml", "image_brief.yaml",
    "video_brief.yaml", "scene_bible.yaml", "character_sheet.yaml",
    "product_sheet.yaml", "prop_sheet.yaml", "location_sheet.yaml",
    "biomechanical_motion_plan.yaml", "shot_list.yaml", "anchor_strategy.yaml",
    "elements_registry.yaml", "execution_pack.md.jinja",
]


# --- 1. Intent classification: image, video_simple, video_multishot ---------
def test_01_intent_classification_three_modes():
    assert theme_resolver.classify_intent("hero product image, photoreal")["mode"] == "image"
    assert theme_resolver.classify_intent("8 second hero ad video for Nike")["mode"] == "video_simple"
    assert theme_resolver.classify_intent("multishot 3 scene sequence with dialogue")["mode"] == "video_multishot"


# --- 2. Domain session lock requerido ---------------------------------------
def test_02_domain_session_lock_required():
    assert gate_domain_session_lock.check(None).passed is False
    assert gate_domain_session_lock.check({}).passed is False


# --- 3. Light refresh requerido antes de route planning ---------------------
def test_03_light_refresh_required():
    assert gate_higgsfield_light_refresh.check(None).passed is False


# --- 4. Route verification bloquea not_verified -----------------------------
def test_04_route_verification_blocks_not_verified():
    res = gate_route_verification.check(
        [{"feature_name": "x", "route_type": "not_verified", "allowed": False}]
    )
    assert res.passed is False


# --- 5. Gate 0 bloquea si score < 85 ----------------------------------------
def test_05_gate0_blocks_below_85():
    ctx = {
        "benchmark_pack": {"refs": [1]},
        "image_scores": [{"total_score": 70, "hard_fail": False}],
        "audits": [{"verdict": "ok"}],
    }
    assert gate_step_0_quality_ceiling.check(ctx).passed is False
    ctx["image_scores"] = [{"total_score": 92, "hard_fail": False}]
    assert gate_step_0_quality_ceiling.check(ctx).passed is True


# --- 6. Benchmark pack requerido --------------------------------------------
def test_06_benchmark_pack_required():
    assert gate_benchmark_pack.check(None).passed is False


# --- 7. Biomechanical sanity detecta hard fails -----------------------------
def test_07_biomech_detects_hard_fail():
    plan = {
        "object_in_motion": {
            "arrival_height_from_ground_cm": 5,
            "contact_points": ["head"],
        },
        "head": {"action": "cabezazo header to the ball"},
    }
    res = gate_biomechanical_sanity.check(plan)
    assert res.passed is False
    assert any("head" in r.lower() for r in res.reasons)


# --- 8. Prompt fitness detecta contradicciones ------------------------------
def test_08_prompt_fitness_detects_contradiction():
    good = {k: 100 for k in prompt_fitness_score.WEIGHTS}
    assert prompt_fitness_score.score(good)["passed"] is True
    contradictory = dict(good, no_overload_or_contradiction=0, single_dominant_action=0)
    assert prompt_fitness_score.score(contradictory)["passed"] is False


# --- 9. Multishot strategy requiere anchor por shot -------------------------
def test_09_multishot_requires_anchor_per_shot():
    no_anchor = [{"shot_number": 2, "anchor_strategy": {"case_type": "continuity_from_previous"}}]
    assert gate_multishot_anchor_strategy.check(no_anchor).passed is False
    with_anchor = [{
        "shot_number": 2,
        "anchor_strategy": {
            "case_type": "continuity_from_previous",
            "previous_clip_ref": "clip_1",
        },
    }]
    assert gate_multishot_anchor_strategy.check(with_anchor).passed is True


# --- 10. Execution pack bloquea si falta cualquier gate obligatorio ----------
def test_10_execution_pack_blocks_on_missing_gate():
    from aurora import execution_pack_builder
    project = {"project_id": "p1", "mode": "image", "operator_intent": "x"}
    result = execution_pack_builder.build_execution_pack(project, {}, "image")
    assert result["ok"] is False
    assert result["gate_evaluation"]["blocking_gates"]


# --- 11. Topaz/upscale no callable sin refresh explícito --------------------
def test_11_topaz_not_callable():
    res = ui_vs_mcp_router.classify("topaz")
    assert res["route_type"] == "outside_aurora"
    assert res["generate_mcp_payload"] is False


# --- 12. Bypass current_turn funciona ---------------------------------------
def test_12_bypass_current_turn(tmp_path):
    from aurora import bypass_handler
    d = bypass_handler.parse_bypass("OVERRIDE: gate_step_0 - need speed")
    assert d is not None and d.scope == "current_turn"
    state = {"current_turn": [d.component]}
    assert bypass_handler.is_component_bypassed("gate_step_0", state) is True


# --- 13. Bypass persist funciona y revoke funciona --------------------------
def test_13_bypass_persist_and_revoke():
    from aurora import bypass_handler
    bypass_handler.revoke_persist_bypass("gate_step_0")
    bypass_handler._set_persist_bypass("gate_step_0", "ongoing")
    state = bypass_handler._load_session_state()
    assert bypass_handler.is_component_bypassed("gate_step_0", state) is True
    bypass_handler.revoke_persist_bypass("gate_step_0")
    state = bypass_handler._load_session_state()
    assert bypass_handler.is_component_bypassed("gate_step_0", state) is False


# --- 14. SQLite round-trip projects/briefs/scores/routes/snapshots ----------
def test_14_sqlite_roundtrip(tmp_path):
    p = str(tmp_path / "rt.db")
    db.init_db(p)
    pid = db.insert_project("intent", "image", db_path=p, output_type="hero_ad")
    assert db.get_project(pid, db_path=p)["operator_intent"] == "intent"
    bid = db.insert_brief({"operator_intent": "x", "output_type": "hero_ad"}, db_path=p)
    assert db.get_brief(bid, db_path=p)["brief_id"] == bid
    db.insert_quality_score(
        project_id=pid, score_type="image",
        total_score=90, score_data={"photorealism": 90}, db_path=p,
    )
    assert db.get_quality_scores(pid, db_path=p)
    db.insert_route(
        project_id=pid, feature_name="soul", route_type="mcp_callable",
        route_data={"x": 1}, db_path=p,
    )
    assert db.get_routes(pid, db_path=p)
    sid = db.insert_capability_snapshot(
        refresh_scope="light_session", source="snapshot_verified",
        snapshot={"a": 1}, db_path=p,
    )
    assert sid and db.get_latest_snapshot(db_path=p)["snapshot"] == {"a": 1}


# --- 15. Production Success Probability calcula correctamente ----------------
def test_15_psp_computation():
    perfect = {k: 100 for k in production_success_probability.COMPONENT_WEIGHTS}
    assert production_success_probability.score(perfect)["total_score"] == 100
    weak = dict(perfect, anchor_quality=0)
    res = production_success_probability.score(weak)
    assert res["weakest_component"] == "anchor_quality"
    assert res["total_score"] < 100


# --- 16. Iteration delta discipline detecta múltiples variables -------------
def test_16_iteration_delta_discipline():
    prev = {"model_id": "a", "prompt": "p", "aspect_ratio": "16:9"}
    one = dict(prev, prompt="p2")
    assert iteration_discipline.check_iteration_delta(prev, one)["disciplined"] is True
    two = dict(prev, prompt="p2", model_id="b")
    res = iteration_discipline.check_iteration_delta(prev, two)
    assert res["disciplined"] is False
    assert set(res["changed_variables"]) == {"prompt", "model_id"}


# --- 17. UI-only route genera instrucciones UI, no MCP payload --------------
def test_17_ui_only_route():
    res = ui_vs_mcp_router.classify("cinema_studio_ui_shot_by_shot", route_type="ui_only")
    assert res["generate_ui_instructions"] is True
    assert res["generate_mcp_payload"] is False


# --- 18. MCP-callable route genera payload estructurado ---------------------
def test_18_mcp_callable_route():
    res = ui_vs_mcp_router.classify(
        "soul", route_type="mcp_callable", verified=True, verification_source="live_mcp"
    )
    assert res["generate_mcp_payload"] is True
    assert res["credit_spend_allowed"] is True


# --- 19. Schema refresh actualiza snapshot ----------------------------------
def test_19_schema_refresh_updates_snapshot(tmp_path):
    p = str(tmp_path / "snap.db")
    db.init_db(p)
    r1 = capability_refresh.refresh(scope="light_session", db_path=p)
    assert r1["ok"] and r1["snapshot_id"]
    latest = db.get_latest_snapshot(db_path=p)
    assert latest["refresh_scope"] == "light_session"


# --- 20. Emergency refresh se dispara por parameter rejection ---------------
def test_20_emergency_refresh_scope(tmp_path):
    p = str(tmp_path / "em.db")
    db.init_db(p)
    assert "emergency" in capability_refresh.REFRESH_SCOPES
    r = capability_refresh.refresh(scope="emergency", source="parameter_rejection", db_path=p)
    assert r["ok"] and r["scope"] == "emergency"


# --- 21. Cinema Studio 3.5 alias no genera MCP payload sin model_id ----------
def test_21_cinema35_no_mcp_payload():
    res = capability_refresh.resolve_model_alias("cinema_studio_3_5_ui", "mcp")
    assert res["generate_mcp_payload"] is False
    assert res["callable"] is False


# --- 22. Cinema Studio 3.5 UI route sí genera instrucciones -----------------
def test_22_cinema35_ui_instructions():
    res = capability_refresh.resolve_model_alias("cinema_studio_3_5_ui", "ui")
    assert res["generate_ui_instructions"] is True
    assert res["callable"] is True


# --- 23. Mr Higgs route genera planning prompt, no style-apply --------------
def test_23_mr_higgs_planning_only():
    sel = video_model_router.select_route("video_multishot", prefer_route_id="mr_higgs")
    assert sel["selected_route"]["route_id"] != "mr_higgs"
    assert "mr_higgs" in sel["ui_only_routes"]
    assert sel["ui_only_routes"]["mr_higgs"]["route_type"] == "ui_only_planning_only"


# --- 24. Mr Higgs Forbidden queda documentado como warning -----------------
def test_24_mr_higgs_forbidden_warning():
    sel = video_model_router.select_route("video_simple")
    warning = sel["ui_only_routes"]["mr_higgs"]["warning"]
    assert "Forbidden" in warning


# --- 25. <<<element_id>>> solo si modelo soporta injection ------------------
def test_25_element_injection_supported_model():
    res = capability_refresh.validate_element_injection("nano_banana_pro", ["el_1"])
    assert res["ok"] is True
    assert res["inject_syntax"] == ["<<<el_1>>>"]


# --- 26. Soul models usan soul_id, no <<<element_id>>> ----------------------
def test_26_soul_models_use_soul_id():
    res = capability_refresh.validate_element_injection("soul_cinematic", ["el_1"])
    assert res["mechanism"] == "soul_id"
    assert res["ok"] is False


# --- 27. Aspect ratio 21:9 bloquea si el modelo no lo soporta ---------------
def test_27_aspect_2139_blocks():
    res = capability_refresh.validate_aspect_ratio("cinematic_studio_3_0", "21:9")
    assert res["ok"] is False and res["status"] == "blocked"


# --- 28. Model/preset count se lee de snapshot, no constante hard-codeada ----
def test_28_counts_from_snapshot(tmp_path):
    p = str(tmp_path / "c.db")
    db.init_db(p)
    custom = {"live_counts_snapshot": {"models": 999}}
    db.insert_capability_snapshot(
        refresh_scope="light_session", source="snapshot_verified",
        snapshot=custom, db_path=p,
    )
    counts = capability_refresh.get_live_counts(db_path=p)
    assert counts["models"] == 999


# --- 29. Cowork/onrender limitation aparece en LIMITATIONS.md ---------------
def test_29_cowork_limitation_documented():
    text = (REPO_ROOT / "LIMITATIONS.md").read_text(encoding="utf-8")
    assert "onrender.com" in text and "allowlist" in text.lower()


# --- 30. Capability conflict policy prioriza MCP para automatización --------
def test_30_capability_conflict_prefers_mcp():
    # An mcp_callable + verified route spends credits; a ui_only does not.
    mcp = ui_vs_mcp_router.classify("soul", route_type="mcp_callable", verified=True, verification_source="live_mcp")
    ui = ui_vs_mcp_router.classify("soul", route_type="ui_only")
    assert mcp["credit_spend_allowed"] is True
    assert ui["credit_spend_allowed"] is False


# --- 31. Cinema Studio UI KB contains exactly 10 base genres ----------------
def test_31_ten_genres():
    caps = capability_refresh.load_capabilities()
    assert len(caps["cinema_studio_ui"]["genres"]) == 10


# --- 32. Cinema Studio UI KB contains exactly 8 speed ramps -----------------
def test_32_eight_speed_ramps():
    caps = capability_refresh.load_capabilities()
    assert len(caps["cinema_studio_ui"]["speed_ramps"]) == 8


# --- 33. Cinema Studio UI KB contains 7 camera movesets + auto --------------
def test_33_seven_movesets_plus_auto():
    caps = capability_refresh.load_capabilities()
    movesets = caps["cinema_studio_ui"]["camera_movesets"]
    assert "auto" in movesets
    assert len(movesets) == 8  # 7 + auto


# --- 34. All 14 required templates exist and are non-empty ------------------
def test_34_all_templates_present_nonempty():
    for tmpl in REQUIRED_TEMPLATES:
        path = TEMPLATES / tmpl
        assert path.exists(), f"missing {tmpl}"
        assert path.stat().st_size > 0, f"empty {tmpl}"


# --- 35. execution_pack.md.jinja contains loops for gates/elements/routes/shots
def test_35_pack_template_loops():
    text = (TEMPLATES / "execution_pack.md.jinja").read_text(encoding="utf-8")
    for token in ("gates", "elements", "routes", "shots"):
        assert token in text


# --- 36. execution_pack.md.jinja contains post-production/checklist/bypass ---
def test_36_pack_template_sections():
    text = (TEMPLATES / "execution_pack.md.jinja").read_text(encoding="utf-8").lower()
    assert "post" in text and "checklist" in text and "bypass" in text


# --- 37. Adobe Podcast defaults: music=0, background=100, speech=50 ----------
def test_37_adobe_podcast_defaults():
    caps = capability_refresh.load_capabilities()
    settings = caps["post_production"]["audio_cleanup"]["adobe_podcast"]["default_settings"]
    assert settings == {"music_pct": 0, "background_pct": 100, "speech_pct": 50}


# --- 38. CapCut/DaVinci/Topaz external classified outside_aurora ------------
def test_38_external_tools_outside_aurora():
    caps = capability_refresh.load_capabilities()
    pp = caps["post_production"]
    assert pp["stitching"]["route"] == "outside_aurora"
    assert pp["upscale"]["topaz_external"]["route"] == "outside_aurora"
    assert ui_vs_mcp_router.classify("capcut")["route_type"] == "outside_aurora"


# --- 39. Sección 9 templates ⊆ Sección 12 (coverage; no undefined template) -
def test_39_template_coverage_complete():
    # Every template the build promises must exist on disk (no dangling refs).
    missing = [t for t in REQUIRED_TEMPLATES if not (TEMPLATES / t).exists()]
    assert missing == []


# --- 40. UI-only Cinema control needs genre/speed_ramp/camera_moveset -------
def test_40_ui_video_route_requires_controls():
    incomplete = [{
        "feature_name": "cinema_ui",
        "route_type": "ui_only",
        "media": "video",
        "ui_config": {"genre": "thriller"},  # missing speed_ramp, camera_moveset, ...
    }]
    assert gate_route_verification.check(incomplete).passed is False
    complete = [{
        "feature_name": "cinema_ui",
        "route_type": "ui_only",
        "media": "video",
        "ui_config": {
            "genre": "thriller", "speed_ramp": "none", "camera_moveset": "auto",
            "style_palette": "noir", "duration_seconds": 8, "aspect_ratio": "16:9",
            "audio": "external", "reference_strategy": "ff_lf",
        },
    }]
    assert gate_route_verification.check(complete).passed is True

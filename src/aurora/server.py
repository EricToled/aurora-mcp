"""AURORA MCP server (v2.1 FINAL).

Exposes the 24 AURORA tools (Sección 10) plus the 4 originally-deployed Sprint 1
tools, which keep working unchanged so the live Render instance is not broken.

AURORA never generates media. It disciplines, plans, audits and emits the
Execution Pack; the real generation runs in Higgsfield via Claude Desktop.

Two transports — same deterministic behavior:

  Local (stdio):   python -m aurora.server
  Remote (HTTP):   python -m aurora.server --http     (or set AURORA_HTTP=1)
  Self-test:       python -m aurora.server --selftest
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from . import (
    bypass_handler,
    capability_refresh,
    db,
    execution_pack_builder,
    theme_resolver,
)
from .gates import (
    gate_anchors_audited,
    gate_biomechanical_sanity,
    gate_multishot_anchor_strategy,
    gate_preproduction_packet,
    gate_prompt_fitness,
    gate_route_verification,
    gate_step_0_quality_ceiling,
)
from .models import VideoBrief
from .routers import (
    image_model_router,
    internal_route_bakeoff,
    ui_vs_mcp_router,
    video_model_router,
)
from .scoring import (
    advertising_quality_score,
    biomechanical_score,
    expected_criteria_for,
    multishot_continuity_score,
    production_success_probability,
    prompt_fitness_score,
    video_quality_score,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get("AURORA_DB_PATH", str(REPO_ROOT / "aurora.db")))

_HTTP_HOST = os.environ.get("AURORA_HOST", "0.0.0.0")
_HTTP_PORT = int(os.environ.get("PORT", os.environ.get("AURORA_PORT", "8000")))

mcp = FastMCP("aurora", host=_HTTP_HOST, port=_HTTP_PORT)

# score_type -> scorer module (each exposes score(data) -> dict).
_SCORERS = {
    # descriptive aliases
    "advertising_image_quality": advertising_quality_score,
    "advertising_quality": advertising_quality_score,
    "video_quality": video_quality_score,
    "multishot_continuity": multishot_continuity_score,
    "biomechanical": biomechanical_score,
    "prompt_fitness": prompt_fitness_score,
    "production_success_probability": production_success_probability,
    # canonical score_type names (must match the quality_scores CHECK)
    "image": advertising_quality_score,
    "video": video_quality_score,
    "multishot": multishot_continuity_score,
    "biomechanics": biomechanical_score,
    "prompt": prompt_fitness_score,
    "production_probability": production_success_probability,
}

# Every accepted score_type maps to the canonical value the DB CHECK allows:
# quality_scores.score_type IN ('image','video','multishot','biomechanics',
# 'prompt','production_probability'). The public tool API accepts either the
# descriptive alias or the canonical name, but we always persist the canonical
# one so the CHECK constraint (and downstream gate reads) stay consistent.
_SCORE_TYPE_CANON = {
    "advertising_image_quality": "image",
    "advertising_quality": "image",
    "image": "image",
    "video_quality": "video",
    "video": "video",
    "multishot_continuity": "multishot",
    "multishot": "multishot",
    "biomechanical": "biomechanics",
    "biomechanics": "biomechanics",
    "prompt_fitness": "prompt",
    "prompt": "prompt",
    "production_success_probability": "production_probability",
    "production_probability": "production_probability",
}


def _ensure_db() -> None:
    # Idempotent: schema uses CREATE TABLE IF NOT EXISTS, so this both
    # creates a fresh DB and adds any new tables to an already-deployed one.
    db.init_db(DB_PATH)


def _db() -> str:
    return str(DB_PATH)


# ===========================================================================
# 1. Intent + capability refresh
# ===========================================================================
@mcp.tool()
def aurora_classify_intent(text: str) -> dict[str, Any]:
    """Classify operator intent into mode + output type + style."""
    return theme_resolver.classify_intent(text)


@mcp.tool()
def aurora_refresh_higgsfield_capabilities(
    scope: str = "light_session",
    project_id: Optional[str] = None,
    target_models: Optional[list[str]] = None,
    target_features: Optional[list[str]] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Record a Higgsfield capability snapshot (Sección 5). Never produces live
    MCP results — it snapshots what AURORA currently knows so the freshness gate
    can verify it. Returns {snapshot_id, scope, capabilities, diff}."""
    _ensure_db()
    return capability_refresh.refresh(
        scope=scope,
        db_path=_db(),
        target_models=target_models,
        target_features=target_features,
        force=force,
    )


# ===========================================================================
# 2. Project + locks + briefs
# ===========================================================================
@mcp.tool()
def aurora_create_project(
    operator_intent: str, mode: str, output_type: str
) -> dict[str, Any]:
    """Create a project. mode in {image, video_simple, video_multishot}."""
    _ensure_db()
    pid = db.insert_project(
        operator_intent=operator_intent,
        mode=mode,
        output_type=output_type,
        current_phase="created",
        db_path=_db(),
    )
    return {"ok": True, "project_id": pid, "mode": mode, "output_type": output_type}


@mcp.tool()
def aurora_create_domain_session_lock(
    project_id: str, lock_data: dict[str, Any]
) -> dict[str, Any]:
    """Persist the Domain Session Lock (Sección 4) on the project."""
    _ensure_db()
    domain = (lock_data or {}).get("domain", "")
    sub = (lock_data or {}).get("sub_domain", "")
    if not str(domain).strip() or not str(sub).strip():
        return {"ok": False, "reason": "domain and sub_domain are required"}
    db.update_project(
        project_id,
        db_path=_db(),
        domain_session_lock_json=lock_data,
        current_phase="domain_locked",
    )
    return {"ok": True, "project_id": project_id, "domain": domain, "sub_domain": sub}


@mcp.tool()
def aurora_create_benchmark_pack(
    project_id: str, refs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Register benchmark references (Sección 12.1). At least one is required."""
    _ensure_db()
    if not refs:
        return {"ok": False, "reason": "at least one benchmark reference required"}
    ids = []
    for ref in refs:
        url = ref.get("url_or_path", "")
        if not str(url).strip():
            return {"ok": False, "reason": "each reference needs a url_or_path"}
        ids.append(
            db.insert_benchmark_ref(
                project_id=project_id,
                url_or_path=url,
                visual_traits=ref.get("visual_traits", {}),
                db_path=_db(),
            )
        )
    return {"ok": True, "project_id": project_id, "benchmark_ids": ids}


@mcp.tool()
def aurora_create_brief(
    project_id: str, brief_type: str, brief_data: dict[str, Any]
) -> dict[str, Any]:
    """Persist an image or video brief (Sección 12.2 / 12.6)."""
    _ensure_db()
    data = dict(brief_data or {})
    data.setdefault("project_id", project_id)
    brief_id = db.insert_brief(data, project_id=project_id, brief_type=brief_type, db_path=_db())
    return {"ok": True, "brief_id": brief_id, "brief_type": brief_type}


# ----- deployed Sprint 1 tool (kept working, not in the v2.1 list) -----------
@mcp.tool()
def aurora_create_video_brief(brief_data: dict[str, Any]) -> dict[str, Any]:
    """Validate a video brief against the template and persist it (deployed)."""
    _ensure_db()
    try:
        brief = VideoBrief(**brief_data)
    except ValidationError as exc:
        return {"ok": False, "errors": exc.errors(include_url=False)}
    brief_id = db.insert_brief(brief.model_dump(mode="json"), db_path=_db())
    return {"ok": True, "brief_id": brief_id}


@mcp.tool()
def aurora_validate_preproduction_packet(
    packet: dict[str, Any], project_id: Optional[str] = None
) -> dict[str, Any]:
    """Run the 'regla inviolable' gate over a preproduction packet (Sección 7).
    Reporting only — does not block. Persists the packet when project_id given."""
    result = gate_preproduction_packet.validate_packet(packet or {})
    if project_id:
        _ensure_db()
        db.put_artifact(project_id, "preproduction_packet", packet or {}, db_path=_db())
    return result.model_dump()


# ===========================================================================
# 3. Route verification
# ===========================================================================
@mcp.tool()
def aurora_verify_route(
    project_id: str, feature_name: str, route_data: dict[str, Any]
) -> dict[str, Any]:
    """Classify + persist a route for a feature (Sección 7.4 / 5B). Decides MCP
    payload vs UI instructions and records it in the route registry."""
    _ensure_db()
    decision = ui_vs_mcp_router.classify(
        feature_name,
        route_type=route_data.get("route_type"),
        verified=bool(route_data.get("verified") or route_data.get("verified_connector")),
        verification_source=route_data.get("verification_source"),
    )
    db.insert_route(
        project_id=project_id,
        feature_name=feature_name,
        route_type=decision["route_type"],
        route_data={**route_data, **decision},
        verification_source=route_data.get("verification_source"),
        confidence=float(route_data.get("confidence", 0.0)),
        db_path=_db(),
    )
    return {"ok": True, "project_id": project_id, "decision": decision}


# ===========================================================================
# 4. Proposal tools (route selection — never generates media)
# ===========================================================================
@mcp.tool()
def aurora_propose_image_generation(
    project_id: str, element_brief: dict[str, Any]
) -> dict[str, Any]:
    """Propose a registered image route + injection plan (Sección 6.1). Returns
    instructions; it never spends credits or calls Higgsfield."""
    _ensure_db()
    image_type = element_brief.get("image_type", "genesis")
    aspect = (element_brief.get("format") or {}).get("aspect_ratio")
    element_ids = (element_brief.get("reference_strategy") or {}).get("element_ids") or []
    selection = image_model_router.select_route(image_type, aspect_ratio=aspect, element_ids=element_ids)
    return {"ok": selection["ok"], "project_id": project_id, "proposal": selection}


@mcp.tool()
def aurora_propose_video_execution(
    project_id: str, video_packet: dict[str, Any]
) -> dict[str, Any]:
    """Propose a registered video route + bakeoff (Sección 6.3/6.4). Mr Higgs is
    never returned as executable. Persists any finishing block for the pack."""
    _ensure_db()
    project = db.get_project(project_id, db_path=_db()) or {}
    mode = video_packet.get("mode") or project.get("mode") or "video_simple"
    aspect = video_packet.get("aspect_ratio")
    selection = video_model_router.select_route(mode, aspect_ratio=aspect)
    if video_packet.get("finishing"):
        db.put_artifact(project_id, "finishing", video_packet["finishing"], db_path=_db())
    return {"ok": selection["ok"], "project_id": project_id, "proposal": selection}


# ===========================================================================
# 5. Elements + audits + scores
# ===========================================================================
@mcp.tool()
def aurora_record_required_elements(
    project_id: str, higgsfield_element_ids: list[str]
) -> dict[str, Any]:
    """Record the Higgsfield Element IDs the project requires (Sección 5B.5)."""
    _ensure_db()
    db.update_project(
        project_id,
        db_path=_db(),
        required_higgsfield_element_ids=list(higgsfield_element_ids or []),
    )
    return {
        "ok": True,
        "project_id": project_id,
        "required_count": len(higgsfield_element_ids or []),
    }


@mcp.tool()
def aurora_record_audit(
    project_id: str,
    criterion: str,
    verdict: str,
    notes: str = "",
    audited_by: str = "aurora",
    higgsfield_job_id: Optional[str] = None,
    higgsfield_element_id: Optional[str] = None,
) -> dict[str, Any]:
    """Record a visual audit verdict (Sección 7.2)."""
    _ensure_db()
    audit_id = db.insert_audit(
        project_id=project_id,
        criterion=criterion,
        verdict=verdict,
        notes=notes,
        audited_by=audited_by,
        higgsfield_job_id=higgsfield_job_id,
        higgsfield_element_id=higgsfield_element_id,
        db_path=_db(),
    )
    return {"ok": True, "audit_id": audit_id}


@mcp.tool()
def aurora_record_quality_score(
    project_id: str,
    score_type: str,
    score_data: dict[str, Any],
    higgsfield_job_id: Optional[str] = None,
    higgsfield_element_id: Optional[str] = None,
) -> dict[str, Any]:
    """Compute + persist a quality score (Sección 3). score_data holds the
    per-criterion values; AURORA computes the weighted total."""
    _ensure_db()
    scorer = _SCORERS.get(score_type)
    if scorer is None:
        return {"ok": False, "reason": f"unknown score_type: {score_type}"}
    result = scorer.score(score_data)
    if result.get("recognized_criteria", 1) == 0:
        return {
            "ok": False,
            "reason": (
                f"score_data for '{score_type}' contained none of the expected "
                f"per-criterion keys (each 0-100). Got keys "
                f"{sorted(score_data.keys())}."
            ),
            "expected_criteria": result.get("expected_criteria", []),
        }
    canon = _SCORE_TYPE_CANON.get(score_type, score_type)
    db.insert_quality_score(
        project_id=project_id,
        score_type=canon,
        score_data={**score_data, **result},
        total_score=int(result["total_score"]),
        hard_fail_reason=result.get("hard_fail_reason"),
        higgsfield_job_id=higgsfield_job_id,
        higgsfield_element_id=higgsfield_element_id,
        db_path=_db(),
    )
    return {"ok": True, "result": result}


# ===========================================================================
# 6. Gate-check tools
# ===========================================================================
@mcp.tool()
def aurora_check_quality_ceiling(project_id: str) -> dict[str, Any]:
    """Gate 0 — Quality Ceiling (Sección 7.2). Requires benchmark pack + a
    scored Genesis/Anchor image (>=85) + a recorded audit."""
    _ensure_db()
    context = {
        "benchmark_pack": _benchmark_pack(project_id),
        "image_scores": _image_scores(project_id),
        "audits": db.get_audits(project_id, db_path=_db()),
    }
    return gate_step_0_quality_ceiling.check(context).model_dump()


@mcp.tool()
def aurora_validate_biomechanics(
    project_id: str, motion_plan: dict[str, Any]
) -> dict[str, Any]:
    """Validate a biomechanical motion plan for hard fails (Sección 7.3)."""
    _ensure_db()
    db.put_artifact(project_id, "motion_plan", motion_plan or {}, db_path=_db())
    return gate_biomechanical_sanity.check(motion_plan).model_dump()


@mcp.tool()
def aurora_check_prompt_fitness(
    project_id: str, prompt_packet: dict[str, Any]
) -> dict[str, Any]:
    """Check Prompt Fitness (Sección 3.6 / 7.1)."""
    _ensure_db()
    db.put_artifact(project_id, "prompt_packet", prompt_packet or {}, db_path=_db())
    result = gate_prompt_fitness.check(prompt_packet).model_dump()
    # Loud shape guard: prompt_fitness expects per-criterion rubric scores
    # (0-100), NOT raw prompt text. If none are present, say so explicitly so a
    # near-zero score is never mistaken for "the prompt is bad".
    expected = expected_criteria_for(prompt_fitness_score)
    if isinstance(prompt_packet, dict) and not any(k in prompt_packet for k in expected):
        result["input_shape_warning"] = (
            "prompt_packet contained none of the expected rubric keys "
            f"{expected} (each 0-100). The score reflects missing scores, not "
            "prompt quality. Provide per-criterion fitness scores."
        )
    return result


@mcp.tool()
def aurora_check_multishot_strategy(
    project_id: str,
    shot_list: list[dict[str, Any]],
    anchor_strategy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Check multishot anchor strategy (Sección 7.1 / 6.5)."""
    _ensure_db()
    db.put_artifact(project_id, "shot_list", shot_list or [], db_path=_db())
    return gate_multishot_anchor_strategy.check(shot_list).model_dump()


@mcp.tool()
def aurora_check_anchors_ready(project_id: str) -> dict[str, Any]:
    """Check that all required anchors are audited and approved (Sección 7.1)."""
    _ensure_db()
    state = db.get_artifact(project_id, "anchor_state", db_path=_db())
    if not state:
        elements = db.get_elements(project_id, db_path=_db())
        anchors = [e for e in elements if (e.get("usage_role") or "") == "anchor"]
        approved = [e for e in anchors if (e.get("audit_status") or "") == "pass"]
        state = {
            "anchors_required_count": len(anchors),
            "anchors_approved_count": len(approved),
            "anchor_audits": [],
        }
    return gate_anchors_audited.check(state).model_dump()


@mcp.tool()
def aurora_compute_production_success_probability(project_id: str) -> dict[str, Any]:
    """Compute the Production Success Probability (Sección 3.7). Blocks < 85.
    Reads PSP components recorded for the project."""
    _ensure_db()
    components = db.get_artifact(project_id, "psp_components", db_path=_db())
    if not components:
        return {"ok": False, "reason": "no PSP components recorded for project"}
    result = production_success_probability.score(components)
    db.put_artifact(project_id, "psp_result", result, db_path=_db())
    db.insert_quality_score(
        project_id=project_id,
        score_type="production_probability",
        score_data={**components, **result},
        total_score=int(result["total_score"]),
        db_path=_db(),
    )
    return {"ok": True, "result": result}


@mcp.tool()
def aurora_record_psp_components(
    project_id: str, components: dict[str, Any]
) -> dict[str, Any]:
    """Record the 7 PSP components so the probability can be computed later."""
    _ensure_db()
    db.put_artifact(project_id, "psp_components", components or {}, db_path=_db())
    return {"ok": True, "project_id": project_id}


# ===========================================================================
# 7. Execution Pack emission
# ===========================================================================
@mcp.tool()
def aurora_emit_execution_pack(
    project_id: str, elements_with_urls: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    """Emit the Execution Pack (Sección 10/13). BLOCKS unless every required
    gate for the mode passes or has a registered active bypass."""
    _ensure_db()
    project = db.get_project(project_id, db_path=_db())
    if not project:
        return {"ok": False, "reason": f"unknown project: {project_id}"}
    mode = project.get("mode") or "image"
    context = _assemble_context(project_id, project, elements_with_urls or {})
    active = db.get_active_bypasses(db_path=_db())
    project_view = {
        "project_id": project_id,
        "operator_intent": project.get("operator_intent", ""),
        "output_type": project.get("output_type", ""),
        "mode": mode,
    }
    result = execution_pack_builder.build_execution_pack(
        project_view, context, mode, active_bypasses=active
    )
    if result["ok"]:
        anchors = context.get("anchor_state") or {}
        pack_id = db.insert_execution_pack(
            project_id=project_id,
            anchors_approved_count=int(anchors.get("anchors_approved_count", 0)),
            anchors_required_count=int(anchors.get("anchors_required_count", 0)),
            success_criteria=context.get("success_criteria", []),
            db_path=_db(),
        )
        result["pack_id"] = pack_id
        db.update_project(project_id, db_path=_db(), current_phase="execution_pack_emitted")
    return result


# ===========================================================================
# 8. Bypass (deployed) + surface helpers
# ===========================================================================
@mcp.tool()
def aurora_log_bypass(
    operator_text: str,
    component: Optional[str] = None,
    reason: Optional[str] = None,
    scope: Optional[str] = None,
) -> dict[str, Any]:
    """Register an operator bypass directive (Sección K). When component/reason
    are omitted, the directive is parsed from operator_text."""
    _ensure_db()
    if not component or not reason:
        parsed = bypass_handler.parse_bypass(operator_text or "")
        if parsed is None:
            return {"ok": False, "reason": "no bypass directive found in text"}
        component = component or parsed.component
        reason = reason or parsed.reason
        scope = scope or parsed.scope
    if component not in bypass_handler.BYPASSABLE_COMPONENTS:
        return {"ok": False, "reason": f"unknown component: {component}"}
    if not reason or not reason.strip():
        return {"ok": False, "reason": "empty reason rejected"}
    if scope not in ("current_turn", "persist", "all_session"):
        scope = "current_turn"

    # Store under the canonical gate name so the bypass actually takes effect
    # when build_execution_pack evaluates gates by canonical name.
    component = bypass_handler.canonical_component(component)
    directive = bypass_handler.BypassDirective(
        component=component,
        reason=reason,
        scope=scope,  # type: ignore[arg-type]
        detected_in_text=operator_text or f"{component} - {reason}",
    )
    bypass_id = bypass_handler.log_bypass(directive, db_path=_db())
    if scope in ("persist", "all_session"):
        db.set_active_bypass(component, scope, reason, db_path=_db())
    return {"ok": True, "bypass_id": bypass_id, "scope": scope, "component": component}


@mcp.tool()
def aurora_resolve_model_alias(
    alias_name: str, desired_surface: str
) -> dict[str, Any]:
    """Resolve a UI/product alias to callable model_ids for a surface
    (Sección 5B.2/5B.3). desired_surface in {'mcp','ui'}."""
    return capability_refresh.resolve_model_alias(alias_name, desired_surface)


@mcp.tool()
def aurora_validate_element_injection(
    model_id: str, element_ids: list[str]
) -> dict[str, Any]:
    """Decide whether <<<element_id>>> injection is allowed (Sección 5B.5).
    Soul models use soul_id instead."""
    return capability_refresh.validate_element_injection(model_id, element_ids)


@mcp.tool()
def aurora_validate_aspect_ratio(model_id: str, aspect_ratio: str) -> dict[str, Any]:
    """Validate an aspect ratio per model (Sección 5B.7)."""
    return capability_refresh.validate_aspect_ratio(model_id, aspect_ratio)


# ===========================================================================
# Context assembly for the Execution Pack
# ===========================================================================
def _benchmark_pack(project_id: str) -> Optional[dict[str, Any]]:
    refs = db.get_benchmark_refs(project_id, db_path=_db())
    if not refs:
        return None
    return {
        "acceptance_threshold": 85,
        "references": [
            {
                "reference_id": r.get("benchmark_id", ""),
                "url_or_path": r.get("url_or_path", ""),
                "reason": "",
                "visual_traits": r.get("visual_traits", {}),
            }
            for r in refs
        ],
    }


def _image_scores(project_id: str) -> list[dict[str, Any]]:
    rows = db.get_quality_scores(project_id, score_type="image", db_path=_db())
    out = []
    for r in rows:
        score_blob = r.get("score") or {}
        out.append(
            {
                "total_score": int(r.get("total_score", 0)),
                "hard_fail": bool(score_blob.get("hard_fail", False)),
            }
        )
    return out


def _assemble_context(
    project_id: str, project: dict[str, Any], element_urls: dict[str, str]
) -> dict[str, Any]:
    import json as _json

    lock_raw = project.get("domain_session_lock_json")
    domain_lock = _json.loads(lock_raw) if lock_raw else {}

    snapshot = db.get_latest_snapshot(db_path=_db())
    routes_rows = db.get_routes(project_id, db_path=_db())
    routes = [
        {
            "feature_name": r.get("feature_name", ""),
            "route_type": r.get("route_type", ""),
            "verification_source": r.get("verification_source"),
            "confidence": r.get("confidence", 0.0),
            "allowed": True,
        }
        for r in routes_rows
    ]

    elements_rows = db.get_elements(project_id, db_path=_db())
    elements = [
        {
            "name": e.get("name", ""),
            "category": e.get("element_type", ""),
            "higgsfield_element_id": e.get("higgsfield_element_id", ""),
            "url": element_urls.get(e.get("higgsfield_element_id", ""), ""),
            "audit_status": e.get("audit_status", ""),
            "quality_score": e.get("quality_score"),
        }
        for e in elements_rows
    ]

    packet = db.get_artifact(project_id, "preproduction_packet", db_path=_db()) or {}
    anchor_state = db.get_artifact(project_id, "anchor_state", db_path=_db())
    if not anchor_state:
        anchors = [e for e in elements_rows if (e.get("usage_role") or "") == "anchor"]
        approved = [e for e in anchors if (e.get("audit_status") or "") == "pass"]
        anchor_state = {
            "anchors_required_count": len(anchors),
            "anchors_approved_count": len(approved),
            "anchor_audits": [],
        }

    bench_refs = db.get_benchmark_refs(project_id, db_path=_db())
    benchmark_refs = [
        {
            "reference_id": r.get("benchmark_id", ""),
            "url_or_path": r.get("url_or_path", ""),
            "reason": "",
            "visual_traits": r.get("visual_traits", {}),
        }
        for r in bench_refs
    ]

    active = db.get_active_bypasses(db_path=_db())
    bypasses = [
        {"component_bypassed": comp, "reason": rsn, "scope": "active"}
        for comp, rsn in active.items()
    ]

    return {
        "domain_lock": domain_lock,
        "refresh_snapshot": snapshot,
        "packet": packet,
        "benchmark_pack": _benchmark_pack(project_id),
        "routes": routes,
        "image_scores": _image_scores(project_id),
        "audits": db.get_audits(project_id, db_path=_db()),
        "anchor_state": anchor_state,
        "motion_plan": db.get_artifact(project_id, "motion_plan", db_path=_db()),
        "prompt_packet": db.get_artifact(project_id, "prompt_packet", db_path=_db()),
        "shot_list": db.get_artifact(project_id, "shot_list", db_path=_db()),
        "psp_components": db.get_artifact(project_id, "psp_components", db_path=_db()),
        "psp_result": db.get_artifact(project_id, "psp_result", db_path=_db())
        or {"total_score": 0},
        "finishing": db.get_artifact(project_id, "finishing", db_path=_db()),
        "benchmark_refs": benchmark_refs,
        "elements": elements,
        "shots": db.get_artifact(project_id, "execution_shots", db_path=_db()) or [],
        "success_criteria": packet.get("success_criteria", []),
        "bypasses": bypasses,
        "route_summary": "Higgsfield-contained",
        "route_policy": {"higgsfield_only": True},
        "post_production": (db.get_artifact(project_id, "finishing", db_path=_db()) or {}),
        "global_ui_config": db.get_artifact(project_id, "global_ui_config", db_path=_db()),
    }


# ===========================================================================
# Self-test
# ===========================================================================
_EXPECTED_TABLES = {
    "projects",
    "briefs",
    "benchmark_refs",
    "route_registry",
    "capability_snapshots",
    "audit_log",
    "quality_scores",
    "execution_packs",
    "bypass_log",
    "active_bypasses",
    "shots",
    "soul_ids",
    "elements",
    "reference_packs",
    "jobs",
    "workflows_cache",
}

_REQUIRED_TOOLS = {
    "aurora_classify_intent",
    "aurora_refresh_higgsfield_capabilities",
    "aurora_create_project",
    "aurora_create_domain_session_lock",
    "aurora_create_benchmark_pack",
    "aurora_create_brief",
    "aurora_validate_preproduction_packet",
    "aurora_verify_route",
    "aurora_propose_image_generation",
    "aurora_propose_video_execution",
    "aurora_record_required_elements",
    "aurora_record_audit",
    "aurora_record_quality_score",
    "aurora_check_quality_ceiling",
    "aurora_validate_biomechanics",
    "aurora_check_prompt_fitness",
    "aurora_check_multishot_strategy",
    "aurora_check_anchors_ready",
    "aurora_compute_production_success_probability",
    "aurora_emit_execution_pack",
    "aurora_log_bypass",
    "aurora_resolve_model_alias",
    "aurora_validate_element_injection",
    "aurora_validate_aspect_ratio",
    # deployed Sprint 1 tool, kept working
    "aurora_create_video_brief",
}


def _selftest() -> int:
    """Verify server wiring without starting the transport loop."""
    _ensure_db()

    conn = db.get_conn(_db())
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    missing_tables = _EXPECTED_TABLES - names
    assert not missing_tables, f"missing tables: {missing_tables}"

    import asyncio

    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    missing_tools = _REQUIRED_TOOLS - tool_names
    assert not missing_tools, f"missing tools: {missing_tools}"
    assert len(_REQUIRED_TOOLS) >= 24, "spec requires at least 24 tools"

    # Gate runs on an empty packet (reports missing, does not crash).
    res = gate_preproduction_packet.validate_packet({})
    assert res.passed is False and len(res.missing) > 0

    # Capabilities load with the spec defaults + KB overlay.
    caps = capability_refresh.load_capabilities()
    assert len(caps.get("cinema_studio_ui", {}).get("genres", {})) == 10

    # All 14 templates exist.
    required_templates = [
        "domain_session_lock.yaml", "benchmark_pack.yaml", "image_brief.yaml",
        "video_brief.yaml", "scene_bible.yaml", "character_sheet.yaml",
        "product_sheet.yaml", "prop_sheet.yaml", "location_sheet.yaml",
        "biomechanical_motion_plan.yaml", "shot_list.yaml", "anchor_strategy.yaml",
        "elements_registry.yaml", "execution_pack.md.jinja",
    ]
    for tmpl in required_templates:
        assert (REPO_ROOT / "templates" / tmpl).exists(), f"missing template {tmpl}"

    print(f"AURORA MCP self-test OK — {len(tool_names)} tools, {len(names)} tables")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    _ensure_db()
    use_http = "--http" in sys.argv or os.environ.get("AURORA_HTTP") == "1"
    if use_http:
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

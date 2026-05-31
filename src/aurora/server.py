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
import re
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
    gate_continuity_readiness,
    gate_multishot_anchor_strategy,
    gate_preproduction_packet,
    gate_prompt_fitness,
    gate_route_verification,
    gate_step_0_quality_ceiling,
    gate_upscale_finishing_route,
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


def _record_gate_eval(
    project_id: Optional[str],
    gate_name: str,
    result: Any,
    packet: Any = None,
    evaluator_version: Optional[str] = None,
) -> None:
    """Persist a gate verdict so emit reads the recorded decision instead of
    re-evaluating in-memory-only input (bugs #8/#10). No-op without project_id.

    ``result`` is a GateResult-like object exposing .passed/.score/.reasons/.notes.
    """
    if not project_id:
        return
    status = "pass" if getattr(result, "passed", False) else "fail"
    score = getattr(result, "score", None)
    db.put_gate_evaluation(
        project_id=project_id,
        gate_name=gate_name,
        status=status,
        score=int(score) if isinstance(score, (int, float)) else None,
        reasons=list(getattr(result, "reasons", []) or []),
        notes=getattr(result, "notes", "") or "",
        packet=packet,
        evaluator_version=evaluator_version,
        db_path=_db(),
    )


# ===========================================================================
# v2.3 — platform syntax research helpers
# ===========================================================================
# output_types AURORA recognizes for a syntax_dossier. Image and video keep
# distinct dossiers for the same model_id (different prompt grammar).
_ANCHOR_ELEMENT_TYPES = {"anchor", "character", "product", "prop", "location"}


def _dossier_is_fresh(dossier: Optional[dict[str, Any]]) -> bool:
    """A dossier is usable only if it exists and its TTL has not elapsed.
    expires_at is stored as an ISO-8601 UTC string, so lexical compare works."""
    if not dossier:
        return False
    expires_at = dossier.get("expires_at")
    return bool(expires_at) and str(expires_at) > db._now_iso()


def _research_required_models(
    mode: str,
    packet: dict[str, Any],
    shot_list: list[dict[str, Any]],
    elements_rows: list[dict[str, Any]],
) -> dict[str, str]:
    """Map every model the project will execute to its research output_type.

    Pipeline A (image): models behind declared elements (sheet.model_id /
    recommended_model), else the packet's model_route/recommended_model.
    Pipeline B/C (video): each shot's mcsla.model, else packet.recommended_model.
    """
    models: dict[str, str] = {}
    if mode == "image":
        for e in elements_rows or []:
            sheet = e.get("sheet") or {}
            model_id = (
                sheet.get("model_id")
                or sheet.get("recommended_model")
                or e.get("recommended_model")
            )
            if model_id:
                category = (e.get("element_type") or "").lower()
                models[model_id] = (
                    "image_anchor"
                    if category in _ANCHOR_ELEMENT_TYPES
                    else "image_genesis"
                )
        if not models:
            fallback = (packet.get("model_route") or {}).get("model_id") or packet.get(
                "recommended_model"
            )
            if fallback:
                models[fallback] = "image_genesis"
    else:  # video_simple | video_multishot
        for shot in shot_list or packet.get("shot_list") or []:
            mcsla = shot.get("mcsla") or {}
            model_id = mcsla.get("model") or packet.get("recommended_model")
            if model_id:
                models[model_id] = mode
        if not models and packet.get("recommended_model"):
            models[packet["recommended_model"]] = mode
    return models


def _research_coverage(models_required: dict[str, str]) -> dict[str, dict[str, Any]]:
    """For each declared model, look up its freshest dossier and report coverage
    so the (pure) gate can decide pass/fail without doing any I/O."""
    coverage: dict[str, dict[str, Any]] = {}
    for model_id, output_type in models_required.items():
        dossier = db.get_latest_syntax_dossier(model_id, output_type, db_path=_db())
        present = dossier is not None
        coverage[model_id] = {
            "output_type": output_type,
            "present": present,
            "expired": present and not _dossier_is_fresh(dossier),
            "confidence": (dossier or {}).get("confidence") if present else None,
        }
    return coverage


def _research_status_for_models(models_required: dict[str, str]) -> dict[str, Any]:
    """Operator-facing status surfaced by the propose_* tools, symmetric for
    image and video: which declared models still need research before emit."""
    status: dict[str, Any] = {}
    for model_id, output_type in models_required.items():
        dossier = db.get_latest_syntax_dossier(model_id, output_type, db_path=_db())
        fresh = _dossier_is_fresh(dossier)
        status[model_id] = {
            "output_type": output_type,
            "cached": fresh,
            "missing": dossier is None,
            "expired": dossier is not None and not fresh,
            "confidence": (dossier or {}).get("confidence") if dossier else None,
        }
    return status


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
    Reporting only — does not block. Persists the packet + records the gate
    verdict so emit reads the same result (bug #8).

    project_id is REQUIRED: pass it as a kwarg or carry it inside the packet.
    Without it the verdict can't be persisted, emit reads an empty DB, and the
    pack renders ceremonial-green-but-empty. Falling back to packet['project_id']
    closes the whole class of silent 'forgot the kwarg' bugs."""
    packet = packet or {}
    project_id = project_id or packet.get("project_id")
    if not project_id:
        return {
            "ok": False,
            "passed": False,
            "error": "project_id required (as kwarg or in packet); "
            "without it the verdict is not persisted and emit reads an empty DB",
        }
    result = gate_preproduction_packet.validate_packet(packet)
    _ensure_db()
    db.put_artifact(project_id, "preproduction_packet", packet, db_path=_db())
    # The shot_list lives inside the packet; persist it on its own so the
    # continuity + multishot gates read it without a separate check (bug #10).
    shot_list = packet.get("shot_list")
    if isinstance(shot_list, list) and shot_list:
        db.put_artifact(project_id, "shot_list", shot_list, db_path=_db())
    db.put_gate_evaluation(
        project_id=project_id,
        gate_name="gate_preproduction_packet",
        status="pass" if result.passed else "fail",
        reasons=[f"missing: {m}" for m in result.missing],
        notes="; ".join(result.warnings),
        packet=packet,
        evaluator_version="preproduction/2.2",
        db_path=_db(),
    )
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
    # v2.3: tell the operator which candidate models still need syntax research
    # before a prompt can be built (symmetric with video).
    out_type = "image_anchor" if image_type in _ANCHOR_ELEMENT_TYPES else "image_genesis"
    candidates: dict[str, str] = {}
    if selection.get("selected_route"):
        candidates[selection["selected_route"]["model_id"]] = out_type
    for cand in (selection.get("ranked_candidates") or [])[:3]:
        if cand.get("model_id"):
            candidates[cand["model_id"]] = out_type
    research_status = _research_status_for_models(candidates)
    selection["research_status"] = research_status
    any_missing = any(s["missing"] or s["expired"] for s in research_status.values())
    selection["next_required_action"] = (
        "research the selected model via aurora_request_platform_research"
        f"(model_id, output_type='{out_type}')"
        if any_missing
        else None
    )
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
    # v2.3: surface research coverage for every model in consideration.
    video_out_type = mode if mode in ("video_simple", "video_multishot") else "video_simple"
    candidates: dict[str, str] = {}
    if selection.get("selected_route"):
        candidates[selection["selected_route"]["model_id"]] = video_out_type
    for cand in (selection.get("ranked_candidates") or [])[:3]:
        if cand.get("model_id"):
            candidates[cand["model_id"]] = video_out_type
    research_status = _research_status_for_models(candidates)
    selection["research_status"] = research_status
    any_missing = any(s["missing"] or s["expired"] for s in research_status.values())
    selection["next_required_action"] = (
        "research the missing models via aurora_request_platform_research"
        if any_missing
        else None
    )
    return {"ok": selection["ok"], "project_id": project_id, "proposal": selection}


@mcp.tool()
def aurora_skip_finishing(project_id: str, reason: str = "") -> dict[str, Any]:
    """Mark a project as needing no upscale/finishing pass (Sección 13B.3). Use
    when the raw Higgsfield output is the final deliverable. Records the
    finishing route as not-required so gate_upscale_finishing_route passes."""
    _ensure_db()
    finishing = {
        "upscale_route": "outside_aurora",
        "not_required": True,
        "tools": [],
        "reason": reason or "operator: no finishing required",
    }
    db.put_artifact(project_id, "finishing", finishing, db_path=_db())
    result = gate_upscale_finishing_route.check(finishing)
    _record_gate_eval(
        project_id, "gate_upscale_finishing_route", result, packet=finishing,
        evaluator_version="finishing/2.2",
    )
    return {"ok": True, "project_id": project_id, "finishing": finishing}


# ===========================================================================
# 4b. Platform syntax research + prompt construction (v2.3)
# ===========================================================================
_RESEARCH_OUTPUT_TYPES = {
    "image_genesis",
    "image_anchor",
    "video_simple",
    "video_multishot",
}
_REQUIRED_SOURCE_TYPES = {"official_docs", "mcp_introspection", "community_forums"}
_REQUIRED_DOSSIER_FIELDS = {
    "model_id",
    "output_type",
    "prompt_template",
    "continuity_injection",
    "params_schema",
}
_HIGGSFIELD_MCP = "mcp__62dd5e40-9da1-495c-b80a-8a8ddeb93147__models_explore"


@mcp.tool()
def aurora_request_platform_research(
    project_id: str,
    model_id: str,
    output_type: str,
    shot_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return a structured research_brief the client must execute via the
    `research` skill, covering 3 mandatory source types (official_docs,
    mcp_introspection, community_forums). If a fresh dossier already exists for
    (model_id, output_type), returns cached=True with it instead — no re-research.

    output_type ∈ {image_genesis, image_anchor, video_simple, video_multishot}.
    """
    project_id = project_id or (shot_context or {}).get("project_id")
    if not project_id:
        return {"ok": False, "error": "project_id required (as kwarg or in shot_context)"}
    if output_type not in _RESEARCH_OUTPUT_TYPES:
        return {
            "ok": False,
            "error": f"invalid output_type '{output_type}'",
            "allowed": sorted(_RESEARCH_OUTPUT_TYPES),
        }
    _ensure_db()

    cached = db.get_latest_syntax_dossier(model_id, output_type, db_path=_db())
    if _dossier_is_fresh(cached):
        return {
            "ok": True,
            "cached": True,
            "cache_id": cached["cache_id"],
            "syntax_dossier": cached["syntax_dossier"],
            "expires_at": cached["expires_at"],
            "confidence": cached.get("confidence"),
        }

    is_image = output_type.startswith("image")
    injection_term = (
        "reference element injection" if is_image else "continuity reference injection"
    )
    forum_kind = "still image" if is_image else "multishot continuity"
    brief = {
        "research_required": True,
        "model_id": model_id,
        "output_type": output_type,
        "shot_context": shot_context,
        "required_sources_min": 3,
        "queries_per_source": {
            "official_docs": [
                f"{model_id} Higgsfield official documentation prompt syntax {output_type}",
                f"{model_id} parameters schema {output_type}",
                f"Higgsfield {model_id} {injection_term}",
            ],
            "mcp_introspection": [
                f"Call: {_HIGGSFIELD_MCP} action=get model_id={model_id}",
                "Extract: parameters, aspect_ratios, medias roles, duration_range",
            ],
            "community_forums": [
                f"reddit r/HiggsfieldAI {model_id} best prompt",
                f"github OSideMedia higgsfield-ai-prompt-skill {model_id}",
                f"{model_id} {forum_kind} prompt example",
                f"{model_id} site:github.com OR site:reddit.com",
            ],
        },
        "expected_dossier_schema": "see syntax_dossier schema in the v2.3 spec",
        "ttl_days": 30,
        "instructions": (
            "Invoke the `research` skill with the queries above. It must hit ALL 3 "
            "source types. Extract verbatim quotes from each. Build a syntax_dossier "
            "following the documented schema. Then call aurora_record_platform_research "
            "with the dossier + sources. If the `research` skill is unavailable, the "
            "operator must research manually and supply the dossier."
        ),
    }
    return {"ok": True, "cached": False, "research_brief": brief}


@mcp.tool()
def aurora_record_platform_research(
    project_id: str,
    model_id: str,
    output_type: str,
    syntax_dossier: dict[str, Any],
    sources: list[dict[str, Any]],
    ttl_days: int = 30,
) -> dict[str, Any]:
    """Persist the syntax_dossier resulting from the client's research. Rejects
    the record unless ``sources`` covers all 3 mandatory source types, so a
    half-researched dossier can never silently power prompt construction.
    Confidence scales with source coverage (+bonus for verbatim quotes)."""
    if output_type not in _RESEARCH_OUTPUT_TYPES:
        return {
            "ok": False,
            "error": f"invalid output_type '{output_type}'",
            "allowed": sorted(_RESEARCH_OUTPUT_TYPES),
        }
    found_source_types = {s.get("source_type") for s in (sources or [])}
    missing = _REQUIRED_SOURCE_TYPES - found_source_types
    if missing:
        return {
            "ok": False,
            "error": f"missing required source types: {sorted(missing)}",
            "required": sorted(_REQUIRED_SOURCE_TYPES),
            "found": sorted(t for t in found_source_types if t),
        }

    missing_fields = _REQUIRED_DOSSIER_FIELDS - set((syntax_dossier or {}).keys())
    if missing_fields:
        return {"ok": False, "error": f"dossier missing fields: {sorted(missing_fields)}"}

    covered = found_source_types & _REQUIRED_SOURCE_TYPES
    confidence = len(covered) / 3.0
    quote_count = sum(1 for s in sources if s.get("verbatim_quote"))
    if quote_count >= 3:
        confidence = min(1.0, confidence + 0.1)

    _ensure_db()
    cache_id = db.insert_syntax_dossier(
        model_id=model_id,
        output_type=output_type,
        syntax_dossier=syntax_dossier,
        sources=sources,
        source_types_covered=sorted(covered),
        ttl_days=ttl_days,
        confidence=confidence,
        db_path=_db(),
    )
    return {
        "ok": True,
        "cache_id": cache_id,
        "model_id": model_id,
        "output_type": output_type,
        "expires_in_days": ttl_days,
        "confidence": confidence,
        "sources_count": len(sources),
    }


@mcp.tool()
def aurora_build_prompt(
    project_id: str,
    model_id: str,
    shot_or_element_data: dict[str, Any],
    output_type: str,
    continuity_strategy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Construct the final MCSLA prompt with the SELECTED model's specific syntax,
    reading the cached syntax_dossier. Blocks (with an actionable research call)
    when no fresh dossier exists. output_type is REQUIRED — no hidden default.

    Pipeline A (image): shot_or_element_data is an element_brief.
    Pipeline B/C (video): it is a shot (MCSLA + continuity context).
    """
    if output_type not in _RESEARCH_OUTPUT_TYPES:
        return {
            "ok": False,
            "error": f"invalid output_type '{output_type}'",
            "allowed": sorted(_RESEARCH_OUTPUT_TYPES),
        }
    _ensure_db()
    dossier_row = db.get_latest_syntax_dossier(model_id, output_type, db_path=_db())
    if not _dossier_is_fresh(dossier_row):
        return {
            "ok": False,
            "error": "research required: no fresh syntax_dossier for this "
            f"model+output_type ({model_id}, {output_type})",
            "required_action": "call aurora_request_platform_research first",
            "next_call": {
                "tool": "aurora_request_platform_research",
                "args": {
                    "project_id": project_id,
                    "model_id": model_id,
                    "output_type": output_type,
                },
            },
        }

    dossier = dossier_row["syntax_dossier"]
    data = shot_or_element_data or {}
    prompt_final = _render_prompt_with_dossier(dossier, data)
    warnings = _validate_prompt_against_dossier(prompt_final, dossier)

    injection = None
    strategy = continuity_strategy or data.get("continuity")
    if output_type == "video_multishot" and isinstance(strategy, dict) and (
        strategy.get("case_type") == "continuity_from_previous"
        or strategy.get("continuity_ref_type") not in (None, "", "none")
    ):
        injection = _build_continuity_injection(
            dossier.get("continuity_injection") or {}, strategy
        )

    ui_steps = None
    mcp_payload = None
    if data.get("route_type") == "ui_only":
        ui_steps = _render_ui_steps(dossier, data, injection)
    else:
        mcp_payload = _render_mcp_payload(dossier, data, injection)

    return {
        "ok": True,
        "model_id": model_id,
        "output_type": output_type,
        "prompt_final": prompt_final,
        "injection_instructions": injection,
        "ui_steps": ui_steps,
        "mcp_payload": mcp_payload,
        "warnings": warnings,
        "gotchas_relevantes": dossier.get("known_gotchas", []),
        "confidence": dossier_row.get("confidence"),
    }


# --- prompt rendering helpers (deterministic; no model calls) ---------------
def _as_text(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value or "")


def _camera_text(camera: Any) -> str:
    if isinstance(camera, dict):
        parts = [
            str(camera.get("body", "")),
            f"{camera.get('focal_mm')}mm" if camera.get("focal_mm") else "",
            str(camera.get("movement", "")),
        ]
        return " ".join(p for p in parts if p).strip()
    return str(camera or "")


def _render_prompt_with_dossier(dossier: dict[str, Any], data: dict[str, Any]) -> str:
    """Fill the dossier's prompt_template with MCSLA slots. Resolves both the
    composite {camera} slot and the GRANULAR camera/quality slots a platform
    template may declare ({camera_body}, {focal_mm}, {movement}, {quality}, …);
    any slot the data can't fill is stripped rather than shipped as a literal
    "{placeholder}" to the operator."""
    template = dossier.get("prompt_template") or "{subject}, {action}, {look}, {camera}"
    fmt = data.get("format") or {}
    camera = data.get("camera") if isinstance(data.get("camera"), dict) else {}
    focal = camera.get("focal_mm") or data.get("focal_mm")
    slots = {
        "subject": _as_text(data.get("subject") or data.get("name")),
        "action": _as_text(data.get("action")),
        "look": _as_text(data.get("look") or data.get("visual_style")),
        # Composite camera phrase (body + focal + movement).
        "camera": _camera_text(data.get("camera")),
        # Granular camera slots so platform templates can place each part.
        "camera_body": _as_text(camera.get("body") or data.get("camera_body")),
        "focal_mm": (f"{focal}mm" if focal else ""),
        "movement": _as_text(camera.get("movement") or data.get("movement")),
        "lens": _as_text(camera.get("lens") or data.get("lens")),
        "quality": _as_text(data.get("quality") or dossier.get("default_quality")),
        # Accept both singular and plural negative slots.
        "negative": _as_text(data.get("negative_constraints")),
        "negatives": _as_text(data.get("negative_constraints")),
        "aspect_ratio": str(
            fmt.get("aspect_ratio")
            or data.get("aspect_ratio")
            or camera.get("aspect_ratio")
            or ""
        ),
        "duration": str(data.get("duration_seconds") or ""),
        "brand_or_product": _as_text(data.get("brand_or_product")),
    }
    out = template
    for key, value in slots.items():
        out = out.replace("{" + key + "}", value)
    # Drop any remaining unfilled slots (e.g. a platform-specific placeholder we
    # don't model) so the final prompt never contains literal braces.
    out = re.sub(r"\{[a-zA-Z0-9_]+\}", "", out)
    # Tidy the punctuation/whitespace debris left by emptied slots.
    out = re.sub(r"\s+([,.;:])", r"\1", out)        # " ," -> ","
    out = re.sub(r"([,.;:])(?:\s*[,.;:])+", r"\1", out)  # ", ." -> ","
    out = re.sub(r"\s{2,}", " ", out)               # collapse runs of spaces
    return out.strip().strip(",.;: ").strip()


def _validate_prompt_against_dossier(
    prompt: str, dossier: dict[str, Any]
) -> list[str]:
    """Surface dossier-declared anti-patterns present in the built prompt and
    required-field reminders. Reporting only — never blocks."""
    warnings: list[str] = []
    lowered = prompt.lower()
    for forbidden in dossier.get("forbidden_in_prompt", []) or []:
        token = str(forbidden).lower()
        if token and token in lowered:
            warnings.append(f"prompt contains a forbidden pattern: {forbidden}")
    max_chars = dossier.get("prompt_max_chars") or 0
    if max_chars and len(prompt) > int(max_chars):
        warnings.append(
            f"prompt is {len(prompt)} chars, over the model max of {max_chars}"
        )
    return warnings


def _build_continuity_injection(
    continuity_injection: dict[str, Any], strategy: dict[str, Any]
) -> dict[str, Any]:
    """Combine the dossier's platform continuity method with this shot's concrete
    previous-clip reference, so the operator gets exact injection instructions."""
    return {
        "method": continuity_injection.get("method", ""),
        "mcp_payload_example": continuity_injection.get("mcp_payload_example", {}),
        "ui_steps": continuity_injection.get("ui_steps", []),
        "notes": continuity_injection.get("notes", ""),
        "previous_clip_ref": strategy.get("previous_clip_ref")
        or strategy.get("continuity_ref_type"),
        "case_type": strategy.get("case_type", "continuity_from_previous"),
    }


def _render_ui_steps(
    dossier: dict[str, Any], data: dict[str, Any], injection: Optional[dict[str, Any]]
) -> list[str]:
    steps = [
        f"Open {dossier.get('model_display_name') or dossier.get('model_id')} in the Higgsfield UI.",
        "Paste prompt_final into the prompt panel.",
    ]
    ar = (data.get("format") or {}).get("aspect_ratio") or data.get("aspect_ratio")
    if ar:
        steps.append(f"Set aspect ratio to {ar}.")
    if injection:
        steps.extend(injection.get("ui_steps") or [])
        if injection.get("previous_clip_ref"):
            steps.append(
                f"Inject continuity via {injection.get('method')}: "
                f"{injection['previous_clip_ref']}."
            )
    return steps


def _render_mcp_payload(
    dossier: dict[str, Any], data: dict[str, Any], injection: Optional[dict[str, Any]]
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model_id": dossier.get("model_id")}
    # params_schema may be a list of {name, default} dicts OR a dict mapping
    # param name -> type/spec. Normalise to dicts before reading defaults so a
    # mapping-shaped schema never makes us call .get on a bare string key.
    schema = dossier.get("params_schema") or []
    if isinstance(schema, dict):
        params = [
            {"name": k, **(v if isinstance(v, dict) else {})}
            for k, v in schema.items()
        ]
    else:
        params = schema
    for param in params:
        if not isinstance(param, dict):
            continue
        name = param.get("name")
        if name and param.get("default") is not None:
            payload[name] = param.get("default")
    ar = (data.get("format") or {}).get("aspect_ratio") or data.get("aspect_ratio")
    if ar:
        payload["aspect_ratio"] = ar
    if data.get("duration_seconds"):
        payload["duration"] = data["duration_seconds"]
    if injection and injection.get("mcp_payload_example"):
        payload["medias"] = injection["mcp_payload_example"].get("medias", [])
    return payload


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
    result = gate_step_0_quality_ceiling.check(context)
    _record_gate_eval(project_id, "gate_step_0_quality_ceiling", result)
    return result.model_dump()


@mcp.tool()
def aurora_validate_biomechanics(
    project_id: str, motion_plan: dict[str, Any]
) -> dict[str, Any]:
    """Validate a biomechanical motion plan for hard fails (Sección 7.3)."""
    _ensure_db()
    db.put_artifact(project_id, "motion_plan", motion_plan or {}, db_path=_db())
    result = gate_biomechanical_sanity.check(motion_plan)
    _record_gate_eval(
        project_id, "gate_biomechanical_sanity", result, packet=motion_plan,
        evaluator_version="biomechanics/2.2",
    )
    return result.model_dump()


@mcp.tool()
def aurora_check_prompt_fitness(
    project_id: str, prompt_packet: dict[str, Any]
) -> dict[str, Any]:
    """Check Prompt Fitness (Sección 3.6 / 7.1). Accepts either per-criterion
    rubric scores or a rich prompt packet — both are scored sensibly (bug #7)."""
    _ensure_db()
    db.put_artifact(project_id, "prompt_packet", prompt_packet or {}, db_path=_db())
    result = gate_prompt_fitness.check(prompt_packet)
    _record_gate_eval(
        project_id, "gate_prompt_fitness", result, packet=prompt_packet,
        evaluator_version=prompt_fitness_score.EVALUATOR_VERSION,
    )
    return result.model_dump()


@mcp.tool()
def aurora_check_multishot_strategy(
    project_id: str,
    shot_list: list[dict[str, Any]],
    anchor_strategy: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Check multishot anchor strategy (Sección 7.1 / 6.5)."""
    _ensure_db()
    db.put_artifact(project_id, "shot_list", shot_list or [], db_path=_db())
    result = gate_multishot_anchor_strategy.check(shot_list)
    _record_gate_eval(
        project_id, "gate_multishot_anchor_strategy", result, packet=shot_list,
        evaluator_version="multishot/2.2",
    )
    # The continuity gate reads the same shot_list; record it here too so a
    # single check call satisfies both multishot gates at emit time.
    continuity = gate_continuity_readiness.check(shot_list)
    _record_gate_eval(
        project_id, "gate_continuity_readiness", continuity, packet=shot_list,
        evaluator_version="continuity/2.2",
    )
    return result.model_dump()


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
    result = gate_anchors_audited.check(state)
    _record_gate_eval(project_id, "gate_anchors_audited", result)
    return result.model_dump()


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
    db.put_gate_evaluation(
        project_id=project_id,
        gate_name="gate_production_success_probability",
        status="pass" if result.get("passed") else "fail",
        score=int(result["total_score"]),
        reasons=[] if result.get("passed") else [
            f"PSP {result['total_score']} < {result.get('threshold', 85)}; "
            f"weakest: {result.get('weakest_component')}"
        ],
        packet=components,
        evaluator_version="psp/2.2",
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
    project_id: str,
    elements_with_urls: Optional[dict[str, str]] = None,
    bypass_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Emit the Execution Pack (Sección 10/13). BLOCKS unless every required
    gate for the mode passes or has a registered active bypass.

    Gate verdicts recorded by the validate_*/check_* tools are read from
    gate_evaluations (persist-then-read); gates with no recorded verdict are
    evaluated from assembled context. ``bypass_ids`` explicitly applies bypasses
    logged via aurora_log_bypass (any scope, including current_turn), so an
    operator override is honored at emit time (bug #9)."""
    _ensure_db()
    project = db.get_project(project_id, db_path=_db())
    if not project:
        return {"ok": False, "reason": f"unknown project: {project_id}"}
    mode = project.get("mode") or "image"
    context = _assemble_context(project_id, project, elements_with_urls or {})
    recorded = db.get_latest_gate_evaluations(project_id, db_path=_db())

    # Bypass sources, in increasing specificity:
    #  1. global persist/all_session active bypasses,
    #  2. current_turn bypasses logged against this project,
    #  3. explicit bypass_ids the caller chose to apply.
    active = db.get_active_bypasses(db_path=_db())
    active.update(db.get_logged_bypasses_for_project(project_id, db_path=_db()))
    for bid in bypass_ids or []:
        row = db.get_bypass_log(bid, db_path=_db())
        if row and row.get("component_bypassed"):
            comp = bypass_handler.canonical_component(row["component_bypassed"])
            active[comp] = row.get("reason") or "operator bypass"

    project_view = {
        "project_id": project_id,
        "operator_intent": project.get("operator_intent", ""),
        "output_type": project.get("output_type", ""),
        "mode": mode,
    }
    result = execution_pack_builder.build_execution_pack(
        project_view, context, mode, active_bypasses=active, recorded=recorded
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
    operator_text: str = "",
    component: Optional[str] = None,
    reason: Optional[str] = None,
    scope: Optional[str] = None,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """Register an operator bypass directive (Sección K). When component/reason
    are omitted, the directive is parsed from operator_text. Pass project_id to
    scope the bypass to a project so emit honors it (bug #9); the returned
    bypass_id can also be passed to aurora_emit_execution_pack(bypass_ids=[...])."""
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
    bypass_id = bypass_handler.log_bypass(directive, project_id=project_id, db_path=_db())
    if scope in ("persist", "all_session"):
        db.set_active_bypass(component, scope, reason, project_id=project_id, db_path=_db())
    return {
        "ok": True,
        "bypass_id": bypass_id,
        "scope": scope,
        "component": component,
        "project_id": project_id,
    }


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


def _elements_from_packet(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive the section-5 element catalogue from a preproduction packet when no
    audited element rows exist yet. IDs come only from the packet (soul_id /
    higgsfield_element_id); a missing ID stays blank — never invented."""
    out: list[dict[str, Any]] = []
    for c in packet.get("characters") or []:
        if not isinstance(c, dict):
            continue
        out.append({
            "name": c.get("name", ""),
            "category": "character",
            "higgsfield_element_id": c.get("soul_id") or c.get("higgsfield_element_id", "") or "",
            "url": "",
            "audit_status": "from_packet",
            "quality_score": None,
        })
    loc = packet.get("location") or {}
    if isinstance(loc, dict) and loc:
        out.append({
            "name": loc.get("name", ""),
            "category": "location",
            "higgsfield_element_id": loc.get("higgsfield_element_id", "") or "",
            "url": "",
            "audit_status": "from_packet",
            "quality_score": None,
        })
    for p in packet.get("props_or_product") or []:
        if not isinstance(p, dict):
            continue
        out.append({
            "name": p.get("name", ""),
            "category": "prop_or_product",
            "higgsfield_element_id": p.get("higgsfield_element_id", "") or "",
            "url": "",
            "audit_status": "from_packet",
            "quality_score": None,
        })
    return out


def _global_ui_from_packet(
    packet: dict[str, Any], prompt_packet: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Build the section-7 Global UI block from the packet's visual style + the
    prompt packet's camera. Returns None (→ 'no UI setup required') only when the
    packet truly carries neither, so the section reflects real operator data."""
    pp = prompt_packet or {}
    cam = pp.get("camera") if isinstance(pp.get("camera"), dict) else {}
    style = packet.get("visual_style") or pp.get("look") or pp.get("style_palette")
    if not style and not cam:
        return None
    return {
        "ui_product_name": packet.get("recommended_model") or pp.get("model") or "",
        "genre": packet.get("genre", ""),
        "style_palette": style or "",
        "camera_body": cam.get("body", ""),
        "aspect_ratio": cam.get("aspect_ratio", ""),
        "resolution": cam.get("resolution", ""),
        "audio": packet.get("audio_strategy", ""),
    }


def _shots_for_render(
    shot_list: list[dict[str, Any]],
    prompt_packet: dict[str, Any],
    packet: dict[str, Any],
) -> list[dict[str, Any]]:
    """Map the persisted shot_list into the rich section-8 shot structure the
    template renders (UI config, MCSLA, anchors, continuity, prompt, negatives).

    Per-shot fields win; otherwise project-level prompt-packet values fill in so
    the operative document is populated from validated data instead of blank. No
    field is fabricated — absent data renders as an empty cell."""
    import yaml as _yaml

    pp = prompt_packet or {}
    cam = pp.get("camera") if isinstance(pp.get("camera"), dict) else {}
    style = packet.get("visual_style") or pp.get("look") or pp.get("style_palette") or ""
    subject = pp.get("subject")
    if not isinstance(subject, list):
        subject = [subject] if subject else []

    shots: list[dict[str, Any]] = []
    for sh in shot_list or []:
        if not isinstance(sh, dict):
            continue
        anchor = dict(sh.get("anchor_strategy") or {})
        # The template reads anchor_strategy.reference_injection.inject_syntax;
        # default it so a packet anchor without that nested block renders blank
        # instead of raising.
        anchor.setdefault("reference_injection", {})
        cont = sh.get("continuity") or {}
        bio = sh.get("biomechanical_plan") or sh.get("biomechanics") or {}
        mcp_payload = sh.get("mcp_payload")
        shots.append({
            "shot_number": sh.get("shot_number"),
            "function": sh.get("function") or sh.get("shot_type") or "",
            "route_id": sh.get("route_id") or pp.get("model") or "",
            "route_type": sh.get("route_type") or "",
            "duration_seconds": sh.get("duration_seconds"),
            "shot_type": sh.get("shot_type") or "",
            "ui_config": sh.get("ui_config") or {
                "route_id": sh.get("route_id") or pp.get("model", ""),
                "genre": packet.get("genre", ""),
                "style_palette": style,
                "camera_moveset": cam.get("movement", ""),
                "speed_ramp": "",
                "resolution": cam.get("resolution", ""),
                "audio": packet.get("audio_strategy", ""),
                "duration_seconds": sh.get("duration_seconds"),
            },
            "mcp_payload": mcp_payload,
            "mcp_payload_json": execution_pack_builder.to_pretty_json(mcp_payload)
            if mcp_payload else "",
            "anchor_strategy": anchor,
            "mcsla": sh.get("mcsla") or {
                "model": pp.get("model", "") or sh.get("route_id", ""),
                "camera": cam.get("body", "") or cam.get("movement", ""),
                "subject": subject,
                "look": style,
                "action": sh.get("action") or pp.get("action") or "",
            },
            "prompt_final": sh.get("prompt_final") or pp.get("prompt_final") or "",
            "biomechanical_yaml": _yaml.safe_dump(bio, allow_unicode=True, sort_keys=False)
            if bio else "",
            "negative_constraints": sh.get("negative_constraints")
            or pp.get("negative_constraints") or [],
            "continuity": cont,
            "expected_scores": sh.get("expected_scores") or {
                "prompt_fitness_min": prompt_fitness_score.THRESHOLD,
                "biomechanics_min": 85,
                "continuity_readiness_min": 85,
            },
        })
    return shots


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
    # shot_list may have been recorded standalone (check_multishot_strategy) or
    # only embedded in the preproduction packet; prefer the standalone artifact,
    # fall back to the packet so the continuity gate reads it either way (#10).
    shot_list = db.get_artifact(project_id, "shot_list", db_path=_db())
    if not shot_list:
        shot_list = packet.get("shot_list") or []
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

    prompt_packet = db.get_artifact(project_id, "prompt_packet", db_path=_db()) or {}

    # The validated packet is the source of operative content. When the dedicated
    # tables/artifacts that normally carry richer data are empty, fall back to the
    # persisted packet so the Execution Pack's critical sections (5 elements, 7 UI,
    # 8 shot list) are populated instead of ceremonially blank.
    if not elements:
        elements = _elements_from_packet(packet)
    execution_shots = db.get_artifact(project_id, "execution_shots", db_path=_db())
    if not execution_shots:
        execution_shots = _shots_for_render(shot_list, prompt_packet, packet)
    global_ui_config = db.get_artifact(project_id, "global_ui_config", db_path=_db())
    if not global_ui_config:
        global_ui_config = _global_ui_from_packet(packet, prompt_packet)

    # v2.3: research coverage is computed here (with db access) so the gate stays
    # pure. Every model the project will execute must hold a fresh syntax_dossier.
    mode = project.get("mode") or "image"
    research_models = _research_required_models(mode, packet, shot_list, elements_rows)
    research_coverage = _research_coverage(research_models)

    return {
        "mode": mode,
        "research_coverage": research_coverage,
        "domain_lock": domain_lock,
        "refresh_snapshot": snapshot,
        "packet": packet,
        "benchmark_pack": _benchmark_pack(project_id),
        "routes": routes,
        "image_scores": _image_scores(project_id),
        "audits": db.get_audits(project_id, db_path=_db()),
        "anchor_state": anchor_state,
        "motion_plan": db.get_artifact(project_id, "motion_plan", db_path=_db()),
        "prompt_packet": prompt_packet,
        "shot_list": shot_list,
        "psp_components": db.get_artifact(project_id, "psp_components", db_path=_db()),
        "psp_result": db.get_artifact(project_id, "psp_result", db_path=_db())
        or {"total_score": 0},
        "finishing": db.get_artifact(project_id, "finishing", db_path=_db()),
        "benchmark_refs": benchmark_refs,
        "elements": elements,
        "shots": execution_shots,
        "success_criteria": packet.get("success_criteria", []),
        "bypasses": bypasses,
        "route_summary": "Higgsfield-contained",
        "route_policy": {"higgsfield_only": True},
        "post_production": (db.get_artifact(project_id, "finishing", db_path=_db()) or {}),
        "global_ui_config": global_ui_config,
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
    "gate_evaluations",
    "shots",
    "soul_ids",
    "elements",
    "reference_packs",
    "jobs",
    "workflows_cache",
    "platform_syntax_cache",
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
    "aurora_skip_finishing",
    "aurora_emit_execution_pack",
    "aurora_log_bypass",
    "aurora_resolve_model_alias",
    "aurora_validate_element_injection",
    "aurora_validate_aspect_ratio",
    # v2.3 research-driven prompt construction
    "aurora_request_platform_research",
    "aurora_record_platform_research",
    "aurora_build_prompt",
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

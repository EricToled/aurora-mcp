"""video_model_router — pick a registered video route (Sección 11.3 / 11.4).

Mr Higgs is planning-only and can NEVER be returned as an executable route
(Sección 5B.4 / 11.4 — Forbidden error observed). Routes with
``mcp_callable_if_verified`` require a live snapshot or current schema before
credit spend; the router flags that requirement, it does not fabricate one.
"""
from __future__ import annotations

from typing import Any, Optional

from .. import capability_refresh

VIDEO_ROUTES: list[dict[str, Any]] = [
    {
        "route_id": "cinema_studio_ui_shot_by_shot",
        "route_type": "ui_only_or_hybrid",
        "model_id": "cinematic_studio_3_0",
        "use_for": "premium control per shot, characters, props, camera, style",
        "modes": ["video_simple", "video_multishot"],
    },
    {
        "route_id": "cinematic_studio_video_mcp_single_clip",
        "route_type": "mcp_callable_if_verified",
        "model_id": "cinematic_studio_video_v2",
        "use_for": "simple FF/LF or single action video",
        "modes": ["video_simple"],
    },
    {
        "route_id": "seedance_structured_multishot",
        "route_type": "mcp_callable_if_verified",
        "model_id": "seedance_2_0",
        "use_for": "structured multishot prompt if model schema supports",
        "modes": ["video_multishot"],
    },
    {
        "route_id": "kling_inside_higgsfield_motion",
        "route_type": "mcp_callable_if_verified",
        "model_id": "kling_3_0",
        "use_for": "motion-heavy sequences if available",
        "modes": ["video_simple", "video_multishot"],
    },
    {
        "route_id": "veo_inside_higgsfield_realism",
        "route_type": "mcp_callable_if_verified",
        "model_id": "veo",
        "use_for": "ultra-realism if available in workspace",
        "modes": ["video_simple", "video_multishot"],
    },
]

# UI-only orchestration surfaces (Sección 11.4). Never executable as MCP routes.
UI_ONLY_ROUTES: dict[str, dict[str, Any]] = {
    "mr_higgs": {
        "route_type": "ui_only_planning_only",
        "use_for": "planning, shot breakdown, suggestions",
        "warning": "Do not assume MCP callable. Never apply style/genre through "
        "Mr Higgs; Forbidden error observed.",
    },
    "popcorn_or_storyboard": {"use_for": "keyframes / storyboard if available"},
    "angles_2_0": {"use_for": "perspective changes if available"},
    "multishot_orchestration": {
        "use_for": "only if UI exposes editable cards/timeline/sequence builder"
    },
}

# Never returnable as an executable route.
NEVER_EXECUTABLE = {"mr_higgs"}

# Routes whose type defers verification — credit spend needs a live snapshot.
_NEEDS_LIVE_VERIFY = {"mcp_callable_if_verified"}


def _registered_routes() -> list[dict[str, Any]]:
    caps = capability_refresh.load_capabilities()
    overrides = caps.get("video_routes")
    if isinstance(overrides, list) and overrides:
        return overrides
    return VIDEO_ROUTES


def select_route(
    mode: str,
    aspect_ratio: Optional[str] = None,
    prefer_route_id: Optional[str] = None,
) -> dict[str, Any]:
    """Rank registered video routes for a project mode. Mr Higgs is excluded.

    mode in {'video_simple', 'video_multishot'}.
    """
    routes = _registered_routes()
    ranked: list[dict[str, Any]] = []
    for r in routes:
        rid = r.get("route_id", "")
        if rid in NEVER_EXECUTABLE:
            continue
        modes = [m.lower() for m in r.get("modes", [])]
        score = 0
        if not modes or mode in modes:
            score = 100
        if prefer_route_id and rid == prefer_route_id:
            score += 50
        if score == 0:
            continue
        candidate = {**r, "match_score": score}
        model_id = r.get("model_id", "")
        rtype = r.get("route_type", "")
        if rtype in _NEEDS_LIVE_VERIFY:
            candidate["credit_spend_requires"] = (
                "live snapshot or current model schema before credit spend"
            )
        if aspect_ratio and model_id:
            candidate["aspect_ratio_check"] = capability_refresh.validate_aspect_ratio(
                model_id, aspect_ratio
            )
        ranked.append(candidate)

    ranked.sort(key=lambda c: c["match_score"], reverse=True)
    best = ranked[0] if ranked else None
    return {
        "ok": best is not None,
        "mode": mode,
        "selected_route": best,
        "ranked_candidates": ranked,
        "ui_only_routes": UI_ONLY_ROUTES,
        "reason": None if best else f"no registered video route matches mode={mode!r}",
    }

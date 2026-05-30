"""internal_route_bakeoff — rank candidate Higgsfield routes (Sección 6.1).

A bake-off ranks registered routes against the brief's needs (verification
state, surface preference, aspect-ratio support, element-injection support).
It never invents a route and never marks an unverified route as credit-ready;
it surfaces *why* a route ranks where it does so the operator can choose.
"""
from __future__ import annotations

from typing import Any, Optional

from .. import capability_refresh

# Verification posture → base score. mcp_callable+verified ranks highest;
# unverified/outside lower. These are routing preferences, not capability claims.
_SURFACE_BASE = {
    "mcp_callable": 50,
    "ui_only_or_hybrid": 40,
    "hybrid": 40,
    "ui_only": 35,
    "mcp_callable_or_ui_verified": 30,
    "mcp_callable_if_verified": 25,
    "not_verified": 10,
    "outside_aurora": 0,
}


def _score_route(
    route: dict[str, Any],
    aspect_ratio: Optional[str],
    element_ids: Optional[list[str]],
    require_verified: bool,
) -> dict[str, Any]:
    rtype = route.get("route_type", "not_verified")
    model_id = route.get("model_id", "")
    score = _SURFACE_BASE.get(rtype, 10)
    notes: list[str] = []

    if route.get("verified"):
        score += 30
        notes.append("verified snapshot/schema present")
    elif require_verified:
        score -= 20
        notes.append("verification required but missing — not credit-ready")

    ar_check = None
    if aspect_ratio and model_id:
        ar_check = capability_refresh.validate_aspect_ratio(model_id, aspect_ratio)
        if ar_check["status"] == "blocked":
            score -= 40
            notes.append(f"aspect ratio {aspect_ratio} blocked for {model_id}")
        elif ar_check["ok"]:
            score += 5

    inj_check = None
    if element_ids and model_id:
        inj_check = capability_refresh.validate_element_injection(model_id, element_ids)
        if inj_check["ok"]:
            score += 10
            notes.append("element injection supported")
        else:
            notes.append(inj_check["reason"])

    return {
        **route,
        "bakeoff_score": score,
        "aspect_ratio_check": ar_check,
        "element_injection_check": inj_check,
        "notes": "; ".join(notes),
    }


def bakeoff(
    candidate_routes: list[dict[str, Any]],
    aspect_ratio: Optional[str] = None,
    element_ids: Optional[list[str]] = None,
    require_verified: bool = False,
) -> dict[str, Any]:
    """Rank candidate routes. Returns the winner plus the full ranked list.

    Pure ranking over registered candidates — no route is fabricated.
    """
    if not candidate_routes:
        return {
            "ok": False,
            "winner": None,
            "ranked": [],
            "reason": "no candidate routes supplied",
        }
    scored = [
        _score_route(r, aspect_ratio, element_ids, require_verified)
        for r in candidate_routes
    ]
    scored.sort(key=lambda c: c["bakeoff_score"], reverse=True)
    winner = scored[0]
    credit_ready = winner.get("bakeoff_score", 0) > 0 and (
        winner.get("verified") or not require_verified
    )
    return {
        "ok": True,
        "winner": winner,
        "ranked": scored,
        "winner_credit_ready": bool(credit_ready),
        "reason": None
        if credit_ready
        else "winner selected but not yet credit-ready; verify live before spend",
    }

"""ui_vs_mcp_router — decide per-feature whether to drive Higgsfield via MCP or UI.

Classifies a platform feature into a route_type and decides the emission mode:
an MCP payload (only when callable AND verified) or UI instructions. Features
known to live outside Higgsfield (Adobe/Topaz/CapCut/DaVinci) are classified
``outside_aurora`` and never emitted as AURORA-executable (Sección 5.4 / 13B).
"""
from __future__ import annotations

from typing import Any, Optional

from .. import capability_refresh

VALID_ROUTE_TYPES = {
    "mcp_callable",
    "ui_only",
    "hybrid",
    "not_verified",
    "outside_aurora",
}

# Transitional spec labels → resolved surface assumption (still needs live
# verification before credit spend where noted).
_TYPE_NORMALIZE = {
    "mcp_callable": "mcp_callable",
    "ui_only": "ui_only",
    "hybrid": "hybrid",
    "not_verified": "not_verified",
    "outside_aurora": "outside_aurora",
    "ui_only_planning_only": "ui_only",
    "ui_only_or_hybrid": "hybrid",
    "ui_only_or_not_verified": "not_verified",
    "mcp_callable_if_verified": "not_verified",
    "mcp_callable_or_ui_verified": "not_verified",
}

# Features that must be outside_aurora unless a verified connector exists.
EXTERNAL_FEATURES = {"capcut", "davinci", "adobe podcast", "topaz"}

_VERIFIED_SOURCES = {"live_mcp", "ui_observed"}


def classify(
    feature_name: str,
    route_type: Optional[str] = None,
    verified: bool = False,
    verification_source: Optional[str] = None,
) -> dict[str, Any]:
    """Classify a feature and decide whether to emit an MCP payload or UI steps.

    - mcp_callable + verified source → generate_mcp_payload
    - ui_only / hybrid → generate_ui_instructions
    - not_verified → blocked from credit spend until a live refresh verifies it
    - outside_aurora → documented but never AURORA-executable
    """
    name = (feature_name or "").strip().lower()
    raw = (route_type or "not_verified").strip().lower()
    resolved = _TYPE_NORMALIZE.get(raw, "not_verified")

    # External finishing tools are outside_aurora unless a verified connector.
    if any(ext in name for ext in EXTERNAL_FEATURES) and not verified:
        resolved = "outside_aurora"

    source_ok = (verification_source or "").strip().lower() in _VERIFIED_SOURCES
    is_verified = bool(verified) or source_ok

    if resolved == "outside_aurora":
        return _result(feature_name, "outside_aurora", False, False,
                       "feature is outside Higgsfield; document manual step, never execute")
    if resolved == "mcp_callable":
        if is_verified:
            return _result(feature_name, "mcp_callable", True, False,
                           "callable and verified — emit MCP payload")
        return _result(feature_name, "not_verified", False, False,
                       "mcp_callable claimed but no verified source — blocked until live refresh")
    if resolved in ("ui_only", "hybrid"):
        return _result(feature_name, resolved, False, True,
                       "drive via UI instructions" if resolved == "ui_only"
                       else "hybrid — UI instructions plus MCP payload where verified")
    # not_verified
    return _result(feature_name, "not_verified", False, False,
                   "route not verified — read live schema / snapshot before credit spend")


def _result(feature: str, rtype: str, mcp: bool, ui: bool, reason: str) -> dict[str, Any]:
    return {
        "ok": rtype in ("mcp_callable", "ui_only", "hybrid"),
        "feature_name": feature,
        "route_type": rtype,
        "generate_mcp_payload": mcp,
        "generate_ui_instructions": ui,
        "credit_spend_allowed": mcp,
        "reason": reason,
    }


def route_capability_features() -> dict[str, Any]:
    """Classify the quality_controls block from the capability snapshot so the
    operator sees which finishing routes are callable vs UI vs outside AURORA."""
    caps = capability_refresh.load_capabilities()
    controls = caps.get("quality_controls", {})
    out: dict[str, Any] = {}
    for feature, meta in controls.items():
        route = meta.get("route", "not_verified")
        out[feature] = classify(feature, route_type=route,
                                 verified=bool(meta.get("mcp_callable")))
    return out

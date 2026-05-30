"""gate_route_verification (Sección 7.4 + 5C.5).

Every route must be registered with a valid route_type. ``not_verified`` cannot
spend credits unless explicitly allowed (bypass). ``mcp_callable`` requires a
verification source. UI-only/hybrid video routes must carry the full UI control
set (genre, speed_ramp, camera_moveset, style_palette, duration_seconds,
aspect_ratio, audio, reference strategy).
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult

VALID_ROUTE_TYPES = {
    "mcp_callable",
    "ui_only",
    "hybrid",
    "not_verified",
    "outside_aurora",
    # transitional labels used in the route registry until live refresh confirms
    "mcp_callable_if_verified",
    "mcp_callable_or_ui_verified",
    "ui_only_or_hybrid",
    "ui_only_planning_only",
}
REQUIRED_UI_CONTROLS = (
    "genre",
    "speed_ramp",
    "camera_moveset",
    "style_palette",
    "duration_seconds",
    "aspect_ratio",
    "audio",
    "reference_strategy",
)


def check(routes: list[dict[str, Any]] | None) -> GateResult:
    reasons: list[str] = []
    if not isinstance(routes, list) or len(routes) == 0:
        return GateResult(
            gate="gate_route_verification",
            passed=False,
            reasons=["no routes registered"],
        )
    for route in routes:
        name = route.get("feature_name", route.get("route_id", "?"))
        rtype = route.get("route_type")
        if rtype not in VALID_ROUTE_TYPES:
            reasons.append(f"{name}: invalid route_type {rtype!r}")
            continue
        if rtype == "not_verified" and not route.get("allowed", False):
            reasons.append(f"{name}: not_verified route cannot spend credits")
        if rtype == "mcp_callable" and not route.get("verification_source"):
            reasons.append(f"{name}: mcp_callable route lacks verification_source")
        is_ui = rtype in ("ui_only", "hybrid", "ui_only_or_hybrid")
        if is_ui and route.get("media") == "video":
            ui_cfg = route.get("ui_config") or {}
            missing = [c for c in REQUIRED_UI_CONTROLS if not ui_cfg.get(c)]
            if missing:
                reasons.append(
                    f"{name}: ui video route missing controls {missing}"
                )
    passed = not reasons
    return GateResult(gate="gate_route_verification", passed=passed, reasons=reasons)

"""gate_upscale_finishing_route (Sección 13B.3).

Passes if:
  1. the finishing route is explicitly classified, and
  2. no non-Higgsfield tool is described as AURORA-executable, and
  3. Adobe/Topaz/CapCut/DaVinci are marked outside_aurora unless a verified
     connector/tool exists.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult

VALID_UPSCALE_ROUTES = {
    "mcp_callable",
    "ui_only",
    "not_verified",
    "outside_aurora",
    "ui_only_or_mcp_if_verified",
    "ui_only_or_not_verified",
}
# Tools that must be outside_aurora unless a verified connector exists.
EXTERNAL_TOOLS = {"capcut", "davinci", "davinci resolve", "adobe podcast", "topaz"}


def check(finishing: dict[str, Any] | None) -> GateResult:
    reasons: list[str] = []
    if not isinstance(finishing, dict) or not finishing:
        return GateResult(
            gate="gate_upscale_finishing_route",
            passed=False,
            reasons=["no finishing route classified"],
        )

    upscale = finishing.get("upscale_route")
    if not upscale:
        reasons.append("upscale_route not classified")
    elif upscale not in VALID_UPSCALE_ROUTES:
        reasons.append(f"upscale_route invalid: {upscale!r}")

    for tool in finishing.get("tools", []) or []:
        name = str(tool.get("name", "")).strip().lower()
        route = tool.get("route")
        verified = bool(tool.get("verified_connector"))
        if tool.get("aurora_executable") and not (
            route == "mcp_callable" and verified
        ):
            reasons.append(f"{name or 'tool'} marked AURORA-executable without a verified connector")
        if any(ext in name for ext in EXTERNAL_TOOLS):
            if route != "outside_aurora" and not verified:
                reasons.append(
                    f"{name} must be outside_aurora unless a verified connector exists"
                )
    passed = len(reasons) == 0
    return GateResult(
        gate="gate_upscale_finishing_route",
        passed=passed,
        reasons=reasons,
    )

"""gate_continuity_readiness (Sección 7.1).

Every shot after the first must declare a continuity reference (last frame,
last seconds, screenshot, element or video ref). The opening shot is exempt.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult

VALID_REF_TYPES = {
    "none",
    "last_frame",
    "last_5s",
    "screenshot",
    "element",
    "video_ref",
}


def check(shot_list: list[dict[str, Any]] | None) -> GateResult:
    reasons: list[str] = []
    if not isinstance(shot_list, list) or len(shot_list) == 0:
        return GateResult(
            gate="gate_continuity_readiness",
            passed=False,
            reasons=["empty shot list"],
        )
    ordered = sorted(shot_list, key=lambda s: s.get("shot_number", 0))
    for idx, shot in enumerate(ordered):
        num = shot.get("shot_number", idx + 1)
        cont = shot.get("continuity") or {}
        ref_type = cont.get("continuity_ref_type", "none")
        if ref_type not in VALID_REF_TYPES:
            reasons.append(f"shot {num}: invalid continuity_ref_type {ref_type!r}")
        if idx > 0 and ref_type == "none":
            reasons.append(
                f"shot {num}: needs a continuity reference (non-opening shot)"
            )
    passed = len(reasons) == 0
    return GateResult(
        gate="gate_continuity_readiness",
        passed=passed,
        reasons=reasons,
    )

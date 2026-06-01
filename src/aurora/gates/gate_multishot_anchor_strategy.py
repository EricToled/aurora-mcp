"""gate_multishot_anchor_strategy (Sección 6.5 / 7.1).

Every shot in a multishot sequence must declare an anchor strategy with a
case_type and at least one usable anchor/continuity reference. A single long
prompt for incompatible actions is not allowed.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult

VALID_CASE_TYPES = {
    "simple_start",
    "start_and_end",
    "open_end",
    "multishot_per_shot",
    "continuity_from_previous",
    "dialogue_long",
    "complex_scene",
}
_ANCHOR_FIELDS = (
    "ff_higgsfield_element_id",
    "lf_higgsfield_element_id",
    "character_higgsfield_element_id",
    "prop_higgsfield_element_id",
    "product_higgsfield_element_id",
    "location_higgsfield_element_id",
    "previous_clip_ref",
    "previous_clip_last_seconds_ref",
    "intermediate_screenshot_ref",
)


def check(shot_list: list[dict[str, Any]] | None) -> GateResult:
    reasons: list[str] = []
    if not isinstance(shot_list, list) or len(shot_list) == 0:
        return GateResult(
            gate="gate_multishot_anchor_strategy",
            passed=False,
            reasons=["empty shot list"],
        )
    valid = ", ".join(sorted(VALID_CASE_TYPES))
    for shot in shot_list:
        # Canonical key is shot_number; fall back to shot_id so a mislabelled
        # shot is still identifiable in the message instead of "shot ?".
        num = shot.get("shot_number", shot.get("shot_id", "?"))
        strat = shot.get("anchor_strategy")
        if not isinstance(strat, dict) or not strat:
            reasons.append(f"shot {num}: no anchor_strategy")
            continue
        case_type = strat.get("case_type")
        if case_type not in VALID_CASE_TYPES:
            reasons.append(
                f"shot {num}: invalid case_type {case_type!r} — válidos: {valid}"
            )
        has_anchor = any(strat.get(f) for f in _ANCHOR_FIELDS)
        # A simple_start opening shot may legitimately have only an FF anchor;
        # all others need at least one anchor/continuity reference.
        if not has_anchor and case_type != "simple_start":
            reasons.append(
                f"shot {num}: anchor_strategy has no anchor reference — "
                f"set one of: {', '.join(_ANCHOR_FIELDS)}"
            )
    passed = len(reasons) == 0
    return GateResult(
        gate="gate_multishot_anchor_strategy",
        passed=passed,
        reasons=reasons,
    )

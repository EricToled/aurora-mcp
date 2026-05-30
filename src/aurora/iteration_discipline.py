"""Iteration delta discipline (Sección 14 rule: one variable per iteration).

When an output is rejected and re-attempted, AURORA changes exactly ONE
variable (model / anchor / biomechanics / prompt / aspect_ratio / ...) so the
cause of any quality change is attributable. ``check_iteration_delta`` compares
two attempt dicts and flags when more than one tracked variable changed.
"""
from __future__ import annotations

from typing import Any

# Variables whose change must be isolated between iterations.
TRACKED_VARIABLES = (
    "model_id",
    "route_id",
    "anchor_strategy",
    "biomechanics",
    "prompt",
    "aspect_ratio",
    "negative_constraints",
    "reference_strategy",
    "genre",
    "speed_ramp",
    "camera_moveset",
)


def diff_variables(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Return the tracked variables that differ between two attempts."""
    changed: list[str] = []
    for var in TRACKED_VARIABLES:
        if previous.get(var) != current.get(var):
            changed.append(var)
    return changed


def check_iteration_delta(
    previous: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    """Verify only one tracked variable changed between iterations.

    Returns {ok, changed_variables, disciplined, reason}. ``disciplined`` is
    True only when zero or one tracked variable changed.
    """
    changed = diff_variables(previous, current)
    disciplined = len(changed) <= 1
    if disciplined:
        reason = (
            "no change" if not changed else f"single variable changed: {changed[0]}"
        )
    else:
        reason = (
            "multiple variables changed in one iteration: "
            + ", ".join(changed)
            + " — isolate to one so the cause is attributable"
        )
    return {
        "ok": disciplined,
        "changed_variables": changed,
        "disciplined": disciplined,
        "reason": reason,
    }

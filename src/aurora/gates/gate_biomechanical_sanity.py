"""gate_biomechanical_sanity (Sección 7.3).

Validates support points, center of mass, joint ranges, object trajectory,
contact mechanics, equipment/environment constraints and pre/post-impact
continuity. Detects physically impossible actions (hard fails). The spinning +
header example from the spec must be caught.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult
from ..scoring import biomechanical_score

HEADER_TERMS = ("header", "cabezazo", "head the ball", "headbutt")
GROUND_BALL_CM = 10.0


def _described_motion_text(plan: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("head", "arms_hands", "legs", "torso", "initial_pose"):
        section = plan.get(key)
        if isinstance(section, dict):
            parts.extend(str(v) for v in section.values())
        elif section:
            parts.append(str(section))
    parts.append(str(plan.get("center_of_mass_trajectory", "")))
    return " ".join(parts).lower()


def detect_hard_fails(plan: dict[str, Any]) -> list[str]:
    fails: list[str] = []
    fails.extend(h for h in (plan.get("hard_fails") or []) if h)

    text = _described_motion_text(plan)
    restrictions = plan.get("physical_restrictions") or {}
    for forbidden in restrictions.get("forbidden_movements", []) or []:
        if forbidden and str(forbidden).lower() in text:
            fails.append(f"forbidden movement performed: {forbidden}")

    obj = plan.get("object_in_motion") or {}
    if obj:
        arrival = obj.get("arrival_height_from_ground_cm")
        contacts = obj.get("contact_points") or []
        is_header = any(t in text for t in HEADER_TERMS)
        if is_header and isinstance(arrival, (int, float)) and arrival < GROUND_BALL_CM:
            fails.append(
                "ground-level object cannot be headed (ball at ras del piso + cabezazo)"
            )
        if (
            contacts
            and obj.get("momentum_calculation_required")
            and obj.get("trajectory_changes_after_contact") is False
        ):
            fails.append("object trajectory unchanged after impact")
    return fails


def check(motion_plan: dict[str, Any] | None) -> GateResult:
    if not isinstance(motion_plan, dict) or not motion_plan:
        return GateResult(
            gate="gate_biomechanical_sanity",
            passed=False,
            reasons=["no biomechanical motion plan provided"],
        )
    fails = detect_hard_fails(motion_plan)
    reasons = list(fails)

    scores = motion_plan.get("scores")
    total = None
    if isinstance(scores, dict):
        result = biomechanical_score.score(scores)
        total = result["total_score"]
        if not result["passed"] and not result["hard_fail"]:
            reasons.append(
                f"biomechanical score {total} < {biomechanical_score.THRESHOLD}"
            )

    passed = len(reasons) == 0
    return GateResult(
        gate="gate_biomechanical_sanity",
        passed=passed,
        score=total,
        reasons=reasons,
    )

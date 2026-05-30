"""gate_production_success_probability (Sección 3.7 / 7.1).

Computes the Production Success Probability from its 7 components and blocks if
it is below 85, reporting the weakest component to fix.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult
from ..scoring import production_success_probability


def check(components: dict[str, Any] | None) -> GateResult:
    if not isinstance(components, dict) or not components:
        return GateResult(
            gate="gate_production_success_probability",
            passed=False,
            reasons=["no PSP components provided"],
        )
    result = production_success_probability.score(components)
    reasons: list[str] = []
    if not result["passed"]:
        reasons.append(
            f"PSP {result['total_score']} < {production_success_probability.THRESHOLD}; "
            f"weakest component: {result['weakest_component']}"
        )
    return GateResult(
        gate="gate_production_success_probability",
        passed=result["passed"],
        score=result["total_score"],
        reasons=reasons,
        notes=f"weakest: {result['weakest_component']}",
    )

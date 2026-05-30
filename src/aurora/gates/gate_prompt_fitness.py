"""gate_prompt_fitness (Sección 3.6 / 7.1).

Scores the prompt packet and detects contradictions/overload. Passes when the
Prompt Fitness Score >= 85 and no contradictions are declared.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult
from ..scoring import prompt_fitness_score


def check(prompt_packet: dict[str, Any] | None) -> GateResult:
    if not isinstance(prompt_packet, dict) or not prompt_packet:
        return GateResult(
            gate="gate_prompt_fitness",
            passed=False,
            reasons=["no prompt packet provided"],
        )
    result = prompt_fitness_score.score(prompt_packet)
    reasons: list[str] = []
    if not result["passed"]:
        reasons.append(
            f"prompt fitness {result['total_score']} < {prompt_fitness_score.THRESHOLD}"
        )
    contradictions = prompt_packet.get("contradictions") or []
    for c in contradictions:
        if c:
            reasons.append(f"contradiction: {c}")
    passed = len(reasons) == 0
    return GateResult(
        gate="gate_prompt_fitness",
        passed=passed,
        score=result["total_score"],
        reasons=reasons,
    )

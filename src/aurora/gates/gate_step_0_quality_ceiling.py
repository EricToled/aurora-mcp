"""gate_step_0_quality_ceiling — Gate 0 (Sección 7.2). Mandatory in v1.

Requires:
  1. benchmark_pack exists
  2. at least one Genesis or Anchor image generated
  3. visual audit completed
  4. Advertising Quality Score >= 85
If the score < 85, AURORA must change the internal Higgsfield route or block.
AURORA may not emit an Execution Pack if Gate 0 fails (unless bypassed).
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult
from ..scoring import advertising_quality_score

THRESHOLD = advertising_quality_score.THRESHOLD


def check(context: dict[str, Any]) -> GateResult:
    """context: {benchmark_pack, image_scores: [score dicts], audits: [...]}"""
    reasons: list[str] = []
    benchmark = context.get("benchmark_pack")
    if not benchmark:
        reasons.append("no benchmark_pack")

    image_scores = context.get("image_scores") or []
    if not image_scores:
        reasons.append("no Genesis/Anchor image generated and scored")

    audits = context.get("audits") or []
    if not audits:
        reasons.append("no visual audit recorded")

    best = 0
    hard_failed = False
    for s in image_scores:
        if s.get("hard_fail"):
            hard_failed = True
        best = max(best, int(s.get("total_score", 0)))
    if image_scores and best < THRESHOLD:
        reasons.append(f"best Advertising Quality Score {best} < {THRESHOLD}")
    if hard_failed:
        reasons.append("an image scored a hard fail — change internal route")

    passed = not reasons
    return GateResult(
        gate="gate_step_0_quality_ceiling",
        passed=passed,
        score=best if image_scores else None,
        reasons=reasons,
    )

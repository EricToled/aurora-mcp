"""AURORA quality scoring (Sección 3).

Every scorer takes a dict of per-criterion values in [0, 100] (missing criteria
default to 0) plus an optional ``hard_fails`` list, and returns a uniform result
dict via ``weighted_score``. Weights per score type sum to 100, so the weighted
total is itself on a 0-100 scale.
"""
from __future__ import annotations

from typing import Any


def weighted_score(
    score_type: str,
    weights: dict[str, int],
    data: dict[str, Any],
    threshold: int,
) -> dict[str, Any]:
    """Compute a weighted 0-100 total from per-criterion values.

    data may contain criterion keys (0-100) and a ``hard_fails`` list. Any
    non-empty hard_fails entry forces ``passed=False`` and total=0.
    """
    hard_fails = [h for h in (data.get("hard_fails") or []) if h]
    breakdown: dict[str, dict[str, float]] = {}
    total = 0.0
    for criterion, weight in weights.items():
        raw = data.get(criterion, 0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(100.0, value))
        weighted = value * weight / 100.0
        breakdown[criterion] = {
            "value": value,
            "weight": weight,
            "weighted": round(weighted, 3),
        }
        total += weighted

    total_int = int(round(total))
    hard_fail = len(hard_fails) > 0
    hard_fail_reason = "; ".join(hard_fails) if hard_fail else None
    if hard_fail:
        total_int = 0
    passed = (not hard_fail) and total_int >= threshold
    return {
        "score_type": score_type,
        "total_score": total_int,
        "threshold": threshold,
        "passed": passed,
        "hard_fail": hard_fail,
        "hard_fail_reason": hard_fail_reason,
        "breakdown": breakdown,
    }

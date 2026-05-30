"""Production Success Probability (Sección 3.7).

PSP = 0.20*GateCompliance + 0.15*RouteVerification + 0.15*BenchmarkMatch
      + 0.15*AnchorQuality + 0.15*BiomechanicalPlausibility
      + 0.10*ContinuityReadiness + 0.10*PromptFitness

Each component is a 0-100 score. If PSP < 85 AURORA must not generate; the
weakest component is reported so the caller knows what to fix.
"""
from __future__ import annotations

from typing import Any

THRESHOLD = 85
COMPONENT_WEIGHTS = {
    "gate_compliance": 0.20,
    "route_verification": 0.15,
    "benchmark_match": 0.15,
    "anchor_quality": 0.15,
    "biomechanical_plausibility": 0.15,
    "continuity_readiness": 0.10,
    "prompt_fitness": 0.10,
}


def score(data: dict[str, Any]) -> dict[str, Any]:
    breakdown: dict[str, dict[str, float]] = {}
    total = 0.0
    for component, weight in COMPONENT_WEIGHTS.items():
        raw = data.get(component, 0)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(100.0, value))
        weighted = value * weight
        breakdown[component] = {
            "value": value,
            "weight": weight,
            "weighted": round(weighted, 3),
        }
        total += weighted

    total_int = int(round(total))
    weakest = min(breakdown.items(), key=lambda kv: kv[1]["value"])[0]
    passed = total_int >= THRESHOLD
    return {
        "score_type": "production_probability",
        "total_score": total_int,
        "threshold": THRESHOLD,
        "passed": passed,
        "weakest_component": weakest,
        "breakdown": breakdown,
    }

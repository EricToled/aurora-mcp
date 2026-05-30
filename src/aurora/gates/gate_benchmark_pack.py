"""gate_benchmark_pack (Sección 7.1 / 12.1).

A benchmark pack must exist with at least one reference (url_or_path) and an
acceptance threshold before prompts/routes are produced.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult


def check(pack: dict[str, Any] | None) -> GateResult:
    reasons: list[str] = []
    if not isinstance(pack, dict) or not pack:
        return GateResult(
            gate="gate_benchmark_pack",
            passed=False,
            reasons=["no benchmark pack provided"],
        )
    refs = pack.get("references")
    if not isinstance(refs, list) or len(refs) == 0:
        reasons.append("benchmark pack has no references")
    else:
        for idx, ref in enumerate(refs):
            if not isinstance(ref, dict) or not str(ref.get("url_or_path", "")).strip():
                reasons.append(f"reference[{idx}] missing url_or_path")
    threshold = pack.get("acceptance_threshold", 85)
    if not isinstance(threshold, (int, float)):
        reasons.append("acceptance_threshold must be numeric")
    if not pack.get("forbidden_traits"):
        # Not blocking, but worth noting.
        pass
    passed = not reasons
    return GateResult(gate="gate_benchmark_pack", passed=passed, reasons=reasons)

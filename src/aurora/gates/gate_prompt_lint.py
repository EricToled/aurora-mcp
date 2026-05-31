"""Gate: deterministic prompt lint (refs redundancy + sections + structure).

This gate is NOT in the mode's always-required set — it only applies when a
prompt is actually linted (it needs a case/platform/refs the generic modes don't
carry). But once a lint is recorded, emit treats a FAIL as blocking: a prompt
that re-describes its refs, misses a required section, or breaks the word/negative
structure must not reach delivery. Mirrors the old aurora-prompt-linter Step 5b.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult

GATE_NAME = "gate_prompt_lint"


def check(lint_result: dict[str, Any] | None) -> GateResult:
    """``lint_result`` is the dict returned by scoring.prompt_lint.lint()."""
    if not lint_result:
        return GateResult(
            gate=GATE_NAME, passed=False, blocking=True,
            reasons=["No lint result provided — run aurora_lint_prompt first."],
        )
    status = lint_result.get("status")
    violations = lint_result.get("violations", []) or []
    passed = status == "PASS"
    reasons = (
        ["Prompt lint PASS — no blocking violations."]
        if passed
        else [f"[{v.get('category')}] {v.get('term')}: {v.get('reason')}" for v in violations]
        or ["Prompt lint FAIL."]
    )
    return GateResult(
        gate=GATE_NAME,
        passed=passed,
        blocking=True,
        reasons=reasons,
        notes=lint_result.get("report", ""),
    )

"""Gate: the Decision Sheet must be approved by the operator before delivery.

Conditional gate (like gate_prompt_lint): it is NOT in the mode's always-required
set and NOT in gates.GATE_MODULES, but emit hard-blocks for content modes when no
APPROVED Decision Sheet exists. This is the teeth behind "Claude no puede escribir
el Execution Pack entero sin aprobación": every creative decision Claude proposed
(age, build, geometry, lens, duration, PSP…) must be signed off by the operator —
with the operator token — before any prompt is sealed for delivery.
"""
from __future__ import annotations

from typing import Any

from .. import decision_sheet
from ..models import GateResult

GATE_NAME = "gate_decision_sheet_approved"


def check(sheet: dict[str, Any] | None) -> GateResult:
    """``sheet`` is the dict stored as the project's ``decision_sheet`` artifact."""
    if not sheet:
        return GateResult(
            gate=GATE_NAME, passed=False, blocking=True,
            reasons=[
                "No hay Decision Sheet. Crea uno (aurora_create_decision_sheet) "
                "con cada decisión de personaje/locación/cinema/estimado y pide "
                "aprobación del operador antes de entregar prompts."
            ],
        )
    if decision_sheet.is_approved(sheet):
        return GateResult(
            gate=GATE_NAME, passed=True, blocking=True,
            reasons=["Decision Sheet aprobado por el operador."],
        )
    pend = decision_sheet.pending_decisions(sheet)
    reasons = [
        f"pendiente de aprobación: {d['id']} = {d.get('value')!r} (source={d['source']})"
        for d in pend
    ] or ["Decision Sheet sin aprobación autenticada del operador."]
    return GateResult(gate=GATE_NAME, passed=False, blocking=True, reasons=reasons)

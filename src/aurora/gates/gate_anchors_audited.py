"""gate_anchors_audited (Sección 7.1).

All required anchors must be audited and approved before generation. Passes when
anchors_approved_count >= anchors_required_count and every audited anchor passed.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult


def check(anchor_state: dict[str, Any]) -> GateResult:
    reasons: list[str] = []
    required = int(anchor_state.get("anchors_required_count", 0))
    approved = int(anchor_state.get("anchors_approved_count", 0))
    if required > 0 and approved < required:
        reasons.append(f"{approved}/{required} anchors approved")
    for audit in anchor_state.get("anchor_audits", []) or []:
        if audit.get("verdict") == "fail":
            reasons.append(
                f"anchor {audit.get('higgsfield_element_id', '?')} failed audit"
            )
    passed = not reasons
    return GateResult(
        gate="gate_anchors_audited",
        passed=passed,
        score=approved,
        reasons=reasons,
    )

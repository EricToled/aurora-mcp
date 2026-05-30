"""gate_domain_session_lock (Sección 4.3).

AURORA cannot create prompts or routes until a valid domain_session_lock exists:
a non-empty domain + sub_domain and a valid project_scope.
"""
from __future__ import annotations

from typing import Any

from ..models import GateResult

VALID_SCOPES = {"image", "video_simple", "video_multishot"}


def check(lock: dict[str, Any] | None) -> GateResult:
    reasons: list[str] = []
    if not isinstance(lock, dict) or not lock:
        return GateResult(
            gate="gate_domain_session_lock",
            passed=False,
            reasons=["no domain_session_lock provided"],
        )
    if not str(lock.get("domain", "")).strip():
        reasons.append("domain is empty")
    if not str(lock.get("sub_domain", "")).strip():
        reasons.append("sub_domain is empty — session subdomain must be closed")
    scope = lock.get("project_scope")
    if scope not in VALID_SCOPES:
        reasons.append(f"project_scope invalid: {scope!r}")
    passed = not reasons
    return GateResult(
        gate="gate_domain_session_lock",
        passed=passed,
        reasons=reasons,
        notes="domain session locked" if passed else "",
    )

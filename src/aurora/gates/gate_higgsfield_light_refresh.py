"""gate_higgsfield_light_refresh (Sección 5).

A light refresh must run at the start of each project before route planning.
The gate passes when a capability snapshot of an acceptable scope exists and is
still inside its TTL (model list TTL = 24h, Sección 5.3).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from ..models import GateResult

ACCEPTABLE_SCOPES = {"light_session", "model_schema", "full_monthly", "ui_partial"}
MODEL_LIST_TTL_HOURS = 24


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def check(snapshot: dict[str, Any] | None, now: Optional[datetime] = None) -> GateResult:
    now = now or datetime.now(timezone.utc)
    if not isinstance(snapshot, dict) or not snapshot:
        return GateResult(
            gate="gate_higgsfield_light_refresh",
            passed=False,
            reasons=["no capability snapshot — run aurora_refresh_higgsfield_capabilities"],
        )
    scope = snapshot.get("refresh_scope")
    reasons: list[str] = []
    if scope not in ACCEPTABLE_SCOPES:
        reasons.append(f"refresh_scope not acceptable: {scope!r}")
    created = snapshot.get("created_at")
    dt = _parse_iso(created) if isinstance(created, str) else None
    if dt is None:
        reasons.append("snapshot has no parseable created_at")
    else:
        age_h = (now - dt).total_seconds() / 3600.0
        if age_h > MODEL_LIST_TTL_HOURS:
            reasons.append(f"snapshot stale ({age_h:.1f}h > {MODEL_LIST_TTL_HOURS}h TTL)")
    passed = not reasons
    return GateResult(
        gate="gate_higgsfield_light_refresh",
        passed=passed,
        reasons=reasons,
    )

"""AURORA bypass handler — operator sovereignty (Sprint 1, full impl).

Parses operator override syntax, validates it, and logs accepted bypasses to
SQLite. Persist-scoped bypasses are tracked in ~/.aurora/session_state.json.

Bypass syntax (spec Section F):
  OVERRIDE: <component> - <reason>            current_turn
  OVERRIDE PERSIST: <component> - <reason>    persist (until revoked)
  REVOKE OVERRIDE: <component>                revoke a persist bypass
  BYPASS AURORA - <reason>                    component='all', current_turn
  /override <component> - <reason>            slash equivalent of OVERRIDE
  /bypass-all - <reason>                      slash equivalent of BYPASS AURORA
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel

from . import db

# Operator sovereignty (Sección F/K): ANY gate that can block Execution Pack
# emission must be bypassable. These are the canonical gate names — they MUST
# stay in sync with gates.GATE_MODULES (the test_coherence meta-test enforces
# this). evaluate_gates() looks up active bypasses by these exact names.
GATE_COMPONENTS = frozenset({
    "gate_domain_session_lock",
    "gate_higgsfield_light_refresh",
    "gate_preproduction_packet",
    "gate_benchmark_pack",
    "gate_route_verification",
    "gate_step_0_quality_ceiling",
    "gate_anchors_audited",
    "gate_biomechanical_sanity",
    "gate_prompt_fitness",
    "gate_multishot_anchor_strategy",
    "gate_continuity_readiness",
    "gate_upscale_finishing_route",
    "gate_production_success_probability",
    "gate_platform_syntax_researched",
})

# Pipeline steps that are bypassable but are not Execution-Pack gates.
NON_GATE_COMPONENTS = frozenset({
    "model_selection",
    "theme_resolver",
})

# Legacy Sprint-1 names kept accepted; each maps to the canonical gate it now
# corresponds to so an old OVERRIDE directive still bypasses the right gate.
LEGACY_ALIASES = {
    "gate_step_0": "gate_step_0_quality_ceiling",
    "gate_continuity_anchors": "gate_anchors_audited",
    "biomechanical_check": "gate_biomechanical_sanity",
    "prompt_linter": "gate_prompt_fitness",
    "router_ui_vs_mcp": "gate_route_verification",
    "tribal_mining_freshness": "gate_higgsfield_light_refresh",
}

BYPASSABLE_COMPONENTS = (
    GATE_COMPONENTS
    | NON_GATE_COMPONENTS
    | frozenset(LEGACY_ALIASES)
    | {"all"}
)


def canonical_component(component: str) -> str:
    """Map a legacy alias to the canonical gate name; pass others through.

    The Execution Pack evaluates bypasses by canonical gate name, so a bypass
    must be stored under the canonical name to actually take effect."""
    return LEGACY_ALIASES.get(component, component)

SESSION_STATE_PATH = Path.home() / ".aurora" / "session_state.json"

# Regexes exactly as specified in Section K. Order matters: more specific
# (PERSIST / REVOKE) must be checked before the generic OVERRIDE form.
_RE_OVERRIDE_PERSIST = re.compile(r"OVERRIDE PERSIST:\s*([\w_]+)\s*-\s*(.+?)(?:\n|$)")
_RE_REVOKE = re.compile(r"REVOKE OVERRIDE:\s*([\w_]+)")
_RE_OVERRIDE = re.compile(r"OVERRIDE:\s*([\w_]+)\s*-\s*(.+?)(?:\n|$)")
_RE_BYPASS_AURORA = re.compile(r"BYPASS AURORA\s*-\s*(.+?)(?:\n|$)")
_RE_SLASH_OVERRIDE = re.compile(r"/override\s+([\w_]+)\s*-\s*(.+?)(?:\n|$)")
_RE_SLASH_BYPASS_ALL = re.compile(r"/bypass-all\s*-\s*(.+?)(?:\n|$)")


class BypassDirective(BaseModel):
    component: str
    reason: str
    scope: Literal["current_turn", "persist", "all_session"]
    revoke: bool = False
    detected_in_text: str


def _valid(component: str, reason: str) -> bool:
    if component not in BYPASSABLE_COMPONENTS:
        return False
    if not reason or not reason.strip():
        return False
    return True


def parse_bypass(operator_text: str) -> Optional[BypassDirective]:
    """Parse the first valid bypass directive in operator_text, else None.

    Invalid component or empty reason => None (silent reject per spec).
    """
    if not operator_text:
        return None

    # 1. REVOKE OVERRIDE — no reason required, component must be valid.
    m = _RE_REVOKE.search(operator_text)
    if m:
        component = m.group(1).strip()
        if component in BYPASSABLE_COMPONENTS:
            return BypassDirective(
                component=component,
                reason="revoke",
                scope="persist",
                revoke=True,
                detected_in_text=m.group(0).strip(),
            )
        return None

    # 2. OVERRIDE PERSIST
    m = _RE_OVERRIDE_PERSIST.search(operator_text)
    if m:
        component, reason = m.group(1).strip(), m.group(2).strip()
        if _valid(component, reason):
            return BypassDirective(
                component=component,
                reason=reason,
                scope="persist",
                detected_in_text=m.group(0).strip(),
            )
        return None

    # 3. BYPASS AURORA (full system, current turn)
    m = _RE_BYPASS_AURORA.search(operator_text)
    if m:
        reason = m.group(1).strip()
        if _valid("all", reason):
            return BypassDirective(
                component="all",
                reason=reason,
                scope="current_turn",
                detected_in_text=m.group(0).strip(),
            )
        return None

    # 4. /bypass-all
    m = _RE_SLASH_BYPASS_ALL.search(operator_text)
    if m:
        reason = m.group(1).strip()
        if _valid("all", reason):
            return BypassDirective(
                component="all",
                reason=reason,
                scope="current_turn",
                detected_in_text=m.group(0).strip(),
            )
        return None

    # 5. /override <component> - <reason>
    m = _RE_SLASH_OVERRIDE.search(operator_text)
    if m:
        component, reason = m.group(1).strip(), m.group(2).strip()
        if _valid(component, reason):
            return BypassDirective(
                component=component,
                reason=reason,
                scope="current_turn",
                detected_in_text=m.group(0).strip(),
            )
        return None

    # 6. OVERRIDE: <component> - <reason>  (generic, checked last)
    m = _RE_OVERRIDE.search(operator_text)
    if m:
        component, reason = m.group(1).strip(), m.group(2).strip()
        if _valid(component, reason):
            return BypassDirective(
                component=component,
                reason=reason,
                scope="current_turn",
                detected_in_text=m.group(0).strip(),
            )
        return None

    return None


def log_bypass(
    directive: BypassDirective,
    project_id: Optional[str] = None,
    related_job_id: Optional[str] = None,
    db_path: Optional[str] = None,
    authorized: bool = False,
) -> str:
    """Write a bypass directive to the SQLite bypass_log. Returns bypass_id.

    persist-scoped directives also update the session state file.

    Only AUTHORIZED bypasses (accompanied by a valid operator token) take effect:
    an unauthorized directive is still written to the audit trail but is never
    promoted to a persist bypass and is filtered out at read time, so Claude
    cannot forge operator consent to skip a gate (anti-invention).
    """
    scope = directive.scope
    if scope == "persist" and not directive.revoke and authorized:
        _set_persist_bypass(directive.component, directive.reason)

    bypass_id = db.insert_bypass_log(
        operator_turn_text=directive.detected_in_text,
        component_bypassed=directive.component,
        reason=directive.reason,
        scope=scope,
        db_path=db_path,
        project_id=project_id,
        related_job_id=related_job_id,
        job_outcome="pending",
        authorized=authorized,
    )
    return bypass_id


# ---------------------------------------------------------------------------
# Session state (persist bypasses)
# ---------------------------------------------------------------------------
def _load_session_state() -> dict:
    if not SESSION_STATE_PATH.exists():
        return {"persist_bypasses": {}}
    try:
        return json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"persist_bypasses": {}}


def _save_session_state(state: dict) -> None:
    SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _set_persist_bypass(component: str, reason: str) -> None:
    state = _load_session_state()
    state.setdefault("persist_bypasses", {})[component] = reason
    _save_session_state(state)


def revoke_persist_bypass(component: str) -> None:
    state = _load_session_state()
    state.setdefault("persist_bypasses", {}).pop(component, None)
    _save_session_state(state)


def is_component_bypassed(component: str, session_state: dict) -> bool:
    """True if the component (or 'all') is bypassed in the given session_state.

    session_state is a dict shaped like:
        {"current_turn": ["gate_x", ...], "persist_bypasses": {"gate_y": "reason"}}
    A bypass on 'all' covers every component.
    """
    current = set(session_state.get("current_turn", []) or [])
    persist = set((session_state.get("persist_bypasses", {}) or {}).keys())
    active = current | persist
    return component in active or "all" in active

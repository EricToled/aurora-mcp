"""Decision Sheet — the creative-decisions deliverable the operator must approve
BEFORE AURORA will seal an Execution Pack (anti-invención, Fase 1).

The point (per Eric's review of the last exercise): Claude legitimately PROPOSES
details the brief never specified — a character's age, a location's geometry, a
lens, a shot duration, a PSP estimate. That is fine on its own. What is NOT fine
is delivering 40+ executable prompts built on those proposals without the operator
ever signing off. The Decision Sheet makes every proposed-vs-specified decision
explicit and forces an approval checkpoint:

  * each decision carries a ``source`` — operator | claude | research,
  * a decision is PENDING until the operator approves it (claude/research) or it
    was operator-specified to begin with,
  * the sheet counts as APPROVED only when the operator runs the authenticated
    approval AND zero decisions remain pending.

This module is pure (no I/O); the server tools persist/read the sheet artifact.
"""
from __future__ import annotations

from typing import Any

SOURCE_OPERATOR = "operator"
SOURCE_CLAUDE = "claude"
SOURCE_RESEARCH = "research"
VALID_SOURCES = (SOURCE_OPERATOR, SOURCE_CLAUDE, SOURCE_RESEARCH)


def _make_id(category: str, item: str, field: str) -> str:
    return ".".join(p for p in (category, item, field) if p) or "decision"


def normalize_decisions(decisions: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Coerce raw decision dicts into the canonical shape and stamp ids.

    Operator-sourced decisions are auto-approved (there is nothing for Claude to
    have invented); everything else starts un-approved (PENDING).
    """
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for d in decisions or []:
        category = str(d.get("category", "")).strip() or "general"
        item = str(d.get("item", "")).strip()
        field = str(d.get("field", "")).strip() or "value"
        source = str(d.get("source", SOURCE_CLAUDE)).strip().lower()
        if source not in VALID_SOURCES:
            source = SOURCE_CLAUDE
        did = str(d.get("id") or _make_id(category, item, field))
        # de-duplicate ids so targeted approval is unambiguous
        if did in seen:
            seen[did] += 1
            did = f"{did}#{seen[did]}"
        else:
            seen[did] = 0
        approved = bool(d.get("approved")) or source == SOURCE_OPERATOR
        row = {
            "id": did,
            "category": category,
            "item": item,
            "field": field,
            "value": d.get("value"),
            "source": source,
            "approved": approved,
        }
        # Preserve genesis-deviation metadata (R11) so the platform-genesis
        # policy survives normalization and reaches emit / approval.
        if d.get("platform_genesis_deviation") is not None:
            row["platform_genesis_deviation"] = d["platform_genesis_deviation"]
        if d.get("rationale") is not None:
            row["rationale"] = d["rationale"]
        out.append(row)
    return out


def pending_decisions(sheet: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Decisions still awaiting operator approval."""
    if not sheet:
        return []
    return [d for d in sheet.get("decisions", []) if not d.get("approved")]


def is_approved(sheet: dict[str, Any] | None) -> bool:
    """A sheet is approved only when the operator actively approved it (the
    authenticated approval sets ``operator_approved``) AND nothing is pending.

    Requiring the explicit flag closes a gaming hole: an empty or all-operator
    sheet must still pass through the token-authenticated approval tool, so Claude
    cannot fabricate an 'approved' sheet to unblock emit on its own.
    """
    if not sheet:
        return False
    return bool(sheet.get("operator_approved")) and not pending_decisions(sheet)


def apply_approval(
    sheet: dict[str, Any],
    approve: Any = "all",
    edits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply operator edits + approvals to a sheet (mutates and returns it).

    ``edits``: list of ``{id, value?}`` — an edited decision becomes operator-owned
    and approved. ``approve``: ``"all"``/``True`` approves every decision, or a list
    of decision ids to approve selectively.
    """
    decisions = sheet.get("decisions", [])
    by_id = {d["id"]: d for d in decisions}
    for e in edits or []:
        d = by_id.get(e.get("id"))
        if not d:
            continue
        if "value" in e:
            d["value"] = e["value"]
        d["source"] = SOURCE_OPERATOR
        d["approved"] = True
    if approve == "all" or approve is True:
        for d in decisions:
            d["approved"] = True
    elif approve:
        targets = set(approve if isinstance(approve, (list, tuple, set)) else [approve])
        for d in decisions:
            if d["id"] in targets:
                d["approved"] = True
    # An approved genesis-routing deviation is, by definition, operator
    # acknowledged — the authenticated approval IS the acknowledgement (R11).
    for d in decisions:
        dev = d.get("platform_genesis_deviation")
        if d.get("approved") and isinstance(dev, dict):
            dev["operator_acknowledged"] = True
    sheet["operator_approved"] = not pending_decisions(sheet)
    return sheet


def summarize(sheet: dict[str, Any] | None) -> dict[str, Any]:
    """A compact view for tool responses / reports."""
    decisions = (sheet or {}).get("decisions", [])
    pend = pending_decisions(sheet)
    return {
        "total": len(decisions),
        "pending": [
            {"id": d["id"], "value": d.get("value"), "source": d["source"]}
            for d in pend
        ],
        "approved": is_approved(sheet),
        "proposed_by_claude": sum(1 for d in decisions if d["source"] == SOURCE_CLAUDE),
        "from_research": sum(1 for d in decisions if d["source"] == SOURCE_RESEARCH),
        "operator_specified": sum(1 for d in decisions if d["source"] == SOURCE_OPERATOR),
    }

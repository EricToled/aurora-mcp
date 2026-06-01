"""genesis_policy — deterministic policy for the DEFAULT genesis image model
(GPT Image 2) and the operator-authorized deviation flow (R11).

Eric's rule: genesis stills (character portraits and studio-backdrop locations)
default to **gpt_image_2**. Claude may route to a different model, but only when
the Decision Sheet carries an explicit ``platform_genesis_deviation`` that the
operator has acknowledged AND whose rationale survives the whitelist. This stops
Claude from silently swapping in a "cinematic" model "because it prefers it".

This module is pure (no I/O). The server tools (create/approve Decision Sheet,
emit) call these helpers; emit hard-blocks unauthorized deviations.
"""
from __future__ import annotations

from typing import Any

# The single default genesis model. Everything else is a *deviation*.
PRIMARY_GENESIS_DEFAULT = "gpt_image_2"

# Per-genesis-kind default + fallback chain (spec §2.1). The primary is always
# gpt_image_2; the rest is the ordered fallback if the primary is unavailable.
GENESIS_ROUTING_DEFAULTS: dict[str, dict[str, Any]] = {
    "image_anchor_character_portrait": {
        "primary": PRIMARY_GENESIS_DEFAULT,
        "fallback": ["soul_cinematic", "cinematic_studio_image_2_5", "seedream_v4_5"],
    },
    "image_anchor_location_studio_backdrop": {
        "primary": PRIMARY_GENESIS_DEFAULT,
        "fallback": ["nano_banana_pro", "flux_2", "cinematic_studio_image_2_5"],
    },
}

# Whitelisted reasons that JUSTIFY deviating from gpt_image_2 (spec §2.2). A
# deviation rationale is auto-accepted when it clearly invokes one of these.
VALID_DEVIATION_REASONS: tuple[str, ...] = (
    "operator explicitly requested a specific non-default model",
    "gpt_image_2 cannot render required on-image text or packaging typography",
    "a real-person identity anchor requires soul_id consent-trained likeness",
    "an approved Higgsfield reference element must drive the anchor",
    "gpt_image_2 does not support the required aspect ratio or resolution for this shot",
    "gpt_image_2 is unavailable or failed verification at route-check time",
)

# Generic non-reasons that must be REJECTED outright (spec §2.2). These are the
# excuses Claude tends to invent; they never authorize a deviation.
INVALID_DEVIATION_REASONS: tuple[str, ...] = (
    "cinematic look",
    "premium quality",
    "photorealistic",
    "claude prefers it",
)

# A rationale must clear this length to count as a "strong reason" when it does
# not literally match a whitelist entry.
_MIN_REASON_LEN = 40

# Keyword fingerprints for each whitelisted reason — a rationale that mentions
# enough of these is treated as invoking that reason.
_VALID_REASON_KEYWORDS: tuple[tuple[str, ...], ...] = (
    ("operator", "request"),
    ("text",),
    ("packaging",),
    ("typography",),
    ("soul_id",),
    ("consent",),
    ("real person", "identity"),
    ("reference element",),
    ("higgsfield", "element"),
    ("aspect ratio",),
    ("resolution",),
    ("unavailable",),
    ("failed verification",),
)


def is_genesis_routing_decision(d: dict[str, Any]) -> bool:
    """True when a Decision Sheet row selects the MODEL for a genesis image.

    We key off the canonical shape: category beginning ``model_routing`` and an
    item that names a genesis/anchor element. This is deliberately permissive on
    the item wording so operators can phrase it naturally.
    """
    category = str(d.get("category", "")).strip().lower()
    item = str(d.get("item", "")).strip().lower()
    field = str(d.get("field", "")).strip().lower()
    if not category.startswith("model_routing"):
        return False
    if "model" not in field and field != "value":
        return False
    return "genesis" in item or "anchor" in item


def _norm(text: Any) -> str:
    return str(text or "").strip().lower()


def reason_is_acceptable(reason: Any) -> bool:
    """Deterministic verdict on a deviation rationale.

    Accept when the rationale invokes a whitelisted reason (literal substring or
    keyword fingerprint). Reject empty rationales, anything shorter than
    :data:`_MIN_REASON_LEN`, and anything that is merely one of the generic
    non-reasons in :data:`INVALID_DEVIATION_REASONS`.
    """
    r = _norm(reason)
    if not r:
        return False
    # Hard reject the generic excuses, even if padded with filler.
    for bad in INVALID_DEVIATION_REASONS:
        if r == bad or r.strip(".! ") == bad:
            return False
    # Literal whitelist match.
    for good in VALID_DEVIATION_REASONS:
        if good in r:
            return True
    # Keyword-fingerprint match: every keyword in any group present.
    for group in _VALID_REASON_KEYWORDS:
        if all(kw in r for kw in group):
            return True
    # Otherwise it must at least be a substantial, specific statement AND not be
    # dominated by a generic excuse.
    if len(r) < _MIN_REASON_LEN:
        return False
    for bad in INVALID_DEVIATION_REASONS:
        if bad in r:
            return False
    return False


def _deviation_block(d: dict[str, Any]) -> dict[str, Any] | None:
    dev = d.get("platform_genesis_deviation")
    return dev if isinstance(dev, dict) else None


def genesis_deviation_problems(sheet: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return blocking problems for every genesis routing decision that deviates
    from gpt_image_2 without proper authorization.

    A deviation is a problem when ANY of:
      * no ``platform_genesis_deviation`` block is attached,
      * the operator has not acknowledged it,
      * its rationale fails :func:`reason_is_acceptable`.
    """
    problems: list[dict[str, Any]] = []
    for d in (sheet or {}).get("decisions", []):
        if not is_genesis_routing_decision(d):
            continue
        chosen = _norm(d.get("value"))
        if not chosen or chosen == PRIMARY_GENESIS_DEFAULT:
            continue  # using the default — nothing to authorize
        dev = _deviation_block(d)
        rationale = (d.get("rationale") or (dev or {}).get("rationale") or "")
        if not dev:
            problems.append({
                "id": d.get("id"),
                "chosen_model": chosen,
                "problem": "missing_deviation_flag",
                "detail": f"genesis routing chose {chosen!r} instead of "
                          f"{PRIMARY_GENESIS_DEFAULT!r} but no platform_genesis_deviation "
                          f"block is attached",
            })
            continue
        if not dev.get("operator_acknowledged"):
            problems.append({
                "id": d.get("id"),
                "chosen_model": chosen,
                "problem": "not_acknowledged",
                "detail": "platform_genesis_deviation is not operator_acknowledged",
            })
            continue
        if not reason_is_acceptable(rationale):
            problems.append({
                "id": d.get("id"),
                "chosen_model": chosen,
                "problem": "weak_reason",
                "detail": "deviation rationale does not match the accepted whitelist "
                          "(generic excuses like 'cinematic look' / 'premium quality' "
                          "are rejected)",
            })
    return problems


def authorized_genesis_deviations(sheet: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Genesis deviations that ARE fully authorized (for the audit trail)."""
    authorized: list[dict[str, Any]] = []
    for d in (sheet or {}).get("decisions", []):
        if not is_genesis_routing_decision(d):
            continue
        chosen = _norm(d.get("value"))
        if not chosen or chosen == PRIMARY_GENESIS_DEFAULT:
            continue
        dev = _deviation_block(d)
        if not dev or not dev.get("operator_acknowledged"):
            continue
        rationale = (d.get("rationale") or dev.get("rationale") or "")
        if reason_is_acceptable(rationale):
            authorized.append({
                "id": d.get("id"),
                "chosen_model": chosen,
                "recommended_model": dev.get("recommended_model", PRIMARY_GENESIS_DEFAULT),
                "rationale": str(rationale),
            })
    return authorized


def inject_deviation_skeletons(
    decisions: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """For any genesis routing decision that deviates from the default, attach an
    un-acknowledged ``platform_genesis_deviation`` skeleton so the operator is
    forced to see and sign it. Idempotent: existing blocks are left intact.
    """
    out: list[dict[str, Any]] = []
    for d in decisions or []:
        d = dict(d)
        if is_genesis_routing_decision(d):
            chosen = _norm(d.get("value"))
            if chosen and chosen != PRIMARY_GENESIS_DEFAULT and not _deviation_block(d):
                d["platform_genesis_deviation"] = {
                    "deviates": True,
                    "recommended_model": PRIMARY_GENESIS_DEFAULT,
                    "chosen_model": chosen,
                    "strong_reason_required": True,
                    "operator_acknowledged": False,
                    "rationale": str(d.get("rationale") or ""),
                }
        out.append(d)
    return out

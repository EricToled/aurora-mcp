"""Prompt Fitness Score (Sección 3.6). Pass >= 85.

Accepts two input shapes and treats them uniformly:

  * rubric shape  — each of the nine WEIGHTS keys already holds a 0-100 number
    (what aurora_record_quality_score(score_type="prompt") supplies).
  * packet shape  — a rich prompt packet (model, camera dict, booleans like
    ``physics_clear``, ``negative_constraints`` list, ``prompt_final`` text).
    ``criteria_from_packet`` maps it to the nine rubric values heuristically so
    a reasonably complete packet scores high instead of silently scoring ~1
    (bug #7: ``float(True)`` is 1.0, not 100, so booleans must be normalized).
"""
from __future__ import annotations

from typing import Any

from . import weighted_score

THRESHOLD = 85
WEIGHTS = {
    "model_correct": 15,
    "model_syntax_correct": 15,
    "single_dominant_action": 15,
    "references_correct": 10,
    "camera_clear": 10,
    "physics_clear": 10,
    "visual_style_clear": 10,
    "negative_constraints_useful": 5,
    "no_overload_or_contradiction": 10,
}

EVALUATOR_VERSION = "prompt_fitness/2.2"


def _as_value(raw: Any) -> int | None:
    """Normalize a packet field to a 0-100 score. bool -> 100/0, number ->
    clamped, anything else -> None (so a heuristic can decide)."""
    if isinstance(raw, bool):
        return 100 if raw else 0
    if isinstance(raw, (int, float)):
        return int(max(0.0, min(100.0, float(raw))))
    return None


def _single_action_score(action: Any) -> int:
    if not isinstance(action, str) or not action.strip():
        return 0
    # One coordinated action is fine; several "and"-joined verbs read as overload.
    return 100 if action.lower().count(" and ") <= 1 else 60


def criteria_from_packet(packet: dict[str, Any]) -> dict[str, int]:
    """Derive the nine rubric criteria (0-100) from a rich prompt packet.

    A field already holding a number/bool is used directly; otherwise a
    structural heuristic fills it in. Accepts both the spec field names
    (``syntax_correct``, ``no_overload_no_contradictions``) and the rubric key
    names so either vocabulary works.
    """
    p = packet or {}

    def pick(*keys: str) -> int | None:
        for k in keys:
            if k in p:
                v = _as_value(p[k])
                if v is not None:
                    return v
        return None

    crit: dict[str, int] = {}

    model_v = pick("model_correct")
    crit["model_correct"] = model_v if model_v is not None else (100 if p.get("model") else 0)

    syntax_v = pick("model_syntax_correct", "syntax_correct")
    prompt_final = p.get("prompt_final") or ""
    crit["model_syntax_correct"] = (
        syntax_v if syntax_v is not None else (100 if str(prompt_final).strip() else 0)
    )

    sda_v = pick("single_dominant_action")
    crit["single_dominant_action"] = (
        sda_v if sda_v is not None else _single_action_score(p.get("action"))
    )

    refs_v = pick("references_correct")
    subject = p.get("subject") or []
    if not isinstance(subject, list):
        subject = [subject]
    has_tags = any(isinstance(s, str) and s.strip().startswith("@") for s in subject)
    crit["references_correct"] = refs_v if refs_v is not None else (100 if has_tags else 0)

    cam_v = pick("camera_clear")
    cam = p.get("camera") or {}
    cam_full = isinstance(cam, dict) and all(
        cam.get(k) for k in ("body", "focal_mm", "movement", "aspect_ratio")
    )
    crit["camera_clear"] = (
        cam_v if cam_v is not None else (100 if cam_full else (50 if cam else 0))
    )

    phys_v = pick("physics_clear")
    crit["physics_clear"] = (
        phys_v if phys_v is not None else (100 if p.get("biomechanical_motion_plan_id") else 0)
    )

    style_v = pick("visual_style_clear")
    look = p.get("look") or p.get("style_palette")
    crit["visual_style_clear"] = style_v if style_v is not None else (100 if look else 0)

    negs = p.get("negative_constraints") or []
    n = len(negs) if isinstance(negs, list) else 0
    crit["negative_constraints_useful"] = 100 if n >= 3 else (60 if n >= 1 else 0)

    overload_v = pick("no_overload_or_contradiction", "no_overload_no_contradictions")
    contradictions = [c for c in (p.get("contradictions") or []) if c]
    overloaded = len(str(prompt_final)) > 600
    if contradictions or overloaded:
        crit["no_overload_or_contradiction"] = 0
    else:
        crit["no_overload_or_contradiction"] = overload_v if overload_v is not None else 100

    return crit


def _has_rubric_scores(data: dict[str, Any]) -> bool:
    """True when the input already carries explicit numeric rubric scores for at
    least half the criteria (the record_quality_score path)."""
    numeric = sum(
        1
        for k in WEIGHTS
        if isinstance(data.get(k), (int, float)) and not isinstance(data.get(k), bool)
    )
    return numeric >= (len(WEIGHTS) + 1) // 2


def score(data: dict[str, Any]) -> dict[str, Any]:
    """Score either a rubric dict or a rich prompt packet. A packet is mapped to
    rubric criteria first so booleans/structure score sensibly."""
    if isinstance(data, dict) and not _has_rubric_scores(data):
        # Looks like a packet (or empty). Derive criteria; keep hard_fails through.
        derived = criteria_from_packet(data)
        if data.get("hard_fails"):
            derived["hard_fails"] = data["hard_fails"]
        data = derived
    return weighted_score("prompt", WEIGHTS, data, THRESHOLD)

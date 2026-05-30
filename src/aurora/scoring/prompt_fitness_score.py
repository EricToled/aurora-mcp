"""Prompt Fitness Score (Sección 3.6). Pass >= 85."""
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


def score(data: dict[str, Any]) -> dict[str, Any]:
    return weighted_score("prompt", WEIGHTS, data, THRESHOLD)

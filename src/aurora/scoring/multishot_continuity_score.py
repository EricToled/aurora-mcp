"""Multishot Continuity Score (Sección 3.4). Pass >= 85."""
from __future__ import annotations

from typing import Any

from . import weighted_score

THRESHOLD = 85
WEIGHTS = {
    "character_continuity": 15,
    "location_continuity": 15,
    "prop_product_continuity": 15,
    "lighting_color_continuity": 10,
    "camera_logic_between_shots": 10,
    "action_continuity": 15,
    "temporal_coherence": 10,
    "editability": 10,
}


def score(data: dict[str, Any]) -> dict[str, Any]:
    return weighted_score("multishot", WEIGHTS, data, THRESHOLD)

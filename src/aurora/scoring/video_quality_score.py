"""Advertising Video Quality Score — simple video (Sección 3.3). Pass >= 88."""
from __future__ import annotations

from typing import Any

from . import weighted_score

THRESHOLD = 88
WEIGHTS = {
    "photorealism_frame_to_frame": 15,
    "motion_plausibility": 15,
    "cinematic_camera": 10,
    "lighting_continuity": 10,
    "subject_consistency": 10,
    "product_prop_fidelity": 10,
    "temporal_stability": 10,
    "composition_blocking": 10,
    "artifact_absence": 10,
}


def score(data: dict[str, Any]) -> dict[str, Any]:
    return weighted_score("video", WEIGHTS, data, THRESHOLD)

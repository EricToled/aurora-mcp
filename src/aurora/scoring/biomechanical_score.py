"""Biomechanical Plausibility Score (Sección 3.5). Pass >= 85.

Hard fail: any physically impossible action for the body, object, equipment or
environment described. Pass ``hard_fails`` (list of detected impossibilities)
to zero the score.
"""
from __future__ import annotations

from typing import Any

from . import weighted_score

THRESHOLD = 85
WEIGHTS = {
    "valid_support_points": 15,
    "center_of_mass_plausible": 15,
    "joint_range_plausible": 15,
    "object_trajectory_plausible": 15,
    "contact_mechanics_plausible": 15,
    "equipment_environment_constraints": 15,
    "no_impossible_movement": 10,
}


def score(data: dict[str, Any]) -> dict[str, Any]:
    return weighted_score("biomechanics", WEIGHTS, data, THRESHOLD)

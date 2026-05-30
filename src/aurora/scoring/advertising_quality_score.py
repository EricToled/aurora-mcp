"""Advertising Quality Score — image (Sección 3.2). Pass threshold 85."""
from __future__ import annotations

from typing import Any

from . import weighted_score

THRESHOLD = 85
WEIGHTS = {
    "photorealism": 20,
    "advertising_look": 15,
    "lighting_quality": 15,
    "composition": 10,
    "materials_textures": 10,
    "anatomy_geometry": 10,
    "brand_product_fidelity": 10,
    "artifact_absence": 10,
}

# Spec hard fails — if present in data["hard_fails"] they zero the score.
HARD_FAIL_VOCAB = {
    "cartoon look",
    "cgi_plastic look",
    "deformed body",
    "broken identity",
    "product deformation",
    "illegible logos",
    "impossible perspective",
    "visible ai artifacts",
    "generic ai stock look",
}


def score(data: dict[str, Any]) -> dict[str, Any]:
    result = weighted_score("image", WEIGHTS, data, THRESHOLD)
    total = result["total_score"]
    if result["hard_fail"]:
        result["verdict"] = "reject_hard_fail"
    elif total >= 90:
        result["verdict"] = "approved_hero_asset"
    elif total >= 85:
        result["verdict"] = "approved_minor_notes"
    elif total >= 75:
        result["verdict"] = "iterate_one_variable"
    else:
        result["verdict"] = "reject_change_route"
    return result

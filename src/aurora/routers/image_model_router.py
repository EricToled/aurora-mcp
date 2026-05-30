"""image_model_router — pick a registered image route (Sección 11.1 / 11.2).

AURORA never invents routes: candidates come from the spec-registered Image
Genesis and Anchor routes, overlaid with operator YAML if present. The router
scores each candidate against the brief's image_type and returns the best
registered route plus the full ranked list, never a fabricated model_id.
"""
from __future__ import annotations

from typing import Any, Optional

from .. import capability_refresh

# Spec-registered routes (Sección 11.1 / 11.2). route_type carries the spec's
# transitional labels verbatim; gate_route_verification resolves them to a
# callable surface before any credit spend.
IMAGE_GENESIS_ROUTES: list[dict[str, Any]] = [
    {
        "route_id": "soul_cinematic_genesis",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "soul_cinematic",
        "use_for": "cinema-grade stills, concept art, cinematic advertising base",
        "image_types": ["genesis", "style_frame", "character"],
    },
    {
        "route_id": "cinematic_studio_2_5_genesis",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "cinematic_studio_image_2_5",
        "use_for": "cinematic stills / anchor candidates",
        "image_types": ["genesis", "anchor", "style_frame"],
    },
    {
        "route_id": "flux_2_product",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "flux_2",
        "use_for": "product hero, material fidelity, prompt adherence",
        "image_types": ["product_hero", "prop", "genesis"],
    },
    {
        "route_id": "nano_banana_pro_text_packaging",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "nano_banana_pro",
        "use_for": "text rendering, packaging, composition control",
        "image_types": ["product_hero", "prop", "style_frame"],
    },
    {
        "route_id": "marketing_studio_image_ads",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "marketing_studio_image",
        "use_for": "DTC/product advertising if available",
        "image_types": ["product_hero", "genesis"],
    },
]

ANCHOR_ROUTES: list[dict[str, Any]] = [
    {
        "route_id": "soul_id_character_anchor",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "soul_id",
        "use_for": "real person identity if consent and training assets exist",
        "image_types": ["anchor", "character"],
    },
    {
        "route_id": "soul_cast_character_anchor",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "soul_cast",
        "use_for": "generated cinematic character identity",
        "image_types": ["anchor", "character"],
    },
    {
        "route_id": "reference_element_anchor",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "reference_element",
        "use_for": "anchor from approved Higgsfield Elements",
        "image_types": ["anchor", "location", "prop"],
    },
    {
        "route_id": "seedream_precise_transform",
        "route_type": "mcp_callable_or_ui_verified",
        "model_id": "seedream_v4_5",
        "use_for": "controlled transformation from refs",
        "image_types": ["anchor", "genesis", "style_frame"],
    },
]


def _registered_routes() -> list[dict[str, Any]]:
    """Spec routes overlaid with operator-editable YAML, if present."""
    caps = capability_refresh.load_capabilities()
    overrides = caps.get("image_routes")
    if isinstance(overrides, list) and overrides:
        return overrides
    return IMAGE_GENESIS_ROUTES + ANCHOR_ROUTES


def select_route(
    image_type: str,
    aspect_ratio: Optional[str] = None,
    element_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Rank registered image routes for an image_type. Returns the best route
    plus the ranked candidates. Never invents a model_id."""
    itype = (image_type or "").strip().lower()
    routes = _registered_routes()
    ranked: list[dict[str, Any]] = []
    for r in routes:
        supported = [t.lower() for t in r.get("image_types", [])]
        score = 100 if itype in supported else (50 if not supported else 0)
        candidate = {**r, "match_score": score}
        # Annotate per-model constraints when an explicit model_id is present.
        model_id = r.get("model_id", "")
        if aspect_ratio and model_id:
            candidate["aspect_ratio_check"] = capability_refresh.validate_aspect_ratio(
                model_id, aspect_ratio
            )
        if element_ids and model_id:
            candidate["element_injection"] = capability_refresh.validate_element_injection(
                model_id, element_ids
            )
        ranked.append(candidate)

    ranked.sort(key=lambda c: c["match_score"], reverse=True)
    best = ranked[0] if ranked and ranked[0]["match_score"] > 0 else None
    return {
        "ok": best is not None,
        "image_type": image_type,
        "selected_route": best,
        "ranked_candidates": ranked,
        "reason": None
        if best
        else f"no registered image route matches image_type={image_type!r}",
    }

"""AURORA routers — registered-route selection for Higgsfield (Sección 11).

AURORA operates only on registered routes and never invents one. Each router is
a pure function returning a plain dict.
"""
from __future__ import annotations

from . import (
    image_model_router,
    internal_route_bakeoff,
    ui_vs_mcp_router,
    video_model_router,
)

__all__ = [
    "image_model_router",
    "video_model_router",
    "ui_vs_mcp_router",
    "internal_route_bakeoff",
]

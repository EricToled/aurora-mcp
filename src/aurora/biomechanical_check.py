"""STUB — Sprint 2 implementation.

Full version validates a biomechanical motion plan against sub-domain physics
rules (joint limits, center-of-mass trajectory, object speed/arrival) and blocks
physically impossible motion. Sprint 1 always returns True.
"""
from __future__ import annotations

from typing import Any


def check(motion_plan: dict[str, Any]) -> bool:
    """STUB: always passes. TODO: Sprint 2 — real biomechanical validation."""
    return True

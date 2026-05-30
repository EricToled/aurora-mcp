"""STUB — Sprint 8 implementation.

Full version enforces continuity anchors across multishot sequences (FF/LF,
character/prop/location sheets, previous-clip last-seconds refs) to keep identity
drift below threshold. Sprint 1 always returns True.
"""
from __future__ import annotations

from typing import Any


def check(shot: dict[str, Any], previous_shot: dict[str, Any] | None = None) -> bool:
    """STUB: always passes. TODO: Sprint 8 — continuity anchor enforcement."""
    return True

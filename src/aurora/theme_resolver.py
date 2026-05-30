"""STUB — Sprint 2 implementation.

Full version resolves operator intent into mode + output type + photographic
style + cinematic style + thematic domain/sub-domain using workflow YAMLs and
tribal mining. Sprint 1 returns a hardcoded placeholder classification so the
MCP `aurora_classify_intent` tool has a stable contract to build against.
"""
from __future__ import annotations

from typing import Any


def classify_intent(text: str) -> dict[str, Any]:
    """STUB: return a placeholder classification structure.

    TODO: Sprint 2 — real resolution from workflows/ + tribal_mining.
    """
    return {
        "mode": "video_simple",
        "output_type": "hero_ad",
        "photographic_style": "editorial",
        "cinematic_style": "cinematic_ad",
        "domain": "unresolved",
        "sub_domain": "unresolved",
        "confidence": 0.0,
        "stub": True,
        "operator_text": text,
        "note": "STUB classification — Sprint 2 will resolve from workflow YAMLs",
    }

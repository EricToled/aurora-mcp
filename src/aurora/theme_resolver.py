"""Operator intent resolution (Sección 2 — flujo paso 1).

Resolves free-text operator intent into a structured classification: mode
(image / video_simple / video_multishot), output type, photographic and
cinematic style hints, and a confidence. Keyword-driven and deterministic so
the MCP ``aurora_classify_intent`` tool and the CLI ``classify`` command have a
stable, testable contract. Domain/sub-domain remain ``unresolved`` until a
workflow-YAML resolver is wired in.
"""
from __future__ import annotations

import re
from typing import Any

# Mode signals -------------------------------------------------------------
_MULTISHOT_TERMS = (
    "multishot", "multi-shot", "multi shot", "secuencia", "sequence",
    "varios shots", "varias tomas", "shot list", "shotlist", "scene sequence",
    "multiple shots", "multiple scenes", "varias escenas", "dialogue",
    "diálogo", "dialogo", "storyboard", "shots", "tomas", "escenas",
)
_VIDEO_TERMS = (
    "video", "vídeo", "clip", "ad video", "spot", "anuncio en video",
    "motion", "animation", "animación", "seconds", "segundos", "fps",
    "footage", "reel", "loop", "cinemagraph", "comercial",
)
_IMAGE_TERMS = (
    "image", "imagen", "foto", "photo", "still", "poster", "póster",
    "packaging", "key visual", "keyvisual", "product shot", "hero image",
    "render", "thumbnail", "portrait", "retrato", "wallpaper", "banner",
)

# Output type signals ------------------------------------------------------
_OUTPUT_TYPES = (
    ("hero_ad", ("hero", "anuncio", "ad", "commercial", "comercial", "spot")),
    ("product_shot", ("product", "producto", "packshot", "packaging", "bottle", "botella")),
    ("social_post", ("social", "instagram", "tiktok", "reel", "post", "story", "historia")),
    ("portrait", ("portrait", "retrato", "character", "personaje", "face", "rostro")),
    ("poster", ("poster", "póster", "key visual", "keyvisual", "banner", "cartel")),
)


def _contains(text: str, terms: tuple[str, ...]) -> bool:
    return any(t in text for t in terms)


def _detect_mode(text: str) -> tuple[str, float]:
    is_multishot = _contains(text, _MULTISHOT_TERMS)
    is_video = _contains(text, _VIDEO_TERMS) or bool(
        re.search(r"\b\d+\s*(s|seg|secs?|seconds?|segundos?)\b", text)
    )
    is_image = _contains(text, _IMAGE_TERMS)

    if is_multishot and (is_video or not is_image):
        return "video_multishot", 0.85
    if is_video and not is_image:
        return "video_simple", 0.8
    if is_image and not is_video:
        return "image", 0.85
    if is_video and is_image:
        # Both signalled — a video that needs an image asset first; treat as video.
        return "video_simple", 0.6
    # No strong signal: default to image (the cheaper, asset-pipeline path).
    return "image", 0.4


def _detect_output_type(text: str) -> str:
    for name, terms in _OUTPUT_TYPES:
        if _contains(text, terms):
            return name
    return "hero_ad"


def classify_intent(text: str) -> dict[str, Any]:
    """Classify operator intent into mode + output type + style hints."""
    raw = text or ""
    lowered = raw.lower()
    mode, confidence = _detect_mode(lowered)
    output_type = _detect_output_type(lowered)

    return {
        "mode": mode,
        "output_type": output_type,
        "photographic_style": "editorial",
        "cinematic_style": "cinematic_ad",
        "domain": "unresolved",
        "sub_domain": "unresolved",
        "confidence": confidence,
        "stub": False,
        "operator_text": raw,
        "note": "keyword-based classification; domain resolution pending workflow YAMLs",
    }

"""Higgsfield capability refresh + surface model (Sección 5 / 5B).

AURORA never hard-codes model/preset counts as eternal constants; they come from
a live refresh or a verified snapshot. This module carries the spec's KNOWN
defaults (alias registry, element-injection support, aspect-ratio policy, live
counts snapshot) and overlays the operator-editable YAML at
``platform_capabilities/higgsfield_platform_capabilities.yaml`` when present.

Live MCP results are never produced here — Higgsfield runs in Claude Desktop.
``refresh`` records a snapshot of whatever capabilities AURORA currently knows so
gate_higgsfield_light_refresh can verify freshness.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from . import db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CAPABILITIES_YAML = (
    REPO_ROOT / "platform_capabilities" / "higgsfield_platform_capabilities.yaml"
)

REFRESH_SCOPES = {
    "light_session",
    "model_schema",
    "ui_partial",
    "emergency",
    "full_monthly",
}

# Soul models reference identity via soul_id, NOT <<<element_id>>> (Sección 5B.5).
SOUL_MODELS = {"soul_2", "soul_cinematic", "soul", "soul_id", "soul_cast"}

# Spec-known defaults. These are a verified snapshot, not eternal constants;
# a live refresh overrides them.
DEFAULT_CAPABILITIES: dict[str, Any] = {
    "model_alias_registry": {
        "cinema_studio_3_5_ui": {
            "label": "Cinema Studio 3.5",
            "status": "ui_confirmed_mcp_pending",
            "callable_when_ui": True,
            "callable_when_mcp": False,
            "current_mcp_equivalents": [
                "cinematic_studio_3_0",
                "cinematic_studio_video_v2",
            ],
            "future_mcp_candidates": [
                "cinematic_studio_3_5",
                "cinema_studio_3_5",
                "cinematic_studio_video_3_5",
            ],
        },
    },
    "element_injection_support_observed": {
        "supported_if_live_verified": [
            "nano_banana_2",
            "nano_banana_pro",
            "gpt_image_2",
            "seedream",
            "seedream_v4_5",
            "cinematic_studio_image_2_5",
            "cinematic_studio_video_v2",
            "cinematic_studio_3_0",
            "seedance_2_0",
            "kling_3_0",
        ],
        "not_supported_observed": ["soul_2", "soul_cinematic"],
        "alternative_for_soul_models": "soul_id",
    },
    "aspect_ratio_policy": {
        "cinematic_studio_3_0": {
            "status": "verify_live",
            "known_public_support_likely": ["16:9", "9:16", "1:1"],
            "not_assume": ["21:9"],
        },
        "cinematic_studio_video_v2": {
            "status": "verify_live",
            "not_assume": ["21:9"],
        },
        "seedance_2_0": {"status": "verify_live", "may_support": ["21:9"]},
        "marketing_studio_video": {"status": "verify_live", "may_support": ["21:9"]},
    },
    "live_counts_snapshot": {
        "count_models": 36,
        "count_presets": 48,
        "verification_source": "live_mcp",
        "verified_at": None,
        "expires_at": None,
    },
    "quality_controls": {
        "higgsfield_upscale": {"route": "ui_only_or_not_verified", "mcp_callable": False},
        "topaz_inside_higgsfield": {
            "route": "ui_only_or_not_verified",
            "mcp_callable": False,
        },
        "topaz_external": {"route": "outside_aurora", "mcp_callable": False},
    },
}


def _load_yaml_capabilities() -> dict[str, Any]:
    if yaml is None or not CAPABILITIES_YAML.exists():
        return {}
    try:
        data = yaml.safe_load(CAPABILITIES_YAML.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def load_capabilities() -> dict[str, Any]:
    """Built-in spec defaults overlaid with the operator-editable YAML."""
    merged = {k: v for k, v in DEFAULT_CAPABILITIES.items()}
    merged.update(_load_yaml_capabilities())
    return merged


def refresh(
    scope: str = "light_session",
    source: str = "snapshot_verified",
    db_path: Optional[str] = None,
    target_models: Optional[list[str]] = None,
    target_features: Optional[list[str]] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Record a capability snapshot. Returns {snapshot_id, scope, capabilities, diff}."""
    if scope not in REFRESH_SCOPES:
        return {"ok": False, "reason": f"unknown refresh scope: {scope}"}
    caps = load_capabilities()
    if target_models:
        caps = {**caps, "target_models": target_models}
    if target_features:
        caps = {**caps, "target_features": target_features}

    previous = db.get_latest_snapshot(db_path=db_path)
    diff = None
    if previous:
        diff = _diff_capabilities(previous.get("snapshot", {}), caps)
    snapshot_id = db.insert_capability_snapshot(
        refresh_scope=scope, source=source, snapshot=caps, diff_from_previous=diff,
        db_path=db_path,
    )
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "scope": scope,
        "capabilities": caps,
        "diff_from_previous": diff,
    }


def _diff_capabilities(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Shallow top-level diff so model/preset count changes generate a diff."""
    changed = {}
    for key in set(old) | set(new):
        if old.get(key) != new.get(key):
            changed[key] = {"from": old.get(key), "to": new.get(key)}
    return changed


def get_live_counts(db_path: Optional[str] = None) -> dict[str, Any]:
    """Read model/preset counts from the latest snapshot, else the default
    snapshot. Never returns a hard-coded literal independent of the snapshot."""
    latest = db.get_latest_snapshot(db_path=db_path)
    caps = latest.get("snapshot", {}) if latest else load_capabilities()
    return caps.get("live_counts_snapshot", DEFAULT_CAPABILITIES["live_counts_snapshot"])


# ---------------------------------------------------------------------------
# Surface helpers (tools 22, 23, 24)
# ---------------------------------------------------------------------------
def resolve_model_alias(alias_name: str, desired_surface: str) -> dict[str, Any]:
    """Resolve a UI/product alias to callable model_ids for a surface.

    desired_surface in {'mcp', 'ui'}. Cinema Studio 3.5 over MCP returns no
    callable model_id until a live refresh confirms one (Sección 5B.2).
    """
    caps = load_capabilities()
    registry = caps.get("model_alias_registry", {})
    entry = registry.get(alias_name)
    if not entry:
        return {
            "ok": False,
            "alias": alias_name,
            "reason": "alias not in registry",
        }
    if desired_surface == "ui":
        return {
            "ok": bool(entry.get("callable_when_ui")),
            "alias": alias_name,
            "surface": "ui",
            "callable": bool(entry.get("callable_when_ui")),
            "ui_label": entry.get("label"),
            "generate_ui_instructions": bool(entry.get("callable_when_ui")),
            "generate_mcp_payload": False,
        }
    # MCP surface
    callable_mcp = bool(entry.get("callable_when_mcp"))
    return {
        "ok": callable_mcp,
        "alias": alias_name,
        "surface": "mcp",
        "callable": callable_mcp,
        "callable_model_ids": entry.get("current_mcp_equivalents", []) if callable_mcp else [],
        "future_mcp_candidates": entry.get("future_mcp_candidates", []),
        "generate_mcp_payload": callable_mcp,
        "reason": None if callable_mcp else "no validated 3.5 model_id; MCP pending live refresh",
    }


def validate_element_injection(model_id: str, element_ids: list[str]) -> dict[str, Any]:
    """Decide whether <<<element_id>>> injection is allowed for a model.

    Soul models use soul_id instead (Sección 5B.5).
    """
    caps = load_capabilities()
    support = caps.get("element_injection_support_observed", {})
    supported = set(support.get("supported_if_live_verified", []))
    not_supported = set(support.get("not_supported_observed", []))
    mid = model_id.strip().lower()

    if mid in {m.lower() for m in SOUL_MODELS} or mid in {
        m.lower() for m in not_supported
    }:
        return {
            "ok": False,
            "model_id": model_id,
            "mechanism": "soul_id",
            "inject_syntax": None,
            "reason": "Soul model — use soul_id, not <<<element_id>>>",
        }
    if mid in {m.lower() for m in supported}:
        return {
            "ok": True,
            "model_id": model_id,
            "mechanism": "element_id",
            "inject_syntax": [f"<<<{eid}>>>" for eid in element_ids],
            "reason": "element injection supported (verify live before credit spend)",
        }
    return {
        "ok": False,
        "model_id": model_id,
        "mechanism": "unknown",
        "inject_syntax": None,
        "reason": "element injection support not verified for this model",
    }


def validate_aspect_ratio(model_id: str, aspect_ratio: str) -> dict[str, Any]:
    """Validate aspect ratio per model (Sección 5B.7). 21:9 blocks if a model's
    policy lists it under not_assume and not under may_support."""
    caps = load_capabilities()
    policy = caps.get("aspect_ratio_policy", {})
    entry = policy.get(model_id)
    if not entry:
        return {
            "ok": False,
            "model_id": model_id,
            "aspect_ratio": aspect_ratio,
            "status": "unknown_model",
            "reason": "no aspect-ratio policy for model; verify live",
        }
    not_assume = set(entry.get("not_assume", []))
    may_support = set(entry.get("may_support", []))
    likely = set(entry.get("known_public_support_likely", []))
    if aspect_ratio in not_assume and aspect_ratio not in may_support:
        return {
            "ok": False,
            "model_id": model_id,
            "aspect_ratio": aspect_ratio,
            "status": "blocked",
            "reason": f"{aspect_ratio} not supported by {model_id}; "
            "propose a 21:9-capable route, switch to 16:9 + crop plan, or block until override",
        }
    if aspect_ratio in may_support or aspect_ratio in likely:
        return {
            "ok": True,
            "model_id": model_id,
            "aspect_ratio": aspect_ratio,
            "status": "verify_live",
            "reason": "supported pending live schema verification",
        }
    return {
        "ok": False,
        "model_id": model_id,
        "aspect_ratio": aspect_ratio,
        "status": "verify_live",
        "reason": "not in known support; read live model schema before credit spend",
    }

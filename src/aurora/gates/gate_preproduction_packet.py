"""gate_preproduction_packet — the 'regla inviolable' enforcer (Sprint 1, full).

Pure, side-effect-free validation of the 12 mandatory preproduction components
(spec Section 7 / Section L). Reports what is missing; it does NOT block.
The caller (server.py) decides whether to block based on active bypasses.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

VALID_FF_LF_STRATEGIES = {
    "simple_start",
    "start_and_end",
    "open_end",
    "multishot_per_shot",
    "continuity_from_previous",
    "dialogue_long",
    "complex_scene",
}
VALID_ROUTES = {"ui", "mcp", "hybrid"}

# Required shot-level fields (presence check) for each entry in shot_list.
_REQUIRED_SHOT_FIELDS = ("shot_number", "duration_seconds", "shot_type", "function")


class ValidationResult(BaseModel):
    passed: bool
    missing: list[str]
    warnings: list[str]
    bypass_required_to_proceed: bool


def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _is_nonempty_list(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0


def validate_packet(packet: dict[str, Any]) -> ValidationResult:
    """Validate the 12 mandatory preproduction components. Pure function."""
    missing: list[str] = []
    warnings: list[str] = []

    # 1. idea — non-empty str
    if not _is_nonempty_str(packet.get("idea")):
        missing.append("idea")

    # 2. script — dict (the video brief)
    script = packet.get("script")
    if not isinstance(script, dict) or not script:
        missing.append("script")

    # 3. shot_list — list len >= 1, each shot has required fields
    shot_list = packet.get("shot_list")
    if not _is_nonempty_list(shot_list):
        missing.append("shot_list")
    else:
        for idx, shot in enumerate(shot_list):
            if not isinstance(shot, dict):
                missing.append(f"shot_list[{idx}]")
                continue
            for field in _REQUIRED_SHOT_FIELDS:
                if field not in shot or shot.get(field) in (None, ""):
                    warnings.append(
                        f"shot_list[{idx}] missing recommended field '{field}'"
                    )

    # 4. characters — list; warn (not block) if empty (mode may be product-only)
    characters = packet.get("characters")
    if not isinstance(characters, list):
        missing.append("characters")
    elif len(characters) == 0:
        warnings.append("characters list is empty — ensure mode is product/prop only")

    # 5. location — dict with non-empty name
    location = packet.get("location")
    if not isinstance(location, dict) or not _is_nonempty_str(location.get("name")):
        missing.append("location")

    # 6. props_or_product — list or dict with at least one entry
    pop = packet.get("props_or_product")
    if isinstance(pop, list):
        if len(pop) == 0:
            missing.append("props_or_product")
    elif isinstance(pop, dict):
        if not pop:
            missing.append("props_or_product")
    else:
        missing.append("props_or_product")

    # 7. visual_style — non-empty str
    if not _is_nonempty_str(packet.get("visual_style")):
        missing.append("visual_style")

    # 8. biomechanical_plan — list, one per shot
    bio = packet.get("biomechanical_plan")
    if not isinstance(bio, list):
        missing.append("biomechanical_plan")
    else:
        if len(bio) == 0:
            missing.append("biomechanical_plan")
        elif _is_nonempty_list(shot_list) and len(bio) != len(shot_list):
            warnings.append(
                f"biomechanical_plan has {len(bio)} entries but shot_list has "
                f"{len(shot_list)} shots — expected one plan per shot"
            )

    # 9. ff_lf_strategy — non-empty str with valid enum value
    ff = packet.get("ff_lf_strategy")
    if not _is_nonempty_str(ff) or ff not in VALID_FF_LF_STRATEGIES:
        missing.append("ff_lf_strategy")

    # 10. recommended_model — non-empty str
    if not _is_nonempty_str(packet.get("recommended_model")):
        missing.append("recommended_model")

    # 11. ui_or_mcp_route — non-empty str with valid enum value
    route = packet.get("ui_or_mcp_route")
    if not _is_nonempty_str(route) or route not in VALID_ROUTES:
        missing.append("ui_or_mcp_route")

    # 12. success_criteria — list len >= 1
    if not _is_nonempty_list(packet.get("success_criteria")):
        missing.append("success_criteria")

    passed = len(missing) == 0
    return ValidationResult(
        passed=passed,
        missing=missing,
        warnings=warnings,
        bypass_required_to_proceed=not passed,
    )


def check(packet: dict[str, Any]):
    """Uniform gate interface wrapper returning a GateResult."""
    from ..models import GateResult

    result = validate_packet(packet)
    return GateResult(
        gate="gate_preproduction_packet",
        passed=result.passed,
        reasons=[f"missing: {m}" for m in result.missing],
        notes="; ".join(result.warnings),
    )

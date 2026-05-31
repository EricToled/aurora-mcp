"""AURORA gates (Sección 7).

The 13 mandatory gates. Each module exposes ``check(...)`` returning a
``models.GateResult``. ``MANDATORY_GATES`` lists the gate names the Execution
Pack emission must satisfy (some only apply to video/multishot).
"""
from __future__ import annotations

from . import (
    gate_anchors_audited,
    gate_benchmark_pack,
    gate_biomechanical_sanity,
    gate_continuity_readiness,
    gate_domain_session_lock,
    gate_higgsfield_light_refresh,
    gate_multishot_anchor_strategy,
    gate_platform_syntax_researched,
    gate_preproduction_packet,
    gate_production_success_probability,
    gate_prompt_fitness,
    gate_route_verification,
    gate_step_0_quality_ceiling,
    gate_upscale_finishing_route,
)

GATE_MODULES = {
    "gate_domain_session_lock": gate_domain_session_lock,
    "gate_higgsfield_light_refresh": gate_higgsfield_light_refresh,
    "gate_preproduction_packet": gate_preproduction_packet,
    "gate_benchmark_pack": gate_benchmark_pack,
    "gate_route_verification": gate_route_verification,
    "gate_step_0_quality_ceiling": gate_step_0_quality_ceiling,
    "gate_anchors_audited": gate_anchors_audited,
    "gate_biomechanical_sanity": gate_biomechanical_sanity,
    "gate_prompt_fitness": gate_prompt_fitness,
    "gate_multishot_anchor_strategy": gate_multishot_anchor_strategy,
    "gate_continuity_readiness": gate_continuity_readiness,
    "gate_upscale_finishing_route": gate_upscale_finishing_route,
    "gate_production_success_probability": gate_production_success_probability,
    "gate_platform_syntax_researched": gate_platform_syntax_researched,
}

# Gates that always block Execution Pack emission.
ALWAYS_REQUIRED = [
    "gate_domain_session_lock",
    "gate_higgsfield_light_refresh",
    "gate_preproduction_packet",
    "gate_benchmark_pack",
    "gate_route_verification",
    "gate_step_0_quality_ceiling",
    "gate_anchors_audited",
    "gate_prompt_fitness",
    "gate_production_success_probability",
    # v2.3: every declared model must have a fresh syntax_dossier. Applies to
    # BOTH image and video pipelines, so it lives in ALWAYS_REQUIRED.
    "gate_platform_syntax_researched",
]

# Gates that block only for video/multishot modes ("si aplica").
VIDEO_REQUIRED = ["gate_biomechanical_sanity"]
MULTISHOT_REQUIRED = ["gate_multishot_anchor_strategy", "gate_continuity_readiness"]


def required_gates_for_mode(mode: str) -> list[str]:
    gates = list(ALWAYS_REQUIRED)
    if mode in ("video_simple", "video_multishot"):
        gates += VIDEO_REQUIRED
        gates.append("gate_upscale_finishing_route")
    if mode == "video_multishot":
        gates += MULTISHOT_REQUIRED
    return gates

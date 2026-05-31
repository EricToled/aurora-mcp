"""execution_pack_builder — assemble + gate-guard the Execution Pack (Sección 10/13).

The Execution Pack is the operative document AURORA hands to Eric. It may ONLY
be emitted when every required gate for the project mode passes — or has an
explicit, registered bypass (Sección 10 "Regla de emisión"). This module runs
the gate suite over an assembled context, records which gates were bypassed,
and renders ``templates/execution_pack.md.jinja`` verbatim when not blocked.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import gates as gates_pkg
from .gates import (
    gate_anchors_audited,
    gate_benchmark_pack,
    gate_biomechanical_sanity,
    gate_continuity_readiness,
    gate_domain_session_lock,
    gate_higgsfield_light_refresh,
    gate_multishot_anchor_strategy,
    gate_preproduction_packet,
    gate_production_success_probability,
    gate_prompt_fitness,
    gate_route_verification,
    gate_step_0_quality_ceiling,
    gate_upscale_finishing_route,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = REPO_ROOT / "templates"

# Each gate is fed the slice of the assembled context it needs. The lambda
# isolates "where does this gate's input live in context" from the gate logic.
_GATE_INPUTS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "gate_domain_session_lock": lambda c: gate_domain_session_lock.check(
        c.get("domain_lock")
    ),
    "gate_higgsfield_light_refresh": lambda c: gate_higgsfield_light_refresh.check(
        c.get("refresh_snapshot")
    ),
    "gate_preproduction_packet": lambda c: gate_preproduction_packet.check(
        c.get("packet") or {}
    ),
    "gate_benchmark_pack": lambda c: gate_benchmark_pack.check(c.get("benchmark_pack")),
    "gate_route_verification": lambda c: gate_route_verification.check(c.get("routes")),
    "gate_step_0_quality_ceiling": lambda c: gate_step_0_quality_ceiling.check(
        {
            "benchmark_pack": c.get("benchmark_pack"),
            "image_scores": c.get("image_scores") or [],
            "audits": c.get("audits") or [],
        }
    ),
    "gate_anchors_audited": lambda c: gate_anchors_audited.check(
        c.get("anchor_state") or {}
    ),
    "gate_biomechanical_sanity": lambda c: gate_biomechanical_sanity.check(
        c.get("motion_plan")
    ),
    "gate_prompt_fitness": lambda c: gate_prompt_fitness.check(c.get("prompt_packet")),
    "gate_multishot_anchor_strategy": lambda c: gate_multishot_anchor_strategy.check(
        c.get("shot_list")
    ),
    "gate_continuity_readiness": lambda c: gate_continuity_readiness.check(
        c.get("shot_list")
    ),
    "gate_upscale_finishing_route": lambda c: gate_upscale_finishing_route.check(
        c.get("finishing")
    ),
    "gate_production_success_probability": lambda c: gate_production_success_probability.check(
        c.get("psp_components")
    ),
}


def evaluate_gates(
    context: dict[str, Any],
    mode: str,
    active_bypasses: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Run every required gate for the mode. A failing gate blocks unless an
    active bypass names it. Returns gate rows + the list of true blockers."""
    active_bypasses = active_bypasses or {}
    # An "all" bypass (BYPASS AURORA) covers every gate — operator sovereignty.
    bypass_all = active_bypasses.get("all")
    required = gates_pkg.required_gates_for_mode(mode)
    rows: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    bypassed: list[dict[str, Any]] = []

    for name in required:
        runner = _GATE_INPUTS.get(name)
        if runner is None:
            continue
        result = runner(context)
        bypass_reason = active_bypasses.get(name)
        if bypass_reason is None and bypass_all is not None:
            bypass_reason = f"BYPASS AURORA: {bypass_all}"
        if result.passed:
            status = "pass"
        elif bypass_reason is not None:
            status = "bypassed"
            bypassed.append({"name": name, "reason": bypass_reason})
        else:
            status = "fail"
            blocking.append({"name": name, "reason": "; ".join(result.reasons) or "blocked"})
        rows.append(
            {
                "name": name,
                "status": status,
                "score": result.score,
                "notes": result.notes or "; ".join(result.reasons),
            }
        )

    return {
        "gates": rows,
        "blocking_gates": blocking,
        "bypassed_gates": bypassed,
        "all_clear": len(blocking) == 0,
    }


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=False,
        lstrip_blocks=False,
    )


def render_execution_pack(render_context: dict[str, Any]) -> str:
    """Render templates/execution_pack.md.jinja with the supplied context."""
    template = _env().get_template("execution_pack.md.jinja")
    return template.render(**render_context)


def build_execution_pack(
    project: dict[str, Any],
    context: dict[str, Any],
    mode: str,
    active_bypasses: Optional[dict[str, str]] = None,
    pack_id: Optional[str] = None,
    pack_version: str = "1",
) -> dict[str, Any]:
    """Gate-guard then render the Execution Pack.

    Returns {ok, blocked, gate_evaluation, markdown}. ``markdown`` is None when
    blocked (a gate failed with no registered bypass).
    """
    evaluation = evaluate_gates(context, mode, active_bypasses)
    if not evaluation["all_clear"]:
        return {
            "ok": False,
            "blocked": True,
            "gate_evaluation": evaluation,
            "markdown": None,
            "reason": "blocking gates without bypass: "
            + ", ".join(g["name"] for g in evaluation["blocking_gates"]),
        }

    now = datetime.now(timezone.utc).isoformat()
    psp = context.get("psp_result") or {"total_score": 0}
    domain_lock = context.get("domain_lock") or {}
    render_context = {
        "now": now,
        "project": project,
        "pack": {"version": pack_version, "pack_id": pack_id or f"pack_{project.get('project_id', '')}"},
        "route_summary": context.get("route_summary", ""),
        "route_policy": context.get("route_policy", {"higgsfield_only": True}),
        "production_success_probability": psp,
        "domain_lock": domain_lock,
        "domain_lock_yaml": yaml.safe_dump(domain_lock, allow_unicode=True, sort_keys=False),
        "gates": evaluation["gates"],
        "blocking_gates": evaluation["blocking_gates"],
        "benchmark_refs": context.get("benchmark_refs", []),
        "elements": context.get("elements", []),
        "routes": context.get("routes", []),
        "global_ui_config": context.get("global_ui_config"),
        "shots": context.get("shots", []),
        "post_production_yaml": yaml.safe_dump(
            context.get("post_production", {}), allow_unicode=True, sort_keys=False
        ),
        "success_criteria": context.get("success_criteria", []),
        "bypasses": context.get("bypasses", []),
    }
    markdown = render_execution_pack(render_context)
    return {
        "ok": True,
        "blocked": False,
        "gate_evaluation": evaluation,
        "markdown": markdown,
        "reason": None,
    }


def to_pretty_json(obj: Any) -> str:
    """Helper for callers building shot.mcp_payload_json before render."""
    return json.dumps(obj, indent=2, ensure_ascii=False)

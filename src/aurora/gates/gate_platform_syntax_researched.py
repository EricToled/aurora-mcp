"""gate_platform_syntax_researched — v2.3 research-driven prompt construction.

Blocks Execution Pack emission (and, in strict mode, propose_*) when any model
declared for the project lacks a fresh syntax_dossier. Applies to BOTH pipelines:

  * Pipeline A (mode=image): every model behind a declared element.
  * Pipeline B/C (mode=video_*): every model in the shot_list MCSLA + the
    packet's recommended_model.

The gate is PURE: ``_assemble_context`` precomputes ``research_coverage`` (a
db lookup per declared model) and ``mode`` into the context, so the gate itself
does no I/O and is trivially unit-testable. ``research_coverage`` maps each
declared model_id to {output_type, present, expired, confidence}.
"""
from __future__ import annotations

from typing import Any


def check(context: dict[str, Any]):
    """Pass only when every declared model has a present, non-expired dossier.

    context["research_coverage"]: {model_id: {"output_type": str, "present": bool,
                                              "expired": bool, "confidence": float}}
    context["mode"]: the project mode (image|video_simple|video_multishot).
    """
    from ..models import GateResult

    mode = context.get("mode") or "video_multishot"
    coverage: dict[str, dict[str, Any]] = context.get("research_coverage") or {}

    if not coverage:
        return GateResult(
            gate="gate_platform_syntax_researched",
            passed=False,
            reasons=[
                f"no model declared for {mode} mode — cannot check research "
                "coverage; declare a recommended_model / element model before emit"
            ],
        )

    missing: list[tuple[str, str]] = []
    expired: list[tuple[str, str]] = []
    for model_id, cov in coverage.items():
        output_type = cov.get("output_type", mode)
        if not cov.get("present"):
            missing.append((model_id, output_type))
        elif cov.get("expired"):
            expired.append((model_id, output_type))

    if missing or expired:
        reasons: list[str] = []
        for model_id, output_type in missing:
            reasons.append(
                f"no research dossier for {model_id} ({output_type}) — call "
                f"aurora_request_platform_research(model_id='{model_id}', "
                f"output_type='{output_type}') then aurora_record_platform_research"
            )
        for model_id, output_type in expired:
            reasons.append(
                f"dossier expired for {model_id} ({output_type}) — re-run "
                "aurora_request_platform_research to refresh it"
            )
        return GateResult(
            gate="gate_platform_syntax_researched", passed=False, reasons=reasons
        )

    return GateResult(
        gate="gate_platform_syntax_researched",
        passed=True,
        reasons=[],
        notes=f"all {len(coverage)} declared models researched (mode={mode})",
    )

"""AURORA MCP server (Sprint 1).

Exposes 4 tools that enforce AURORA's deterministic gates:
  - aurora_classify_intent
  - aurora_create_video_brief
  - aurora_validate_preproduction_packet
  - aurora_log_bypass

Two transports — same code, same deterministic behavior:

  Local (stdio):     python -m aurora.server
  Remote (HTTP):     python -m aurora.server --http      (or set AURORA_HTTP=1)
  Self-test:         python -m aurora.server --selftest

The HTTP mode is what makes AURORA reachable from ANY Claude session
(Cowork or regular): host it on the internet, register the URL as a custom
connector, and the 4 tools run server-side — identical every time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from . import bypass_handler, db
from .gates import gate_preproduction_packet
from .models import VideoBrief
from . import theme_resolver

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# DB path is overridable so a hosted instance can point at a persistent volume.
DB_PATH = Path(os.environ.get("AURORA_DB_PATH", str(REPO_ROOT / "aurora.db")))

# Bind config for HTTP mode. Render and most PaaS inject PORT.
_HTTP_HOST = os.environ.get("AURORA_HOST", "0.0.0.0")
_HTTP_PORT = int(os.environ.get("PORT", os.environ.get("AURORA_PORT", "8000")))

mcp = FastMCP("aurora", host=_HTTP_HOST, port=_HTTP_PORT)


def _ensure_db() -> None:
    """Create aurora.db with the schema if it does not yet exist."""
    if not DB_PATH.exists():
        db.init_db(DB_PATH)


@mcp.tool()
def aurora_classify_intent(text: str) -> dict[str, Any]:
    """Classify operator intent into mode + output type + style.

    Sprint 1: delegates to the theme_resolver stub (hardcoded placeholder).
    """
    return theme_resolver.classify_intent(text)


@mcp.tool()
def aurora_create_video_brief(brief_data: dict[str, Any]) -> dict[str, Any]:
    """Validate a video brief against the template and persist it.

    Returns {"ok": True, "brief_id": ...} or {"ok": False, "errors": [...]}.
    """
    _ensure_db()
    try:
        brief = VideoBrief(**brief_data)
    except ValidationError as exc:
        return {"ok": False, "errors": exc.errors(include_url=False)}

    brief_id = db.insert_brief(brief.model_dump(mode="json"), db_path=str(DB_PATH))
    return {"ok": True, "brief_id": brief_id}


@mcp.tool()
def aurora_validate_preproduction_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Run the 'regla inviolable' gate over a preproduction packet.

    Returns the ValidationResult (passed, missing, warnings,
    bypass_required_to_proceed). Reporting only — does not block.
    """
    result = gate_preproduction_packet.validate_packet(packet)
    return result.model_dump()


@mcp.tool()
def aurora_log_bypass(
    operator_text: str,
    component: str,
    reason: str,
    scope: str = "current_turn",
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """Register an operator bypass directive in bypass_log.

    Validates the directive; invalid component or empty reason is rejected.
    Returns {"ok": True, "bypass_id": ...} or {"ok": False, "reason": ...}.
    """
    _ensure_db()
    if component not in bypass_handler.BYPASSABLE_COMPONENTS:
        return {"ok": False, "reason": f"unknown component: {component}"}
    if not reason or not reason.strip():
        return {"ok": False, "reason": "empty reason rejected"}
    if scope not in ("current_turn", "persist", "all_session"):
        scope = "current_turn"

    directive = bypass_handler.BypassDirective(
        component=component,
        reason=reason,
        scope=scope,  # type: ignore[arg-type]
        detected_in_text=operator_text or f"{component} - {reason}",
    )
    bypass_id = bypass_handler.log_bypass(
        directive, project_id=project_id, db_path=str(DB_PATH)
    )
    return {"ok": True, "bypass_id": bypass_id}


def _selftest() -> int:
    """Verify the server wiring without starting the stdio loop."""
    _ensure_db()

    # DB has the 8 tables.
    conn = db.get_conn(str(DB_PATH))
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    expected = {
        "projects",
        "shots",
        "soul_ids",
        "elements",
        "reference_packs",
        "jobs",
        "workflows_cache",
        "bypass_log",
    }
    assert expected.issubset(names), f"missing tables: {expected - names}"

    # Tools are registered (FastMCP stores them in a registry).
    import asyncio

    tools = asyncio.run(mcp.list_tools())
    tool_names = {t.name for t in tools}
    required_tools = {
        "aurora_classify_intent",
        "aurora_create_video_brief",
        "aurora_validate_preproduction_packet",
        "aurora_log_bypass",
    }
    assert required_tools.issubset(
        tool_names
    ), f"missing tools: {required_tools - tool_names}"

    # Gate runs on an empty packet (should report missing, not crash).
    res = gate_preproduction_packet.validate_packet({})
    assert res.passed is False and len(res.missing) > 0

    # Templates load.
    for tmpl in (
        "video_brief.yaml",
        "shot_list.yaml",
        "biomechanical_motion_plan.yaml",
    ):
        assert (REPO_ROOT / "templates" / tmpl).exists(), f"missing template {tmpl}"

    print("AURORA MCP self-test OK")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    _ensure_db()
    use_http = "--http" in sys.argv or os.environ.get("AURORA_HTTP") == "1"
    if use_http:
        # Streamable HTTP transport — the MCP endpoint is served at /mcp.
        # This is the mode a remote/custom connector points at.
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

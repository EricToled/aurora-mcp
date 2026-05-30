# AURORA — Visual Production AI Orchestration

Sprint 1 build. Status: working MCP server + 3 templates + 2 gates + skill wrapper.

## Quick start

1. Restart Claude Desktop completely (quit, kill all background processes, re-open).
2. In any Claude conversation, type `aurora` or "create a video brief" — the skill should trigger.

## Scope of this build (Sprint 1)

- SQLite state (8 tables)
- Templates: video_brief, shot_list, biomechanical_motion_plan
- bypass_handler (full)
- gate_preproduction_packet (full)
- MCP server with 4 tools
- aurora-skill.md (live)

## Out of scope (Sprints 2-8 — future sessions)

- theme_resolver full impl
- biomechanical_check with sub-domain rules
- prompt_builder per-platform templates
- tribal_mining with WebSearch
- platform_adapters (higgsfield_mcp, higgsfield_ui_guide)
- gate_step_0_quality_ceiling
- gate_continuity_anchors
- routers/ui_vs_mcp full matrix
- workflows/ YAML population

## Running tests

```
cd aurora-system
.venv\Scripts\activate
pytest -v
```

## Bypass syntax (operator override)

- `OVERRIDE: <component> - <reason>` — single gate, current turn
- `OVERRIDE PERSIST: <component> - <reason>` — until revoked
- `REVOKE OVERRIDE: <component>` — revoke a persist bypass
- `BYPASS AURORA - <reason>` — full bypass, current turn
- `/override <component> - <reason>` — slash equivalent
- `/bypass-all - <reason>` — full bypass slash equivalent

Bypassable components: `gate_step_0`, `gate_preproduction_packet`, `gate_continuity_anchors`, `biomechanical_check`, `prompt_linter`, `router_ui_vs_mcp`, `model_selection`, `tribal_mining_freshness`, `theme_resolver`, `all`.

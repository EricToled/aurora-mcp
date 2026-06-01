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

## Genesis Model Selection

The **default genesis image model is `gpt_image_2`** — for both character
portraits and studio-backdrop locations, generated on a neutral white/light-gray
background with a scene-agnostic prompt so the element is reusable across scenes.
Defaults and validated params live in `aurora_model_defaults/gpt_image_2.yaml`;
reusable base prompts live in `aurora_prompt_library/`.

Routing to any **other** genesis model is a *deviation* and is policed
deterministically by `src/aurora/genesis_policy.py`:

- `aurora_create_decision_sheet` auto-injects an un-acknowledged
  `platform_genesis_deviation` skeleton on any `model_routing` genesis decision
  whose value ≠ `gpt_image_2`.
- `aurora_approve_decision_sheet` (operator-token authenticated) marks the
  deviation `operator_acknowledged` on approval.
- `aurora_emit_execution_pack` hard-blocks with status
  `GENESIS_DEVIATION_BLOCKED` unless the deviation is acknowledged **and** its
  rationale clears the whitelist. Authorized deviations are written to the
  `audit_log` as `GENESIS_DEVIATION_AUTHORIZED`.

Accepted deviation reasons (whitelist): operator explicitly requested a specific
model; on-image text/packaging typography; real-person `soul_id` identity;
approved Higgsfield reference element; unsupported aspect ratio/resolution;
`gpt_image_2` unavailable/failed verification. Generic excuses (*cinematic look*,
*premium quality*, *photorealistic*, *Claude prefers it*) are rejected.

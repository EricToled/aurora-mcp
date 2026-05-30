# AURORA Install Verification

Run these checks after Claude Code finishes the build.

## 1. Files exist

- [ ] `C:\Users\EricToledano\aurora-system\aurora.db` exists
- [ ] `C:\Users\EricToledano\aurora-system\.venv\Scripts\python.exe` exists
- [ ] `aurora-skill.md` placed in skills folder (path documented in Claude Code's final report)

## 2. Tests pass

```
cd C:\Users\EricToledano\aurora-system
.venv\Scripts\activate
pytest -v
```

Expected: all 14 tests pass (6 bypass + 5 gate + 3 db).

## 3. MCP server self-test

```
.venv\Scripts\python.exe -m aurora.server --selftest
```

Expected output: `AURORA MCP self-test OK` and exit 0.

## 4. SQLite has 8 tables

```
sqlite3 aurora.db ".tables"
```

Expected: `bypass_log  elements  jobs  projects  reference_packs  shots  soul_ids  workflows_cache`

Note: once a video brief has been created (tool `aurora_create_video_brief`), a 9th
lazy companion table `briefs` appears. This is by design — `init_db` always yields
exactly the 8 spec tables; `briefs` is created on first write so brief round-trips
work without bloating the documented schema.

## 5. Claude Desktop config — KNOWN ISSUE (read this)

The build script attempted to add an `mcpServers.aurora` entry to
`C:\Users\EricToledano\AppData\Roaming\Claude\claude_desktop_config.json`, but
this Claude Desktop build (Cowork / DXT variant) **owns and rewrites that file**
on every UI state change and **strips unknown keys** like `mcpServers`. The edit
was applied successfully but overwritten by the running app within ~3 seconds.

Consequence: AURORA's MCP server is **NOT** registered with Claude Desktop via
this file, and cannot be by editing it. The 4 MCP tools work when invoked
directly in Python (verified) but are not yet reachable from a Claude
conversation.

To make the MCP tools reachable, register AURORA through the Claude Desktop UI as
a custom connector / local MCP extension, pointing at:

- Command: `C:\Users\EricToledano\aurora-system\.venv\Scripts\python.exe`
- Args: `-m aurora.server`
- Working dir: `C:\Users\EricToledano\aurora-system`

The `aurora` skill is correctly installed (Section 6) and will trigger, but until
the MCP server is registered the skill's tool calls will fail. A clean backup of
the original config is at `claude_desktop_config.json.aurora-backup`.

## 6. How AURORA actually runs on this build (terminal CLI)

This Cowork / Claude Code desktop build does NOT load a local MCP server and
re-syncs its marketplace skills folder (wiping side-loaded skills). So AURORA
runs as a terminal CLI, driven by the `aurora` skill.

The skill is installed at the personal (non-marketplace) location:
`C:\Users\EricToledano\.claude\skills\aurora\SKILL.md`

Drive AURORA directly from the terminal anytime:

```
set PY=C:\Users\EricToledano\aurora-system\.venv\Scripts\python.exe
%PY% -m aurora.cli classify --text "8s hero ad for Sports World"
%PY% -m aurora.cli parse-bypass --text "OVERRIDE: gate_step_0 - reason"
%PY% -m aurora.cli validate-packet --json-file packet.json
%PY% -m aurora.cli create-brief --json-file brief.json
%PY% -m aurora.cli log-bypass --component gate_step_0 --reason "rapid proto"
```

In a chat, typing `aurora ...` should trigger the skill, which then runs these
commands for you.

## 7. Bypass parsing + logging works

```
set PY=C:\Users\EricToledano\aurora-system\.venv\Scripts\python.exe
%PY% -m aurora.cli log-bypass --component gate_preproduction_packet --reason "test bypass"
sqlite3 aurora.db "SELECT * FROM bypass_log ORDER BY timestamp DESC LIMIT 1;"
```

Expected: a row with `component_bypassed='gate_preproduction_packet'`.

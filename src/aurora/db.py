"""SQLite helpers for AURORA Sprint 1.

Briefs are stored verbatim as JSON in a lightweight companion ``briefs`` table
(created lazily here) so create/fetch round-trips preserve every field. The
8 schema tables come from schema/aurora_schema.sql.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "aurora.db"
SCHEMA_PATH = REPO_ROOT / "schema" / "aurora_schema.sql"

# A small companion table for full brief round-trips (Sprint 1).
_BRIEFS_DDL = """
CREATE TABLE IF NOT EXISTS briefs (
  brief_id TEXT PRIMARY KEY,
  project_id TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  brief_json TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """Open a connection with row access by name.

    Sprint 1 trade-off: foreign keys are left OFF (sqlite default) so the
    bypass audit trail can carry informational related_job_id values that may
    reference jobs not yet persisted. The companion ``briefs`` table is created
    lazily so brief round-trips work without bloating the 8-table schema.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_briefs_table(conn: sqlite3.Connection) -> None:
    """Create the lazy briefs companion table on first brief operation."""
    conn.execute(_BRIEFS_DDL)


def init_db(db_path: Optional[str | Path] = None) -> list[str]:
    """Apply the 8-table schema. Returns table names.

    The companion ``briefs`` table is intentionally NOT created here; it is
    created lazily by get_conn so init_db yields exactly the 8 spec tables.
    """
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(Path(db_path) if db_path else DEFAULT_DB_PATH))
    try:
        conn.executescript(schema_sql)
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------
def insert_brief(
    brief: dict[str, Any],
    db_path: Optional[str | Path] = None,
    project_id: Optional[str] = None,
) -> str:
    """Persist a brief dict. Generates brief_id/created_at if absent. Returns id."""
    brief = dict(brief)
    brief_id = brief.get("brief_id") or str(uuid.uuid4())
    brief["brief_id"] = brief_id
    if not brief.get("created_at"):
        brief["created_at"] = _now_iso()

    conn = get_conn(db_path)
    try:
        _ensure_briefs_table(conn)
        conn.execute(
            "INSERT INTO briefs (brief_id, project_id, created_at, brief_json) "
            "VALUES (?, ?, ?, ?)",
            (brief_id, project_id, brief["created_at"], json.dumps(brief)),
        )
        conn.commit()
        return brief_id
    finally:
        conn.close()


def get_brief(
    brief_id: str, db_path: Optional[str | Path] = None
) -> Optional[dict[str, Any]]:
    """Fetch a brief by id, returning the full brief dict or None."""
    conn = get_conn(db_path)
    try:
        _ensure_briefs_table(conn)
        row = conn.execute(
            "SELECT brief_json FROM briefs WHERE brief_id = ?", (brief_id,)
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["brief_json"])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def insert_project(
    operator_intent: str,
    mode: str,
    db_path: Optional[str | Path] = None,
    project_id: Optional[str] = None,
    status: str = "open",
) -> str:
    project_id = project_id or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO projects (project_id, operator_intent, mode, status) "
            "VALUES (?, ?, ?, ?)",
            (project_id, operator_intent, mode, status),
        )
        conn.commit()
        return project_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Shots
# ---------------------------------------------------------------------------
def insert_shot(
    shot: dict[str, Any],
    project_id: str,
    db_path: Optional[str | Path] = None,
    shot_id: Optional[str] = None,
) -> str:
    """Insert a shot. Complex fields are JSON-encoded. Returns shot_id."""
    shot_id = shot_id or shot.get("shot_id") or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            """
            INSERT INTO shots (
                shot_id, project_id, shot_number, duration_seconds, shot_type,
                function, camera_movement, speed_ramp,
                biomechanical_motion_plan_json, anchor_strategy_json,
                prompt_creative, prompt_technical_per_model_json,
                prompt_biomechanical, prompt_continuity, negative_constraints_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shot_id,
                project_id,
                shot.get("shot_number", 0),
                shot.get("duration_seconds", 0.0),
                shot.get("shot_type", ""),
                shot.get("function"),
                shot.get("camera_movement"),
                shot.get("speed_ramp"),
                json.dumps(shot.get("biomechanical_motion_plan")),
                json.dumps(shot.get("anchor_strategy")),
                shot.get("prompt_creative"),
                json.dumps(shot.get("prompt_technical_per_model")),
                shot.get("prompt_biomechanical"),
                shot.get("prompt_continuity"),
                json.dumps(shot.get("negative_constraints")),
            ),
        )
        conn.commit()
        return shot_id
    finally:
        conn.close()


def get_shots_for_project(
    project_id: str, db_path: Optional[str | Path] = None
) -> list[dict[str, Any]]:
    """Return all shots for a project, JSON fields decoded, ordered by number."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM shots WHERE project_id = ? ORDER BY shot_number",
            (project_id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            for json_col in (
                "biomechanical_motion_plan_json",
                "anchor_strategy_json",
                "prompt_technical_per_model_json",
                "negative_constraints_json",
            ):
                if d.get(json_col):
                    d[json_col] = json.loads(d[json_col])
            result.append(d)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bypass log
# ---------------------------------------------------------------------------
def insert_bypass_log(
    operator_turn_text: str,
    component_bypassed: str,
    reason: str,
    scope: str,
    db_path: Optional[str | Path] = None,
    project_id: Optional[str] = None,
    related_job_id: Optional[str] = None,
    job_outcome: Optional[str] = None,
) -> str:
    """Write a bypass entry. Returns the generated bypass_id."""
    bypass_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            """
            INSERT INTO bypass_log (
                bypass_id, project_id, operator_turn_text, component_bypassed,
                reason, scope, related_job_id, job_outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bypass_id,
                project_id,
                operator_turn_text,
                component_bypassed,
                reason,
                scope,
                related_job_id,
                job_outcome,
            ),
        )
        conn.commit()
        return bypass_id
    finally:
        conn.close()


def get_bypass_log(
    bypass_id: str, db_path: Optional[str | Path] = None
) -> Optional[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM bypass_log WHERE bypass_id = ?", (bypass_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

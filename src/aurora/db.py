"""SQLite helpers for AURORA v2.1 FINAL.

The canonical schema (schema/aurora_schema.sql) holds the v2.1 FINAL tables
(Sección 8) plus the original Sprint 1 tables. ``migrate_db`` upgrades an
already-deployed database in place by adding any missing columns, so the live
Render instance keeps working without a destructive rebuild.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "aurora.db"
SCHEMA_PATH = REPO_ROOT / "schema" / "aurora_schema.sql"

# Columns added to pre-existing tables by migrate_db (table -> [(col, ddl)]).
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "projects": [
        ("output_type", "output_type TEXT"),
        ("current_phase", "current_phase TEXT"),
        ("domain_session_lock_json", "domain_session_lock_json TEXT"),
        ("required_higgsfield_element_ids", "required_higgsfield_element_ids TEXT"),
    ],
    "briefs": [
        ("brief_type", "brief_type TEXT"),
        ("validated_at", "validated_at TIMESTAMP"),
        ("gate_result_json", "gate_result_json TEXT"),
    ],
    "bypass_log": [
        # A pre-existing DB predates authenticated overrides; default 0 means
        # every legacy bypass is treated as UNauthorized until re-logged with a
        # valid operator token (fail-closed).
        ("authorized", "authorized INTEGER NOT NULL DEFAULT 0"),
    ],
    "elements": [
        ("higgsfield_element_id", "higgsfield_element_id TEXT"),
        ("audit_status", "audit_status TEXT"),
        ("quality_score", "quality_score INTEGER"),
        ("usage_role", "usage_role TEXT"),
    ],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn(db_path: Optional[str | Path] = None) -> sqlite3.Connection:
    """Open a connection with row access by name. Foreign keys stay OFF so the
    audit trail can carry informational references to not-yet-persisted rows."""
    path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1] for r in rows}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _migrate_briefs_brief_type_check(conn: sqlite3.Connection) -> None:
    """Widen the briefs.brief_type CHECK to allow 'artifact:%' rows.

    SQLite cannot ALTER a CHECK constraint, so rebuild the table when an older
    DB still carries the narrow constraint. Idempotent: a no-op once the live
    DDL already permits artifact rows.
    """
    if not _table_exists(conn, "briefs"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='briefs'"
    ).fetchone()
    ddl = (row[0] if row else "") or ""
    if "artifact:%" in ddl:
        return  # already widened

    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE briefs_new (
          brief_id TEXT PRIMARY KEY,
          project_id TEXT REFERENCES projects(project_id),
          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
          brief_type TEXT CHECK(brief_type IN ('image','video','multishot')
            OR brief_type LIKE 'artifact:%' OR brief_type IS NULL),
          brief_json TEXT NOT NULL,
          validated_at TIMESTAMP,
          gate_result_json TEXT
        );
        INSERT INTO briefs_new (brief_id, project_id, created_at, brief_type,
          brief_json, validated_at, gate_result_json)
          SELECT brief_id, project_id, created_at, brief_type, brief_json,
                 validated_at, gate_result_json FROM briefs;
        DROP TABLE briefs;
        ALTER TABLE briefs_new RENAME TO briefs;
        CREATE INDEX IF NOT EXISTS idx_briefs_project ON briefs(project_id);
        PRAGMA foreign_keys=ON;
        """
    )
    conn.commit()


def migrate_db(conn: sqlite3.Connection) -> None:
    """Idempotently add any columns missing from a pre-existing database."""
    for table, cols in _MIGRATIONS.items():
        if not _table_exists(conn, table):
            continue
        existing = _table_columns(conn, table)
        for name, ddl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    conn.commit()
    _migrate_briefs_brief_type_check(conn)


def init_db(db_path: Optional[str | Path] = None) -> list[str]:
    """Apply the schema and run migrations. Returns table names."""
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_conn(db_path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
        migrate_db(conn)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]
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
    output_type: Optional[str] = None,
    current_phase: Optional[str] = None,
) -> str:
    project_id = project_id or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO projects (project_id, operator_intent, mode, status, "
            "output_type, current_phase) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, operator_intent, mode, status, output_type, current_phase),
        )
        conn.commit()
        return project_id
    finally:
        conn.close()


def get_project(
    project_id: str, db_path: Optional[str | Path] = None
) -> Optional[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_projects(
    limit: int = 25, db_path: Optional[str | Path] = None
) -> list[dict[str, Any]]:
    """Recent projects (newest first) for the Operator Console status picker.

    Returns only the lightweight columns the console needs to populate its
    dropdown — full per-project state is fetched on demand via get_project +
    get_latest_gate_evaluations. No secret or token material is involved."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT project_id, operator_intent, mode, status, current_phase, "
            "created_at FROM projects ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


_PROJECT_UPDATABLE = {
    "status",
    "output_type",
    "current_phase",
    "domain_session_lock_json",
    "required_higgsfield_element_ids",
}


def update_project(
    project_id: str, db_path: Optional[str | Path] = None, **fields: Any
) -> None:
    """Update whitelisted project columns. JSON-encodes dict/list values."""
    sets, params = [], []
    for key, value in fields.items():
        if key not in _PROJECT_UPDATABLE:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value)
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return
    params.append(project_id)
    conn = get_conn(db_path)
    try:
        conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE project_id = ?", params
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------
def insert_brief(
    brief: dict[str, Any],
    db_path: Optional[str | Path] = None,
    project_id: Optional[str] = None,
    brief_type: Optional[str] = None,
) -> str:
    """Persist a brief dict verbatim. Returns brief_id."""
    brief = dict(brief)
    brief_id = brief.get("brief_id") or str(uuid.uuid4())
    brief["brief_id"] = brief_id
    if not brief.get("created_at"):
        brief["created_at"] = _now_iso()
    project_id = project_id or brief.get("project_id")

    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO briefs (brief_id, project_id, created_at, brief_type, "
            "brief_json) VALUES (?, ?, ?, ?, ?)",
            (brief_id, project_id, brief["created_at"], brief_type, json.dumps(brief)),
        )
        conn.commit()
        return brief_id
    finally:
        conn.close()


def get_brief(
    brief_id: str, db_path: Optional[str | Path] = None
) -> Optional[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT brief_json FROM briefs WHERE brief_id = ?", (brief_id,)
        ).fetchone()
        return json.loads(row["brief_json"]) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Project artifacts (interim check results) — stored as typed brief rows so the
# Execution Pack can later assemble its gate context from persisted state.
# ---------------------------------------------------------------------------
def put_artifact(
    project_id: str,
    kind: str,
    data: Any,
    db_path: Optional[str | Path] = None,
) -> str:
    """Persist an interim artifact (packet, motion_plan, prompt_packet, etc.)
    as a typed brief row. Returns the artifact (brief) id."""
    artifact_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO briefs (brief_id, project_id, created_at, brief_type, "
            "brief_json) VALUES (?, ?, ?, ?, ?)",
            (artifact_id, project_id, _now_iso(), f"artifact:{kind}", json.dumps(data)),
        )
        conn.commit()
        return artifact_id
    finally:
        conn.close()


def get_artifact(
    project_id: str, kind: str, db_path: Optional[str | Path] = None
) -> Optional[Any]:
    """Read the most recent artifact of ``kind`` for a project, or None."""
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT brief_json FROM briefs WHERE project_id = ? AND brief_type = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (project_id, f"artifact:{kind}"),
        ).fetchone()
        return json.loads(row["brief_json"]) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Benchmark refs
# ---------------------------------------------------------------------------
def insert_benchmark_ref(
    project_id: str,
    url_or_path: str,
    visual_traits: dict[str, Any],
    db_path: Optional[str | Path] = None,
    benchmark_id: Optional[str] = None,
) -> str:
    benchmark_id = benchmark_id or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO benchmark_refs (benchmark_id, project_id, url_or_path, "
            "visual_traits_json) VALUES (?, ?, ?, ?)",
            (benchmark_id, project_id, url_or_path, json.dumps(visual_traits)),
        )
        conn.commit()
        return benchmark_id
    finally:
        conn.close()


def get_benchmark_refs(
    project_id: str, db_path: Optional[str | Path] = None
) -> list[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM benchmark_refs WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["visual_traits"] = json.loads(d.pop("visual_traits_json"))
            out.append(d)
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Route registry
# ---------------------------------------------------------------------------
def insert_route(
    project_id: Optional[str],
    feature_name: str,
    route_type: str,
    route_data: dict[str, Any],
    verification_source: Optional[str] = None,
    confidence: float = 0.0,
    db_path: Optional[str | Path] = None,
    route_id: Optional[str] = None,
) -> str:
    route_id = route_id or route_data.get("route_id") or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO route_registry (route_id, project_id, "
            "feature_name, route_type, verification_source, verified_at, "
            "confidence, route_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                route_id,
                project_id,
                feature_name,
                route_type,
                verification_source,
                _now_iso() if verification_source else None,
                confidence,
                json.dumps(route_data),
            ),
        )
        conn.commit()
        return route_id
    finally:
        conn.close()


def get_routes(
    project_id: str, db_path: Optional[str | Path] = None
) -> list[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM route_registry WHERE project_id = ? OR project_id IS NULL",
            (project_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["route"] = json.loads(d.pop("route_json"))
            out.append(d)
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Capability snapshots
# ---------------------------------------------------------------------------
def insert_capability_snapshot(
    refresh_scope: str,
    source: str,
    snapshot: dict[str, Any],
    diff_from_previous: Optional[dict[str, Any]] = None,
    db_path: Optional[str | Path] = None,
    snapshot_id: Optional[str] = None,
) -> str:
    snapshot_id = snapshot_id or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO capability_snapshots (snapshot_id, refresh_scope, source, "
            "snapshot_json, diff_from_previous_json) VALUES (?, ?, ?, ?, ?)",
            (
                snapshot_id,
                refresh_scope,
                source,
                json.dumps(snapshot),
                json.dumps(diff_from_previous) if diff_from_previous else None,
            ),
        )
        conn.commit()
        return snapshot_id
    finally:
        conn.close()


def get_latest_snapshot(
    db_path: Optional[str | Path] = None,
) -> Optional[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM capability_snapshots ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["snapshot"] = json.loads(d.pop("snapshot_json"))
        if d.get("diff_from_previous_json"):
            d["diff_from_previous"] = json.loads(d.pop("diff_from_previous_json"))
        return d
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def insert_audit(
    project_id: Optional[str],
    criterion: str,
    verdict: str,
    notes: Optional[str],
    audited_by: str,
    higgsfield_job_id: Optional[str] = None,
    higgsfield_element_id: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> str:
    audit_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO audit_log (audit_id, project_id, higgsfield_job_id, "
            "higgsfield_element_id, criterion, verdict, notes, audited_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                project_id,
                higgsfield_job_id,
                higgsfield_element_id,
                criterion,
                verdict,
                notes,
                audited_by,
            ),
        )
        conn.commit()
        return audit_id
    finally:
        conn.close()


def get_audits(
    project_id: str, db_path: Optional[str | Path] = None
) -> list[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Quality scores
# ---------------------------------------------------------------------------
def insert_quality_score(
    project_id: str,
    score_type: str,
    score_data: dict[str, Any],
    total_score: int,
    scored_by: str = "aurora",
    hard_fail_reason: Optional[str] = None,
    higgsfield_job_id: Optional[str] = None,
    higgsfield_element_id: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> str:
    score_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO quality_scores (score_id, project_id, higgsfield_job_id, "
            "higgsfield_element_id, score_type, score_json, total_score, "
            "hard_fail_reason, scored_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                score_id,
                project_id,
                higgsfield_job_id,
                higgsfield_element_id,
                score_type,
                json.dumps(score_data),
                int(total_score),
                hard_fail_reason,
                scored_by,
            ),
        )
        conn.commit()
        return score_id
    finally:
        conn.close()


def get_quality_scores(
    project_id: str,
    score_type: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        if score_type:
            rows = conn.execute(
                "SELECT * FROM quality_scores WHERE project_id = ? AND score_type = ? "
                "ORDER BY created_at",
                (project_id, score_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM quality_scores WHERE project_id = ? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["score"] = json.loads(d.pop("score_json"))
            out.append(d)
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Execution packs
# ---------------------------------------------------------------------------
def insert_execution_pack(
    project_id: str,
    anchors_approved_count: int = 0,
    anchors_required_count: int = 0,
    success_criteria: Optional[list[str]] = None,
    version: int = 1,
    db_path: Optional[str | Path] = None,
    pack_id: Optional[str] = None,
) -> str:
    pack_id = pack_id or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO execution_packs (pack_id, project_id, version, "
            "anchors_approved_count, anchors_required_count, success_criteria_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                pack_id,
                project_id,
                version,
                anchors_approved_count,
                anchors_required_count,
                json.dumps(success_criteria or []),
            ),
        )
        conn.commit()
        return pack_id
    finally:
        conn.close()


def get_execution_pack(
    pack_id: str, db_path: Optional[str | Path] = None
) -> Optional[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM execution_packs WHERE pack_id = ?", (pack_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("success_criteria_json"):
            d["success_criteria"] = json.loads(d.pop("success_criteria_json"))
        return d
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Shots (Sprint 1 compat)
# ---------------------------------------------------------------------------
def insert_shot(
    shot: dict[str, Any],
    project_id: str,
    db_path: Optional[str | Path] = None,
    shot_id: Optional[str] = None,
) -> str:
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
# Elements (Higgsfield element registry — metadata only)
# ---------------------------------------------------------------------------
def insert_element(
    project_id: Optional[str],
    element_type: str,
    name: str,
    sheet: dict[str, Any],
    higgsfield_element_id: Optional[str] = None,
    audit_status: Optional[str] = None,
    quality_score: Optional[int] = None,
    usage_role: Optional[str] = None,
    db_path: Optional[str | Path] = None,
    element_id: Optional[str] = None,
) -> str:
    element_id = element_id or str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO elements (element_id, project_id, element_type, name, "
            "sheet_json, higgsfield_element_id, audit_status, quality_score, "
            "usage_role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                element_id,
                project_id,
                element_type,
                name,
                json.dumps(sheet),
                higgsfield_element_id,
                audit_status,
                quality_score,
                usage_role,
            ),
        )
        conn.commit()
        return element_id
    finally:
        conn.close()


def get_elements(
    project_id: str, db_path: Optional[str | Path] = None
) -> list[dict[str, Any]]:
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM elements WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("sheet_json"):
                d["sheet"] = json.loads(d["sheet_json"])
            out.append(d)
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bypass log + active bypasses
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
    authorized: bool = False,
) -> str:
    bypass_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            """
            INSERT INTO bypass_log (
                bypass_id, project_id, operator_turn_text, component_bypassed,
                reason, scope, related_job_id, job_outcome, authorized
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                1 if authorized else 0,
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


def set_active_bypass(
    component: str,
    scope: str,
    reason: str,
    project_id: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> None:
    """Record/refresh a persist|all_session bypass as active (revoked_at=NULL)."""
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO active_bypasses (component, project_id, scope, reason, "
            "created_at, revoked_at) VALUES (?, ?, ?, ?, ?, NULL) "
            "ON CONFLICT(component) DO UPDATE SET scope=excluded.scope, "
            "reason=excluded.reason, project_id=excluded.project_id, "
            "created_at=excluded.created_at, revoked_at=NULL",
            (component, project_id, scope, reason, _now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def revoke_active_bypass(component: str, db_path: Optional[str | Path] = None) -> None:
    conn = get_conn(db_path)
    try:
        conn.execute(
            "UPDATE active_bypasses SET revoked_at = ? WHERE component = ? "
            "AND revoked_at IS NULL",
            (_now_iso(), component),
        )
        conn.commit()
    finally:
        conn.close()


def get_logged_bypasses_for_project(
    project_id: str, db_path: Optional[str | Path] = None
) -> dict[str, str]:
    """Return {component: reason} for current_turn bypasses logged against this
    project. current_turn bypasses are not promoted to active_bypasses, so emit
    reads them here to honor operator sovereignty within the project (bug #9).

    Only AUTHORIZED bypasses (authorized=1, i.e. accompanied by a valid operator
    token) are returned. Unauthenticated bypass rows are recorded for audit but
    are NEVER honored — Claude cannot forge operator consent (anti-invention)."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT component_bypassed, reason FROM bypass_log "
            "WHERE project_id = ? AND scope = 'current_turn' AND authorized = 1 "
            "ORDER BY timestamp ASC, rowid ASC",
            (project_id,),
        ).fetchall()
        return {r["component_bypassed"]: r["reason"] for r in rows}
    finally:
        conn.close()


def get_active_bypasses(db_path: Optional[str | Path] = None) -> dict[str, str]:
    """Return {component: reason} for all non-revoked active bypasses."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT component, reason FROM active_bypasses WHERE revoked_at IS NULL"
        ).fetchall()
        return {r["component"]: r["reason"] for r in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Security events (tamper-evident anti-invention alarm trail)
# ---------------------------------------------------------------------------
def insert_security_event(
    event_type: str,
    project_id: Optional[str] = None,
    component: Optional[str] = None,
    detail: Any = None,
    severity: str = "halt",
    db_path: Optional[str | Path] = None,
) -> str:
    """Record a security event (e.g. an unauthorized bypass / invention attempt).

    These rows are the persistent alarm trail: while unresolved, emit refuses to
    produce an Execution Pack and returns a SECURITY_HALT. detail is JSON-encoded.
    Returns the new event_id."""
    event_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO security_events (event_id, project_id, event_type, "
            "severity, component, detail_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                event_id,
                project_id,
                event_type,
                severity,
                component,
                json.dumps(detail) if detail is not None else None,
            ),
        )
        conn.commit()
        return event_id
    finally:
        conn.close()


def get_security_events(
    project_id: Optional[str] = None,
    unresolved_only: bool = True,
    db_path: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """Return security events, newest first. By default only unresolved (active
    alarm) events. When project_id is given, also includes global events with a
    NULL project_id so a system-wide halt cannot be sidestepped by a new project."""
    conn = get_conn(db_path)
    try:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)
        if unresolved_only:
            clauses.append("resolved_at IS NULL")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(
            "SELECT * FROM security_events" + where
            + " ORDER BY created_at DESC, rowid DESC",
            tuple(params),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            if d.get("detail_json"):
                try:
                    d["detail"] = json.loads(d["detail_json"])
                except (ValueError, TypeError):
                    d["detail"] = None
            out.append(d)
        return out
    finally:
        conn.close()


def resolve_security_events(
    project_id: Optional[str] = None,
    component: Optional[str] = None,
    event_type: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> int:
    """Mark matching unresolved security events as resolved. Returns the count.

    Used when a step is honestly re-attested clean after a confessed invention:
    the prior alarm for that step is cleared so the pipeline can proceed."""
    conn = get_conn(db_path)
    try:
        clauses = ["resolved_at IS NULL"]
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if component is not None:
            clauses.append("component = ?")
            params.append(component)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        cur = conn.execute(
            "UPDATE security_events SET resolved_at = ? WHERE " + " AND ".join(clauses),
            tuple([_now_iso()] + params),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Single-use ledger for rotating operator tokens (anti-invention, Fase 2)
# ---------------------------------------------------------------------------
def try_consume_token(
    counter: int,
    token: str,
    purpose: str,
    project_id: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> bool:
    """Atomically burn a (counter, token) pair so it unlocks exactly one action.

    Returns True the FIRST time a token is presented for its window and False on
    every replay. The (counter, token) primary key makes the burn race-free: a
    second INSERT of the same pair raises IntegrityError, which we translate to
    False. The caller has already proven the token is cryptographically valid via
    totp.verify(); this is the single-use half of Eric's mandate (a code is dead
    after one gate/bypass even inside its 60s window)."""
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO consumed_tokens (counter, token, purpose, project_id) "
            "VALUES (?, ?, ?, ?)",
            (counter, token, purpose, project_id),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_event_feed(
    limit: int = 50,
    db_path: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """Recent security events for the Operator Console feed (newest first).

    Unlike get_security_events this includes BOTH resolved and unresolved rows so
    Eric sees the full timeline of AURORA blocks/halts — the "avisos de bloqueo"
    he uses to question Claude. Each row is flattened to the fields the browser
    renders; detail_json is parsed. No secret or token value is ever exposed."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT event_id, created_at, project_id, event_type, severity, "
            "component, detail_json, resolved_at FROM security_events "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            detail = None
            if d.get("detail_json"):
                try:
                    detail = json.loads(d["detail_json"])
                except (ValueError, TypeError):
                    detail = None
            out.append({
                "event_id": d["event_id"],
                "created_at": d["created_at"],
                "project_id": d["project_id"],
                "event_type": d["event_type"],
                "severity": d["severity"],
                "component": d["component"],
                "detail": detail,
                "resolved": d["resolved_at"] is not None,
            })
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Per-step honesty attestation (anti-invention, content-level)
# ---------------------------------------------------------------------------
def insert_step_attestation(
    project_id: str,
    step: str,
    invented: bool,
    invented_fields: Optional[list[str]] = None,
    sources: Any = None,
    notes: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> str:
    """Record a per-step honesty attestation, superseding any prior attestation
    for the same (project, step). Returns the new attestation_id.

    invented=True is a confession of fabricated content for the step; invented=
    False seals the step as truthful. Only the latest (non-superseded) row counts
    at emit time."""
    attestation_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "UPDATE step_attestations SET superseded_at = ? "
            "WHERE project_id = ? AND step = ? AND superseded_at IS NULL",
            (_now_iso(), project_id, step),
        )
        conn.execute(
            "INSERT INTO step_attestations (attestation_id, project_id, step, "
            "invented, invented_fields, sources_json, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                attestation_id,
                project_id,
                step,
                1 if invented else 0,
                json.dumps(invented_fields or []),
                json.dumps(sources) if sources is not None else None,
                notes,
            ),
        )
        conn.commit()
        return attestation_id
    finally:
        conn.close()


def get_current_step_attestations(
    project_id: str, db_path: Optional[str | Path] = None
) -> dict[str, dict[str, Any]]:
    """Return {step: attestation_row} for the latest (non-superseded) attestation
    of each step in the project."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM step_attestations "
            "WHERE project_id = ? AND superseded_at IS NULL "
            "ORDER BY created_at ASC, rowid ASC",
            (project_id,),
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            d = dict(r)
            if d.get("invented_fields"):
                try:
                    d["invented_fields"] = json.loads(d["invented_fields"])
                except (ValueError, TypeError):
                    d["invented_fields"] = []
            out[d["step"]] = d
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Gate evaluations (persist-then-read; Sección 10)
# ---------------------------------------------------------------------------
def put_gate_evaluation(
    project_id: str,
    gate_name: str,
    status: str,
    score: Optional[int] = None,
    reasons: Optional[list[str]] = None,
    notes: Optional[str] = None,
    packet: Any = None,
    evaluator_version: Optional[str] = None,
    db_path: Optional[str | Path] = None,
) -> str:
    """Persist a gate verdict + the input snapshot that produced it. Returns id.

    status must be one of pass|fail|warning (CHECK-enforced)."""
    evaluation_id = str(uuid.uuid4())
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO gate_evaluations (evaluation_id, project_id, gate_name, "
            "status, score, reasons_json, notes, packet_json, evaluator_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evaluation_id,
                project_id,
                gate_name,
                status,
                int(score) if score is not None else None,
                json.dumps(reasons or []),
                notes,
                json.dumps(packet) if packet is not None else None,
                evaluator_version,
            ),
        )
        conn.commit()
        return evaluation_id
    finally:
        conn.close()


def get_latest_gate_evaluations(
    project_id: str, db_path: Optional[str | Path] = None
) -> dict[str, dict[str, Any]]:
    """Return {gate_name: latest_evaluation_row} for a project (most recent per
    gate_name). reasons_json/packet_json are decoded into reasons/packet."""
    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM gate_evaluations WHERE project_id = ? "
            "ORDER BY evaluated_at ASC, rowid ASC",
            (project_id,),
        ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for r in rows:
            d = dict(r)
            d["reasons"] = json.loads(d.get("reasons_json") or "[]")
            d["packet"] = (
                json.loads(d["packet_json"]) if d.get("packet_json") else None
            )
            latest[d["gate_name"]] = d  # later rows overwrite earlier -> newest wins
        return latest
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Platform syntax cache (v2.3 — research-driven prompt construction)
# ---------------------------------------------------------------------------
def insert_syntax_dossier(
    model_id: str,
    output_type: str,
    syntax_dossier: dict[str, Any],
    sources: list[dict[str, Any]],
    source_types_covered: list[str],
    ttl_days: int = 30,
    confidence: float = 0.0,
    researched_by: str = "operator_via_research_skill",
    db_path: Optional[str | Path] = None,
) -> str:
    """Persist a researched syntax_dossier for a (model_id, output_type) with a
    TTL. Returns the cache_id. Newer rows win (read path orders by fetched_at)."""
    cache_id = str(uuid.uuid4())
    fetched_at = _now_iso()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=int(ttl_days))
    ).isoformat()
    conn = get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO platform_syntax_cache (cache_id, model_id, output_type, "
            "syntax_dossier_json, sources_json, source_types_covered_json, "
            "fetched_at, expires_at, confidence, researched_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cache_id,
                model_id,
                output_type,
                json.dumps(syntax_dossier),
                json.dumps(sources),
                json.dumps(sorted(source_types_covered)),
                fetched_at,
                expires_at,
                float(confidence),
                researched_by,
            ),
        )
        conn.commit()
        return cache_id
    finally:
        conn.close()


def get_latest_syntax_dossier(
    model_id: str, output_type: str, db_path: Optional[str | Path] = None
) -> Optional[dict[str, Any]]:
    """Return the most-recently-fetched dossier row for (model_id, output_type),
    or None. JSON columns are decoded into syntax_dossier/sources/source_types.
    The caller decides freshness by comparing expires_at to now (ISO strings)."""
    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM platform_syntax_cache WHERE model_id = ? AND "
            "output_type = ? ORDER BY fetched_at DESC, rowid DESC LIMIT 1",
            (model_id, output_type),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["syntax_dossier"] = json.loads(d.get("syntax_dossier_json") or "{}")
        d["sources"] = json.loads(d.get("sources_json") or "[]")
        d["source_types_covered"] = json.loads(
            d.get("source_types_covered_json") or "[]"
        )
        return d
    finally:
        conn.close()

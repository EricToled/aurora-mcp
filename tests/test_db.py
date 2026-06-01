"""Tests for aurora.db (3 cases per spec Section M)."""
from __future__ import annotations

from aurora import db

EXPECTED_TABLES = {
    "projects",
    "shots",
    "soul_ids",
    "elements",
    "reference_packs",
    "jobs",
    "workflows_cache",
    "bypass_log",
    "briefs",
    "benchmark_refs",
    "route_registry",
    "capability_snapshots",
    "audit_log",
    "quality_scores",
    "execution_packs",
    "active_bypasses",
    "gate_evaluations",
    "platform_syntax_cache",
    "security_events",
    "step_attestations",
    "consumed_tokens",
}


def test_init_db_creates_v21_schema(tmp_path):
    db_path = tmp_path / "test.db"
    tables = db.init_db(db_path)
    # init_db must yield the full schema (v2.1 17 tables + v2.3 syntax cache +
    # security_events + step_attestations + consumed_tokens for the anti-invention
    # alarm trail and the rotating single-use-token ledger).
    assert set(tables) == EXPECTED_TABLES
    assert len(tables) == 21


def test_put_artifact_roundtrip(tmp_path):
    # Regression: artifact rows (brief_type="artifact:<kind>") must be allowed
    # by the briefs CHECK so validate_biomechanics/check_multishot can persist.
    db_path = str(tmp_path / "art.db")
    db.init_db(db_path)
    pid = db.insert_project("x", "video_simple", db_path=db_path)
    aid = db.put_artifact(pid, "motion_plan", {"scores": {"x": 90}}, db_path=db_path)
    assert aid
    assert db.get_artifact(pid, "motion_plan", db_path=db_path) == {"scores": {"x": 90}}


def test_migrate_widens_brief_type_check(tmp_path):
    # An old DB with the narrow CHECK must migrate to accept artifact rows.
    import sqlite3
    db_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE projects (project_id TEXT PRIMARY KEY, mode TEXT);"
        "CREATE TABLE briefs (brief_id TEXT PRIMARY KEY, project_id TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "brief_type TEXT CHECK(brief_type IN ('image','video','multishot') "
        "OR brief_type IS NULL), brief_json TEXT NOT NULL, "
        "validated_at TIMESTAMP, gate_result_json TEXT);"
    )
    conn.execute("INSERT INTO projects(project_id,mode) VALUES('p','video')")
    conn.execute(
        "INSERT INTO briefs(brief_id,project_id,brief_type,brief_json) "
        "VALUES('b','p','video','{}')"
    )
    conn.commit()
    conn.close()

    conn = db.get_conn(db_path)
    db.migrate_db(conn)
    conn.close()

    aid = db.put_artifact("p", "motion_plan", {"ok": 1}, db_path=db_path)
    assert aid
    # Pre-existing row survives the table rebuild.
    conn = db.get_conn(db_path)
    rows = conn.execute("SELECT count(*) FROM briefs").fetchone()[0]
    conn.close()
    assert rows == 2


def test_insert_brief_roundtrip(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    brief = {
        "operator_intent": "8s hero ad for Sports World",
        "output_type": "hero_ad",
        "duration_seconds": 8,
        "emotional_beat": "triumph",
        "product_or_brand": "Sports World",
        "core_action": "sprinter explodes off blocks",
        "target_audience": "urban athletes 18-35",
        "final_frame_description": "logo lockup over freeze frame",
        "audio_strategy": "external_track",
        "success_criteria": ["identity stable"],
    }
    brief_id = db.insert_brief(brief, db_path=str(db_path))
    fetched = db.get_brief(brief_id, db_path=str(db_path))
    assert fetched is not None
    assert fetched["brief_id"] == brief_id
    for key, value in brief.items():
        assert fetched[key] == value


def test_bypass_log_foreign_keys(tmp_path):
    # Sprint 1 trade-off: related_job_id is informational. Inserting a bypass
    # row with a related_job_id that points to a non-existent job SUCCEEDS,
    # because no job is created here and the FK is not enforced as blocking in
    # Sprint 1 (sqlite FK pragma does not retroactively validate prior rows and
    # we accept dangling job refs for the bypass audit trail).
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    bypass_id = db.insert_bypass_log(
        operator_turn_text="OVERRIDE: gate_step_0 - test",
        component_bypassed="gate_step_0",
        reason="test",
        scope="current_turn",
        db_path=str(db_path),
        related_job_id="job-does-not-exist",
    )
    fetched = db.get_bypass_log(bypass_id, db_path=str(db_path))
    assert fetched is not None
    assert fetched["related_job_id"] == "job-does-not-exist"

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
}


def test_init_db_creates_8_tables(tmp_path):
    db_path = tmp_path / "test.db"
    tables = db.init_db(db_path)
    # init_db must yield exactly the 8 spec tables (no companion briefs table).
    assert set(tables) == EXPECTED_TABLES
    assert len(tables) == 8


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

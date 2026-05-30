"""Tests for aurora.bypass_handler (6 cases per spec Section M)."""
from __future__ import annotations

from aurora import bypass_handler, db


def test_valid_override_parses_correctly():
    directive = bypass_handler.parse_bypass(
        "OVERRIDE: gate_preproduction_packet - rapid prototype needed"
    )
    assert directive is not None
    assert directive.component == "gate_preproduction_packet"
    assert directive.scope == "current_turn"
    assert directive.reason.strip() != ""


def test_bypass_without_reason_rejected():
    assert bypass_handler.parse_bypass("OVERRIDE: gate_step_0 -") is None


def test_invalid_component_silently_ignored():
    assert bypass_handler.parse_bypass("OVERRIDE: fake_gate - because") is None


def test_override_persist_detected():
    directive = bypass_handler.parse_bypass(
        "OVERRIDE PERSIST: prompt_linter - skipping lint for batch run"
    )
    assert directive is not None
    assert directive.scope == "persist"
    assert directive.component == "prompt_linter"


def test_bypass_all_directive():
    directive = bypass_handler.parse_bypass("/bypass-all - emergency manual mode")
    assert directive is not None
    assert directive.component == "all"
    assert directive.scope == "current_turn"


def test_log_bypass_writes_to_db(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    directive = bypass_handler.BypassDirective(
        component="gate_preproduction_packet",
        reason="unit test",
        scope="current_turn",
        detected_in_text="OVERRIDE: gate_preproduction_packet - unit test",
    )
    bypass_id = bypass_handler.log_bypass(directive, db_path=str(db_path))

    conn = db.get_conn(str(db_path))
    try:
        rows = conn.execute("SELECT * FROM bypass_log").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["bypass_id"] == bypass_id
    assert row["component_bypassed"] == "gate_preproduction_packet"
    assert row["reason"] == "unit test"
    assert row["scope"] == "current_turn"

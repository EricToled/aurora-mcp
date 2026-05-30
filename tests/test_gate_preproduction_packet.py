"""Tests for gate_preproduction_packet (5 cases per spec Section M)."""
from __future__ import annotations

import copy

from aurora.gates import gate_preproduction_packet as gate


def _complete_packet() -> dict:
    """A fully populated, valid 12-component preproduction packet."""
    return {
        "idea": "A sprinter explodes off the blocks for a Sports World hero ad.",
        "script": {"beats": ["block start", "drive phase", "logo lockup"]},
        "shot_list": [
            {
                "shot_number": 1,
                "duration_seconds": 4.0,
                "shot_type": "action",
                "function": "hero moment",
            }
        ],
        "characters": [{"name": "Sprinter", "id": "char-1"}],
        "location": {"name": "Outdoor stadium track at dawn"},
        "props_or_product": [{"name": "Running shoes"}],
        "visual_style": "editorial sports action, anamorphic 35mm",
        "biomechanical_plan": [{"shot_id": "1", "duration_seconds": 4.0}],
        "ff_lf_strategy": "start_and_end",
        "recommended_model": "kling-3.0",
        "ui_or_mcp_route": "ui",
        "success_criteria": ["identity stable", "explosive motion reads as real"],
    }


def test_complete_packet_passes():
    result = gate.validate_packet(_complete_packet())
    assert result.passed is True
    assert result.missing == []


def test_missing_shot_list_fails():
    packet = _complete_packet()
    del packet["shot_list"]
    result = gate.validate_packet(packet)
    assert result.passed is False
    assert "shot_list" in result.missing


def test_empty_success_criteria_fails():
    packet = _complete_packet()
    packet["success_criteria"] = []
    result = gate.validate_packet(packet)
    assert result.passed is False
    assert "success_criteria" in result.missing


def test_invalid_route_enum_fails():
    packet = _complete_packet()
    packet["ui_or_mcp_route"] = "unknown"
    result = gate.validate_packet(packet)
    assert result.passed is False
    assert "ui_or_mcp_route" in result.missing


def test_warnings_do_not_block():
    # Mismatch between biomechanical_plan count and shot count -> warning, not block.
    packet = _complete_packet()
    packet["shot_list"].append(
        {
            "shot_number": 2,
            "duration_seconds": 3.0,
            "shot_type": "close_up",
            "function": "product insert",
        }
    )
    # biomechanical_plan still has 1 entry while shot_list now has 2.
    result = gate.validate_packet(packet)
    assert result.passed is True
    assert len(result.warnings) > 0

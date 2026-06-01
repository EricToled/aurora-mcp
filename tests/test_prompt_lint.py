"""Deterministic prompt-lint gate tests (migrated from the aurora-prompt-linter
skill into AURORA).

Lock in the three layers — refs redundancy (P/O/L/PR/S), required sections by
platform+case, and structure (word cap / negative / banned vocab) — plus the
emit integration: a recorded lint FAIL blocks delivery until fixed or bypassed
by an AUTHORIZED operator override.
"""
from __future__ import annotations

import pytest

from aurora import bypass_handler, db
from aurora import server as srv
from aurora.scoring import prompt_lint

OPERATOR_TOKEN = "test-operator-token"


@pytest.fixture()
def server_db(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "lint.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", OPERATOR_TOKEN)
    srv._ensure_db()
    return srv.DB_PATH


# === pure scorer ============================================================
def test_clean_prompt_passes():
    res = prompt_lint.lint(
        prompt="A lone cellist plays in candlelight.\nNegative: blurry, distorted",
        case="1", platform="")
    assert res["status"] == "PASS", res["violations"]


def test_refs_redundancy_is_flagged():
    # The ref already carries the outfit (O); re-describing it in MAIN is a FAIL.
    res = prompt_lint.lint(
        prompt="She wears a red sports bra as the camera arcs.\nNegative: blur",
        case="3a", platform="",
        refs=[{"file": "ff.jpg", "role": "FF", "tags": ["P1", "O1", "L1"]}])
    cats = {v["category"] for v in res["violations"]}
    assert "O" in cats
    assert res["status"] == "FAIL"


def test_override_clears_redundancy():
    res = prompt_lint.lint(
        prompt="She wears a red sports bra as the camera arcs.\nNegative: blur",
        case="3a", platform="",
        refs=[{"file": "ff.jpg", "role": "FF", "tags": ["O1"]}],
        overrides_text="OVERRIDE: O - the outfit visibly changes color mid-shot")
    assert res["status"] == "PASS", res["violations"]
    assert res["overrides_accepted"]


def test_motion_context_is_not_redundancy():
    # "off" in a directional/motion context must NOT be flagged as a static
    # descriptor even when categories are covered by refs.
    res = prompt_lint.lint(
        prompt="The sprinter explodes off the blocks as the camera tracks.\nNegative: blur",
        case="3a", platform="",
        refs=[{"file": "ff.jpg", "role": "FF", "tags": ["P1", "O1"]}])
    assert res["status"] == "PASS", res["violations"]


def test_missing_required_section_fails():
    # kling_3.0 case 3a requires a camera section; omit all section keywords.
    res = prompt_lint.lint(
        prompt="A quiet field at dawn.\nNegative: blur",
        case="3a", platform="kling_3.0")
    assert res["status"] == "FAIL"
    assert "camera" in res["sections_missing"]


def test_banned_vocab_in_main_fails():
    res = prompt_lint.lint(
        prompt="A runner in slow motion crosses the line.\nNegative: blur",
        case="1", platform="")
    cats = {v["category"] for v in res["violations"]}
    assert "BANNED" in cats


def test_word_count_over_hard_max_fails():
    long_main = " ".join(["motion"] * 95)
    res = prompt_lint.lint(prompt=f"{long_main}\nNegative: blur", case="3a", platform="")
    assert res["status"] == "FAIL"
    assert any(v["category"] == "STRUCTURE" and "word_count" in v["term"]
               for v in res["violations"])


def test_missing_negative_block_fails():
    res = prompt_lint.lint(prompt="A lone cellist plays in candlelight.",
                           case="1", platform="")
    assert any(v["term"] == "negative_prompt" for v in res["violations"])


def test_unknown_case_is_rejected():
    res = prompt_lint.lint(prompt="x", case="99", platform="")
    assert res["status"] == "FAIL"
    assert "Unknown case" in res["report"]


# === element reusability (character/prop Génesis) ==========================
def test_element_genesis_requires_neutral_background():
    # A character Génesis with no neutral-background statement is a FAIL.
    res = prompt_lint.lint(
        prompt="A confident athlete standing tall.\nNegative: blur",
        case="1", platform="", element_role="character")
    assert res["status"] == "FAIL"
    assert any(v["category"] == "ELEMENT" and v["term"] == "neutral_background"
               for v in res["violations"])


def test_element_genesis_flags_scene_descriptor():
    # Neutral bg present, but a scene descriptor ("forest") breaks reusability.
    res = prompt_lint.lint(
        prompt="A confident athlete on a plain white background in a forest.\nNegative: blur",
        case="1", platform="", element_role="prop")
    assert res["status"] == "FAIL"
    assert any(v["category"] == "ELEMENT" and v["term"] == "forest"
               for v in res["violations"])


def test_element_genesis_clean_passes():
    res = prompt_lint.lint(
        prompt="A confident athlete, full body, on a plain white background.\nNegative: blur",
        case="1", platform="", element_role="character")
    assert res["status"] == "PASS", res["violations"]
    assert res["element_role"] == "character"


def test_element_rules_do_not_apply_without_role():
    # Same scene-y prompt without element_role must NOT trigger ELEMENT layer.
    res = prompt_lint.lint(
        prompt="A confident athlete in a forest at sunset.\nNegative: blur",
        case="1", platform="")
    assert not any(v["category"] == "ELEMENT" for v in res["violations"])


def test_element_violation_is_overridable():
    res = prompt_lint.lint(
        prompt="A confident athlete on a plain white background in a forest.\nNegative: blur",
        case="1", platform="", element_role="character",
        overrides_text="OVERRIDE: forest - the forest is part of this prop's identity")
    assert res["status"] == "PASS", res["violations"]
    assert res["overrides_accepted"]


def test_element_category_override_clears_all():
    # OVERRIDE: ELEMENT clears the whole layer (missing neutral bg + scene term).
    res = prompt_lint.lint(
        prompt="A confident athlete in a forest.\nNegative: blur",
        case="1", platform="", element_role="character",
        overrides_text="OVERRIDE: ELEMENT - this is a deliberate in-scene reference")
    assert res["status"] == "PASS", res["violations"]


# === tool + emit integration ================================================
def test_tool_records_gate_and_blocks_emit(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    out = srv.aurora_lint_prompt(
        project_id=pid, prompt="A runner in slow motion.", case="1", platform="")
    assert out["ok"] is True
    assert out["passed"] is False  # banned vocab + missing negative
    recorded = db.get_latest_gate_evaluations(pid, db_path=str(server_db))
    assert recorded["gate_prompt_lint"]["status"] == "fail"
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["status"] == "PROMPT_LINT_FAILED"
    assert emit["violations"]


def test_clean_lint_does_not_block_on_lint(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    out = srv.aurora_lint_prompt(
        project_id=pid,
        prompt="A lone cellist plays in candlelight.\nNegative: blurry, distorted",
        case="1", platform="")
    assert out["passed"] is True
    emit = srv.aurora_emit_execution_pack(pid)
    # It will still be blocked by the normal SHAPE/attestation gates, but NOT by
    # the prompt linter.
    assert emit.get("status") != "PROMPT_LINT_FAILED"


def test_authorized_bypass_clears_lint_block(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    srv.aurora_lint_prompt(
        project_id=pid, prompt="A runner in slow motion.", case="1", platform="")
    blocked = srv.aurora_emit_execution_pack(pid)
    assert blocked["status"] == "PROMPT_LINT_FAILED"
    res = srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_prompt_lint - operator accepts",
        component="gate_prompt_lint", reason="operator accepts", scope="persist",
        project_id=pid, operator_token=OPERATOR_TOKEN)
    assert res["ok"] is True
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit.get("status") != "PROMPT_LINT_FAILED"


def test_lint_prompt_appends_attestation_directive(server_db):
    pid = srv.aurora_create_project("x", "image", "image_genesis")["project_id"]
    out = srv.aurora_lint_prompt(
        project_id=pid, prompt="A lone cellist plays.\nNegative: blur",
        case="1", platform="")
    assert out.get("attestation_required", {}).get("step") == "prompt_fitness"

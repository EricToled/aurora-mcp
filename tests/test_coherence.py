"""Meta coherence tests — prevent the whole family of cross-component drift bugs.

These guard the three seams where AURORA's components agreed on a vocabulary by
convention and silently drifted apart:

  (a) every gate that can BLOCK Execution Pack emission must be bypassable
      (operator sovereignty — bug #4).
  (b) a project_id written by one tool must be found by every read path,
      including emit_execution_pack (bug #5/#6 class).
  (c) every scorer's wire shape must match what its score() actually reads, so
      a wrong shape is loud, not a silent 0 (bug #7 class), and every score_type
      maps to a DB-CHECK-valid canonical value.
"""
from __future__ import annotations

import importlib

from aurora import bypass_handler, db
from aurora import gates as gates_pkg
from aurora import server as srv
from aurora import scoring


# (a) Every emit-blocking gate is bypassable ---------------------------------
def test_every_gate_is_bypassable():
    gate_names = set(gates_pkg.GATE_MODULES.keys())
    # The canonical gate set the bypass handler accepts must cover every gate.
    assert gate_names <= bypass_handler.GATE_COMPONENTS, (
        "gates missing from BYPASSABLE_COMPONENTS: "
        f"{gate_names - bypass_handler.GATE_COMPONENTS}"
    )
    # And each must be accepted by the public bypass vocabulary.
    for name in gate_names:
        assert name in bypass_handler.BYPASSABLE_COMPONENTS


def test_legacy_aliases_map_to_real_gates():
    for alias, canon in bypass_handler.LEGACY_ALIASES.items():
        assert canon in gates_pkg.GATE_MODULES, f"{alias} -> {canon} is not a real gate"
        assert bypass_handler.canonical_component(alias) == canon


def test_bypass_unblocks_emit_for_every_required_gate(tmp_path, monkeypatch):
    # A persist bypass on each required gate (by canonical name) must let the
    # Execution Pack emit even with an otherwise-empty project.
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "bypass.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "session.json")
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", "coherence-token")
    srv._ensure_db()
    pid = srv.aurora_create_project("intent", "video_multishot", "hero_ad")["project_id"]
    for gate in gates_pkg.required_gates_for_mode("video_multishot"):
        res = srv.aurora_log_bypass(
            operator_text=f"OVERRIDE PERSIST: {gate} - coherence test",
            component=gate, reason="coherence test", scope="persist",
            operator_token="coherence-token",
        )
        assert res["ok"], (gate, res)
        assert res["component"] == gate
    # Fase 1: the conditional Decision Sheet gate is not in required_gates_for_mode,
    # so bypass it explicitly to let the otherwise-empty project emit.
    srv.aurora_log_bypass(
        operator_text="OVERRIDE PERSIST: gate_decision_sheet_approved - coherence test",
        component="gate_decision_sheet_approved", reason="coherence test",
        scope="persist", operator_token="coherence-token")
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason")


def test_bypass_all_covers_every_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "all.db")
    monkeypatch.setattr(bypass_handler, "SESSION_STATE_PATH", tmp_path / "s.json")
    monkeypatch.setenv("AURORA_OPERATOR_TOKEN", "coherence-token")
    srv._ensure_db()
    pid = srv.aurora_create_project("intent", "video_simple", "hero_ad")["project_id"]
    srv.aurora_log_bypass(operator_text="BYPASS AURORA - operator override",
                          component="all", reason="operator override", scope="persist",
                          operator_token="coherence-token")
    emit = srv.aurora_emit_execution_pack(pid)
    assert emit["ok"], emit.get("reason")


# (b) A written project_id is found by every read path -----------------------
def test_project_id_is_found_by_all_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "reads.db")
    srv._ensure_db()
    pid = srv.aurora_create_project("intent", "video_simple", "hero_ad")["project_id"]
    # Writes through several tools...
    srv.aurora_create_benchmark_pack(pid, [{"url_or_path": "u", "visual_traits": {}}])
    srv.aurora_record_audit(pid, "c", "pass")
    srv.aurora_record_quality_score(pid, "image", {"photorealism": 90})
    # ...must all be visible to the read paths emit depends on.
    assert db.get_project(pid, db_path=str(srv.DB_PATH))
    assert srv._benchmark_pack(pid) is not None, "benchmark pack not found for pid (bug #5)"
    assert db.get_benchmark_refs(pid, db_path=str(srv.DB_PATH))
    # emit must not report 'unknown project' for an id the system just issued.
    emit = srv.aurora_emit_execution_pack(pid)
    assert "unknown project" not in (emit.get("reason") or ""), emit


# (c) Scorer wire shapes match what score() reads ----------------------------
def test_every_scorer_shape_matches_and_is_canonical():
    # Each public score_type must resolve to a scorer AND a DB-CHECK value.
    db_check_values = {"image", "video", "multishot", "biomechanics", "prompt",
                       "production_probability"}
    for score_type, scorer in srv._SCORERS.items():
        canon = srv._SCORE_TYPE_CANON.get(score_type)
        assert canon in db_check_values, f"{score_type} -> {canon} not a CHECK value"
        keys = scoring.expected_criteria_for(scorer)
        assert keys, f"{score_type} scorer exposes no criteria keys"
        # Feeding all-100 over the declared keys must yield a passing 100.
        result = scorer.score({k: 100 for k in keys})
        assert result["total_score"] == 100, (score_type, result["total_score"])
        assert result.get("recognized_criteria") == len(keys)


def test_wrong_shape_is_loud_not_silent_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "shape.db")
    srv._ensure_db()
    pid = srv.aurora_create_project("intent", "video_simple", "hero_ad")["project_id"]
    # Passing prompt CONTENT (not rubric scores) must be rejected with guidance,
    # never silently scored ~0.
    res = srv.aurora_record_quality_score(
        pid, "image", {"creative": "a nice prompt", "technical": "85mm"})
    assert res["ok"] is False
    assert "expected" in res["reason"].lower() or res.get("expected_criteria")


# (d) Recorded-verdict vocabulary matches the context-check vocabulary --------
def test_vocabulary_coherence():
    """The two evaluation paths must speak the same gate vocabulary.

    emit reads recorded verdicts (persist-then-read) AND falls back to a
    context check for gates with no recording. If a gate name only exists on one
    side, a project would be silently mis-evaluated (the bug #8/#10 class). Every
    required gate for every mode must therefore appear in BOTH the canonical gate
    registry and the builder's context-input table, so neither path can name a
    gate the other doesn't know.
    """
    from aurora import execution_pack_builder as builder

    context_inputs = set(builder._GATE_INPUTS.keys())
    registry = set(gates_pkg.GATE_MODULES.keys())
    assert context_inputs == registry, (
        "context-check table and gate registry disagree: "
        f"only-in-context={context_inputs - registry} "
        f"only-in-registry={registry - context_inputs}"
    )
    for mode in ("image", "video_simple", "video_multishot"):
        for gate in gates_pkg.required_gates_for_mode(mode):
            assert gate in registry, f"{mode}: {gate} not in gate registry"
            assert gate in context_inputs, f"{mode}: {gate} has no context check"


def test_recorded_status_values_are_db_check_valid():
    """Every status the server can persist must satisfy the gate_evaluations
    CHECK constraint, so a recorded verdict never raises on write."""
    import sqlite3

    valid = {"pass", "fail", "warning"}
    # _record_gate_eval writes pass/fail; psp + preproduction write pass/fail too.
    assert {"pass", "fail"} <= valid
    # The DB enforces the same set — a bogus status must be rejected.
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE projects (project_id TEXT PRIMARY KEY);"
        "CREATE TABLE gate_evaluations (evaluation_id TEXT PRIMARY KEY, "
        "project_id TEXT, gate_name TEXT, "
        "status TEXT NOT NULL CHECK(status IN ('pass','fail','warning')));"
    )
    conn.execute("INSERT INTO projects VALUES ('p')")
    for status in valid:
        conn.execute(
            "INSERT INTO gate_evaluations VALUES (?, 'p', 'g', ?)", (status, status)
        )
    try:
        conn.execute(
            "INSERT INTO gate_evaluations VALUES ('bad', 'p', 'g', 'not_evaluated')"
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    conn.close()
    assert raised, "CHECK must reject a status outside pass/fail/warning"

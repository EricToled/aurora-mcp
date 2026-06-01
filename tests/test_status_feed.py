"""Operator Console project-status assembly (server._project_status).

Guards the feature that lets Eric SEE, from the console, the real blocks
(gate_evaluations — not just SECURITY_HALT events) and what Claude has provided
for a project. Without this, normal gate failures never surface in the console.
"""
from __future__ import annotations

from aurora import db
from aurora import server as srv


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "status.db")
    srv._ensure_db()


def test_status_unknown_project_is_none(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert srv._project_status("does-not-exist") is None


def test_status_surfaces_gate_blocks_and_provided(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    db_path = srv._db()
    pid = db.insert_project("anuncio hero", "video_multishot", db_path=db_path)

    # A failing gate (a real "bloqueo") + a passing one.
    db.put_gate_evaluation(pid, "gate_preproduction_packet", "fail",
                           reasons=["falta shot_list", "falta characters"], db_path=db_path)
    db.put_gate_evaluation(pid, "gate_route_verification", "pass", db_path=db_path)
    # Something Claude provided.
    db.put_artifact(pid, "preproduction_packet",
                    {"characters": [{"name": "A"}], "shot_list": [{}, {}]}, db_path=db_path)

    st = srv._project_status(pid)
    assert st is not None
    assert st["project"]["operator_intent"] == "anuncio hero"
    assert st["summary"] == {"passed": 1, "failed": 1, "warning": 0, "total": 2}
    # Failures sort first so the operator sees blocks at the top.
    assert st["gates"][0]["gate"] == "gate_preproduction_packet"
    assert st["gates"][0]["status"] == "fail"
    assert "falta shot_list" in st["gates"][0]["reasons"]
    # Provided panel reflects the submitted packet with a count summary.
    packet_row = next(p for p in st["provided"] if p["kind"] == "preproduction_packet")
    assert packet_row["present"] is True
    assert "1 personaje(s), 2 shot(s)" == packet_row["detail"]
    # An un-submitted artifact reads as absent.
    prompt_row = next(p for p in st["provided"] if p["kind"] == "prompt_packet")
    assert prompt_row["present"] is False


def test_emit_block_notifies_feed_without_halting(monkeypatch, tmp_path):
    """Eric's mandate: the console must be notified of EVERY emit refusal, not
    just SECURITY_HALT alarms — and those notifications must NOT themselves turn
    into a permanent halt that blocks future emits."""
    _setup(monkeypatch, tmp_path)
    db_path = srv._db()
    pid = db.insert_project("spot hero", "image", db_path=db_path,
                            output_type="image_genesis")

    # A bare content-mode project blocks on the shape gates.
    res = srv.aurora_emit_execution_pack(pid)
    assert res["ok"] is False

    feed = db.get_event_feed(limit=50, db_path=db_path)
    blocks = [e for e in feed if e["event_type"] == "emit_blocked"]
    assert blocks, "every emit block must leave a feed notification"
    assert blocks[0]["severity"] == "block"
    assert blocks[0]["resolved"] is False  # shown as an active block, not 'resuelto'

    # The 'block' event is informational: a second emit must still reach the gate
    # logic (its own block), NOT be hijacked into a SECURITY_HALT by the feed row.
    res2 = srv.aurora_emit_execution_pack(pid)
    assert res2.get("status") != "SECURITY_HALT"

    # And a 'block' event never appears in the status card's HALTS section.
    st = srv._project_status(pid)
    assert st["halts"] == []

"""Validate that AURORA's db layer works on libSQL (Turso client) exactly as on
stdlib sqlite3. Run inside a Linux container with libsql-experimental installed.

libSQL opens a filesystem path as a LOCAL database, so we point the Turso env
vars at a local file: this drives the REAL db.get_conn libSQL branch (row_factory
= sqlite3.Row, executescript schema, inserts, queries) with no Turso account.
"""
import os
import tempfile

# Activate the libSQL branch in db.get_conn, pointed at a local libSQL file.
tmp = tempfile.mkdtemp()
os.environ["AURORA_TURSO_DATABASE_URL"] = os.path.join(tmp, "val.db")
os.environ["AURORA_TURSO_AUTH_TOKEN"] = "local-no-token"

from aurora import db

# Sanity: the Turso branch must be active.
assert db._turso_config() is not None, "Turso config not detected"

# 1) Schema init (exercises executescript + migrate_db + PRAGMA table_info).
tables = db.init_db(None)
assert "projects" in tables, tables
print(f"[ok] init_db created {len(tables)} tables")

# 2) Insert + read back a project (exercises row_factory=sqlite3.Row by-name + idx).
pid = db.insert_project("validate libsql", "image", db_path=None,
                        output_type="image_genesis", current_phase="open")
proj = db.get_project(pid, db_path=None)
assert proj and proj["project_id"] == pid, proj
assert proj["operator_intent"] == "validate libsql", proj
print(f"[ok] project round-trip by-name access works: {proj['project_id']}")

# 3) Artifact JSON round-trip (put/get_artifact).
db.put_artifact(pid, "decision_sheet", {"decisions": [], "operator_approved": True}, db_path=None)
art = db.get_artifact(pid, "decision_sheet", db_path=None)
assert art == {"decisions": [], "operator_approved": True}, art
print("[ok] artifact JSON round-trip works")

# 4) list_projects (exercises ordered query + multiple rows).
db.insert_project("second", "video_simple", db_path=None)
rows = db.list_projects(limit=10, db_path=None)
assert len(rows) >= 2, rows
assert all("project_id" in r for r in rows), rows
print(f"[ok] list_projects returned {len(rows)} rows")

# 5) audit insert + read (exercises CHECK constraint + fetch).
aid = db.insert_audit(project_id=pid, criterion="VALIDATE", verdict="pass",
                      notes="libsql validation", audited_by="operator", db_path=None)
audits = db.get_audits(pid, db_path=None)
assert any(a["criterion"] == "VALIDATE" for a in audits), audits
print(f"[ok] audit round-trip works ({aid})")

# 6) Re-open a fresh connection and confirm persistence to the same file.
proj2 = db.get_project(pid, db_path=None)
assert proj2 and proj2["project_id"] == pid
print("[ok] persistence across connections works")

print("\nALL LIBSQL COMPATIBILITY CHECKS PASSED")

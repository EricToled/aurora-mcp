"""Apply the AURORA SQLite schema to aurora.db.

Usage:
    python scripts/init_db.py [db_path]

If db_path is omitted, defaults to aurora.db in the repo root.
"""
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "aurora_schema.sql"
DEFAULT_DB_PATH = REPO_ROOT / "aurora.db"


def init_db(db_path: Path, schema_path: Path = SCHEMA_PATH) -> list[str]:
    """Create all tables from the schema file. Returns the list of table names."""
    schema_sql = Path(schema_path).read_text(encoding="utf-8")
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(schema_sql)
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    tables = init_db(db_path)
    print(f"Initialized DB at: {db_path}")
    print(f"Tables ({len(tables)}): {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

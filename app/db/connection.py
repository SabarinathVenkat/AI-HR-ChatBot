"""SQLite connection and schema setup."""
import re
import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# Columns added after a table first shipped. CREATE TABLE IF NOT EXISTS leaves an older database as it was, so each is
# added here when missing.
ADDED_COLUMNS = [("job_descriptions", "file_key", "TEXT"), ("job_descriptions", "briefing_json", "TEXT"), ("resume_drafts", "mode", "TEXT NOT NULL DEFAULT 'polish'")]


def _make_lead_optional(conn: sqlite3.Connection) -> None:
    """A request's Competency Lead used to be required. SQLite cannot relax a column, so the table is rebuilt (the
    way SQLite's own documentation says to) and every request is copied across."""
    columns = list(conn.execute("PRAGMA table_info(resume_requests)"))
    if not any(c["name"] == "lead_id" and c["notnull"] for c in columns):
        return
    old_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'resume_requests'").fetchone()["sql"]
    new_sql = re.sub(r"(lead_id\s+INTEGER)\s+NOT NULL", r"\1", old_sql, count=1)
    new_sql = re.sub(r"CREATE TABLE\s+(IF NOT EXISTS\s+)?resume_requests", "CREATE TABLE resume_requests_new", new_sql, count=1)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute(new_sql)
        conn.execute("INSERT INTO resume_requests_new SELECT * FROM resume_requests")
        conn.execute("DROP TABLE resume_requests")
        conn.execute("ALTER TABLE resume_requests_new RENAME TO resume_requests")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))  # the indexes went with the old table: make them again


def _allow_any_app(conn: sqlite3.Connection) -> None:
    """platform_modules first allowed only 'hr' and 'rmg'. The portal now takes any app in its catalog, so a database made
    with that rule gets the table rebuilt without it."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'platform_modules'").fetchone()
    if row is None or "CHECK (module IN" not in row["sql"]:
        return
    conn.commit()
    conn.execute("ALTER TABLE platform_modules RENAME TO platform_modules_old")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute("INSERT INTO platform_modules SELECT * FROM platform_modules_old")
    conn.execute("DROP TABLE platform_modules_old")
    conn.commit()


def upgrade_schema(conn: sqlite3.Connection) -> None:
    """Add any column an older database lacks, and relax what has since become optional. Safe to run again."""
    for table, column, definition in ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()
    _make_lead_optional(conn)
    _allow_any_app(conn)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    upgrade_schema(conn)
    conn.commit()

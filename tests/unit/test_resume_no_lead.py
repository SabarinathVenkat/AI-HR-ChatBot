"""An associate with no Competency Lead can still be tagged: their resume is then reviewed by RMG.

The database column that held the lead was required; an older database is upgraded without losing any request.
"""
import sqlite3

from app.db.connection import SCHEMA_PATH, connect, init_schema, upgrade_schema
from tests.unit.test_resume_service import DIVYA, HEAD, LEAD, RAVI, STAFF, ready, world  # noqa: F401  (fixtures)


def old_database() -> sqlite3.Connection:
    """A database made before the lead became optional: lead_id is NOT NULL, and one request, draft and notification exist."""
    conn = connect(":memory:")
    required = SCHEMA_PATH.read_text(encoding="utf-8").replace(
        "lead_id       INTEGER REFERENCES employees(id),", "lead_id       INTEGER NOT NULL REFERENCES employees(id),")
    assert required != SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(required)
    conn.execute("INSERT INTO employees (id, email, password_hash, name, role, manager_id, department, join_date, employment_status)"
                 " VALUES (1, 'a@x.invalid', 'x', 'Ana', 'employee', NULL, 'Eng', '2020-01-01', 'confirmed'),"
                 " (2, 'l@x.invalid', 'x', 'Lee', 'employee', NULL, 'Eng', '2020-01-01', 'confirmed')")
    conn.execute("INSERT INTO job_descriptions (id, title, filename, jd_json, created_by, created_at) VALUES (1, 'JD', 'jd.txt', '{}', 1, 'now')")
    conn.execute("INSERT INTO resume_requests (id, jd_id, associate_id, lead_id, status, created_by, created_at, updated_at)"
                 " VALUES (7, 1, 1, 2, 'in_progress', 1, 'now', 'now')")
    conn.execute("INSERT INTO resume_drafts (request_id, base_json, working_json, updated_at) VALUES (7, '{}', '{}', 'now')")
    conn.execute("INSERT INTO notifications (employee_id, message, request_id, created_at) VALUES (1, 'hello', 7, 'now')")
    conn.commit()
    return conn


def lead_is_required(conn) -> bool:
    return any(row["name"] == "lead_id" and row["notnull"] for row in conn.execute("PRAGMA table_info(resume_requests)"))


def test_an_older_database_has_the_lead_made_optional_without_losing_a_request():
    conn = old_database()
    assert lead_is_required(conn)

    upgrade_schema(conn)

    assert not lead_is_required(conn)
    request = conn.execute("SELECT * FROM resume_requests").fetchone()
    assert (request["id"], request["lead_id"], request["status"]) == (7, 2, "in_progress")
    assert conn.execute("SELECT COUNT(*) FROM resume_drafts WHERE request_id = 7").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM notifications WHERE request_id = 7").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_the_upgrade_can_be_run_again_and_keeps_its_indexes_and_uniqueness():
    conn = old_database()

    upgrade_schema(conn)
    upgrade_schema(conn)

    names = {row["name"] for row in conn.execute("PRAGMA index_list(resume_requests)")}
    assert "idx_resume_requests_lead" in names and "idx_resume_requests_associate" in names
    conn.execute("INSERT INTO resume_requests (jd_id, associate_id, lead_id, status, created_by, created_at, updated_at)"
                 " VALUES (1, 2, NULL, 'requested', 1, 'now', 'now')")  # no lead is now allowed
    try:
        conn.execute("INSERT INTO resume_requests (jd_id, associate_id, lead_id, status, created_by, created_at, updated_at)"
                     " VALUES (1, 2, NULL, 'requested', 1, 'now', 'now')")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("one request per job description and associate must still be enforced")


def test_a_new_database_already_has_the_lead_optional():
    conn = connect(":memory:")
    init_schema(conn)

    assert not lead_is_required(conn)


# --- tagging ------------------------------------------------------------------------------------------------------------------

def test_an_associate_with_no_lead_is_tagged_and_the_review_goes_to_rmg(world):  # noqa: F811
    jd = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]
    world.db.execute("DELETE FROM lead_assignments WHERE associate_id = ?", (world.id_of(RAVI),))
    world.db.commit()

    result = world.as_(STAFF).tag(jd, [world.id_of(RAVI)])

    assert len(result["created"]) == 1 and result["skipped"] == []
    row = world.db.execute("SELECT lead_id FROM resume_requests WHERE associate_id = ?", (world.id_of(RAVI),)).fetchone()
    assert row["lead_id"] is None


def test_the_people_list_says_who_has_no_lead_but_still_lets_them_be_tagged(world):  # noqa: F811
    world.db.execute("DELETE FROM lead_assignments WHERE associate_id = ?", (world.id_of(RAVI),))
    world.db.commit()

    people = {p["name"]: p for p in world.as_(STAFF).associates()}

    assert people[RAVI]["lead"] is None and people[RAVI]["review_by"] == "RMG"
    assert people[DIVYA]["lead"] and people[DIVYA]["review_by"] == "Competency Lead"

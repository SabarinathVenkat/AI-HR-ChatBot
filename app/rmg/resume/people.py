"""RMG roles and the Competency Lead mapping.

An employee keeps their HR role (employee, manager, hr_admin) and can hold RMG roles on top of it:
  rmg_staff        tags associates against a job description and downloads resumes
  rmg_head         everything rmg_staff can do, plus the template and the Lead mapping
  competency_lead  reviews and approves the resumes of the associates mapped to them
"""
import sqlite3

RMG_ROLES = frozenset({"rmg_staff", "rmg_head", "competency_lead"})

MESSAGES = {
    "unknown_role": "That role does not exist.",
    "not_a_lead": "That person is not a Competency Lead.",
    "self_lead": "A person cannot be their own Competency Lead.",
    "no_such_employee": "That employee does not exist.",
}


class PeopleError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(MESSAGES[code])


def roles_of(conn: sqlite3.Connection, employee_id: int) -> frozenset[str]:
    rows = conn.execute("SELECT role FROM rmg_roles WHERE employee_id = ?", (employee_id,)).fetchall()
    return frozenset(r["role"] for r in rows)


def assign_role(conn: sqlite3.Connection, employee_id: int, role: str) -> None:
    if role not in RMG_ROLES:
        raise PeopleError("unknown_role")
    conn.execute("INSERT OR IGNORE INTO rmg_roles (employee_id, role) VALUES (?, ?)", (employee_id, role))
    conn.commit()


def _exists(conn: sqlite3.Connection, employee_id: int) -> bool:
    return conn.execute("SELECT 1 FROM employees WHERE id = ?", (employee_id,)).fetchone() is not None


def set_lead(conn: sqlite3.Connection, associate_id: int, lead_id: int) -> None:
    if not (_exists(conn, associate_id) and _exists(conn, lead_id)):
        raise PeopleError("no_such_employee")
    if associate_id == lead_id:
        raise PeopleError("self_lead")
    if "competency_lead" not in roles_of(conn, lead_id):
        raise PeopleError("not_a_lead")
    conn.execute(
        "INSERT INTO lead_assignments (associate_id, lead_id) VALUES (?, ?)"
        " ON CONFLICT(associate_id) DO UPDATE SET lead_id = excluded.lead_id", (associate_id, lead_id))
    conn.commit()


def lead_of(conn: sqlite3.Connection, associate_id: int) -> int | None:
    row = conn.execute("SELECT lead_id FROM lead_assignments WHERE associate_id = ?", (associate_id,)).fetchone()
    return row["lead_id"] if row else None


def list_assignments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT a.associate_id, ea.name AS associate, a.lead_id, el.name AS lead"
        " FROM lead_assignments a JOIN employees ea ON ea.id = a.associate_id"
        " JOIN employees el ON el.id = a.lead_id ORDER BY ea.name").fetchall()
    return [dict(r) for r in rows]

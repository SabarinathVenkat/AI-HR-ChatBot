"""Data access. Parameterized SQL only; scoping by employee or manager happens in the query."""
import sqlite3
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Employee:
    id: int
    email: str
    name: str
    role: str
    manager_id: int | None
    department: str
    join_date: date
    status: str


def _employee(row: sqlite3.Row) -> Employee:
    return Employee(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        role=row["role"],
        manager_id=row["manager_id"],
        department=row["department"],
        join_date=date.fromisoformat(row["join_date"]),
        status=row["employment_status"],
    )


@dataclass(frozen=True)
class LeaveBalance:
    leave_type: str
    accrued: float
    carried_forward: float
    used: float
    adjustment: float
    pending: float

    @property
    def available(self) -> float:
        return self.accrued + self.carried_forward + self.adjustment - self.used


def get_leave_balances(
    conn: sqlite3.Connection, employee_id: int, year: int
) -> list[LeaveBalance]:
    rows = conn.execute(
        """
        SELECT b.leave_type, b.accrued, b.carried_forward, b.used, b.adjustment,
               COALESCE((SELECT SUM(r.days_counted) FROM leave_requests r
                         WHERE r.employee_id = b.employee_id AND r.leave_type = b.leave_type
                           AND r.status = 'pending' AND substr(r.start_date, 1, 4) = ?), 0)
                 AS pending
        FROM leave_balances b
        WHERE b.employee_id = ? AND b.leave_year = ?
        ORDER BY b.leave_type
        """,
        (str(year), employee_id, year),
    ).fetchall()
    return [LeaveBalance(**dict(row)) for row in rows]


@dataclass(frozen=True)
class LeaveRequestRow:
    id: int
    employee_id: int
    leave_type: str
    start: date
    end: date
    days_counted: float
    status: str
    employee_name: str | None = None


def _request(row: sqlite3.Row) -> LeaveRequestRow:
    return LeaveRequestRow(
        id=row["id"],
        employee_id=row["employee_id"],
        leave_type=row["leave_type"],
        start=date.fromisoformat(row["start_date"]),
        end=date.fromisoformat(row["end_date"]),
        days_counted=row["days_counted"],
        status=row["status"],
        employee_name=row["employee_name"] if "employee_name" in row.keys() else None,
    )


def get_holidays(conn: sqlite3.Connection, year: int) -> dict[date, str]:
    rows = conn.execute(
        "SELECT date, name FROM holidays WHERE substr(date, 1, 4) = ? ORDER BY date",
        (str(year),),
    ).fetchall()
    return {date.fromisoformat(r["date"]): r["name"] for r in rows}


def list_own_requests(
    conn: sqlite3.Connection, employee_id: int, status: str | None = None
) -> list[LeaveRequestRow]:
    rows = conn.execute(
        "SELECT * FROM leave_requests WHERE employee_id = ? AND (? IS NULL OR status = ?)"
        " ORDER BY start_date",
        (employee_id, status, status),
    ).fetchall()
    return [_request(r) for r in rows]


def list_team_requests(
    conn: sqlite3.Connection, manager_id: int, status: str | None = None
) -> list[LeaveRequestRow]:
    """Requests of the manager's direct reports. Scoping is part of the query itself."""
    rows = conn.execute(
        """
        SELECT r.*, e.name AS employee_name FROM leave_requests r
        JOIN employees e ON e.id = r.employee_id
        WHERE e.manager_id = ? AND (? IS NULL OR r.status = ?)
        ORDER BY r.start_date
        """,
        (manager_id, status, status),
    ).fetchall()
    return [_request(r) for r in rows]


def get_team_member(
    conn: sqlite3.Connection, manager_id: int, employee_id: int
) -> Employee | None:
    row = conn.execute(
        "SELECT * FROM employees WHERE id = ? AND manager_id = ?", (employee_id, manager_id)
    ).fetchone()
    return _employee(row) if row else None


def list_active_leave(conn: sqlite3.Connection, employee_id: int) -> list[LeaveRequestRow]:
    """Pending and approved requests, used for overlap and combination checks."""
    rows = conn.execute(
        "SELECT * FROM leave_requests WHERE employee_id = ? AND status IN ('pending', 'approved')"
        " ORDER BY start_date",
        (employee_id,),
    ).fetchall()
    return [_request(r) for r in rows]


def decide_request(
    conn: sqlite3.Connection,
    manager_id: int,
    request_id: int,
    decision: str,
    note: str | None,
    decided_at: str,
) -> str:
    """Approve or reject a direct report's pending request in one transaction.

    Returns "ok", "not_found" (also when the request belongs to another team, so existence is
    not revealed) or "not_pending".
    """
    row = conn.execute(
        """
        SELECT r.* FROM leave_requests r JOIN employees e ON e.id = r.employee_id
        WHERE r.id = ? AND e.manager_id = ?
        """,
        (request_id, manager_id),
    ).fetchone()
    if row is None:
        return "not_found"
    new_status = "approved" if decision == "approve" else "rejected"
    try:
        updated = conn.execute(
            "UPDATE leave_requests SET status = ?, decided_by = ?, decided_at = ?,"
            " decision_note = ? WHERE id = ? AND status = 'pending'",
            (new_status, manager_id, decided_at, note, request_id),
        ).rowcount
        if updated == 0:
            conn.rollback()
            return "not_pending"
        if new_status == "approved":
            conn.execute(
                "UPDATE leave_balances SET used = used + ? WHERE employee_id = ?"
                " AND leave_type = ? AND leave_year = ?",
                (row["days_counted"], row["employee_id"], row["leave_type"],
                 int(row["start_date"][:4])),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return "ok"


def get_employee(conn: sqlite3.Connection, employee_id: int) -> Employee | None:
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    return _employee(row) if row else None


def get_policy_section(conn: sqlite3.Connection, section_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM policy_chunks WHERE section_id = ?", (section_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "section_id": row["section_id"],
        "policy_id": row["policy_id"],
        "policy_title": row["policy_title"],
        "title": row["title"],
        "text": row["text"],
        "version": row["version"],
        "effective_date": row["effective_date"],
    }


def list_demo_accounts(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT name, email, role, department FROM employees ORDER BY id"
    ).fetchall()
    return [dict(row) for row in rows]


def get_open_draft(conn: sqlite3.Connection, employee_id: int) -> dict | None:
    """The employee's leave draft that is waiting for confirmation, if any."""
    row = conn.execute(
        "SELECT * FROM leave_drafts WHERE employee_id = ? AND status = 'awaiting_confirmation'"
        " ORDER BY created_at DESC LIMIT 1",
        (employee_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "draft_id": row["id"],
        "leave_type": row["leave_type"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "days": row["days_counted"],
        "lop_days": row["lop_days"],
        "expires_at": row["expires_at"],
    }


def list_other_employee_names(conn: sqlite3.Connection, employee_id: int) -> frozenset[str]:
    """Names of everyone except this employee, for the answer verifier."""
    rows = conn.execute("SELECT name FROM employees WHERE id != ?", (employee_id,)).fetchall()
    return frozenset(row["name"] for row in rows)


def get_password_hash(conn: sqlite3.Connection, employee_id: int) -> str | None:
    row = conn.execute(
        "SELECT password_hash FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    return row["password_hash"] if row else None


def get_employee_by_email(conn: sqlite3.Connection, email: str) -> Employee | None:
    row = conn.execute(
        "SELECT * FROM employees WHERE lower(email) = lower(?)", (email,)
    ).fetchone()
    return _employee(row) if row else None

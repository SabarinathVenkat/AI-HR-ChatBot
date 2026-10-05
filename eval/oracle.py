"""Ground truth computed from the database and the domain code, independent of the agent.

Expected values for data and calculation questions come from here, so the answer key is derived
from the same facts the policy states, not typed by hand.
"""
import sqlite3
from datetime import date

from app.db import repositories as repo
from app.domain.calendar import count_working_days

YEAR = 2026


def balance(conn: sqlite3.Connection, employee_id: int, leave_type: str) -> float:
    rows = {b.leave_type: b for b in repo.get_leave_balances(conn, employee_id, YEAR)}
    return rows[leave_type].available


def working_days(
    conn: sqlite3.Connection, start: str, end: str, start_half: str = "full", end_half: str = "full"
) -> float:
    holidays = {}
    for year in range(date.fromisoformat(start).year, date.fromisoformat(end).year + 1):
        holidays.update(repo.get_holidays(conn, year))
    return count_working_days(
        date.fromisoformat(start), date.fromisoformat(end), holidays, start_half, end_half
    ).days


def employee_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM employees WHERE name = ?", (name,)).fetchone()
    return row["id"]


def other_names(conn: sqlite3.Connection, persona_id: int) -> frozenset[str]:
    return repo.list_other_employee_names(conn, persona_id)

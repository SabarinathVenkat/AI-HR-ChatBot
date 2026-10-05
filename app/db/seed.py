"""Demo data: a small fictional company. All people and addresses are made up."""
import sqlite3
from collections.abc import Callable
from datetime import date

from app.domain.accrual import accrued_annual_leave, prorated_upfront_leave

SEED_AS_OF = date(2026, 10, 2)
DEMO_PASSWORD = "Welcome@123"
EMAIL_DOMAIN = "example-ideas2it.invalid"

# id, name, role, manager_id, department, join_date, status, confirmation_date, gender
EMPLOYEES = [
    (1, "Meera Nair", "hr_admin", None, "People Operations", "2018-03-12", "confirmed", "2018-09-12", "F"),
    (2, "Arjun Rao", "manager", 1, "Engineering", "2019-07-01", "confirmed", "2020-01-01", "M"),
    (3, "Kavya Iyer", "manager", 1, "Data and AI", "2020-02-17", "confirmed", "2020-08-17", "F"),
    (4, "Ravi Kumar", "employee", 2, "Engineering", "2021-05-10", "confirmed", "2021-11-10", "M"),
    (5, "Divya Menon", "employee", 2, "Engineering", "2022-09-19", "confirmed", "2023-03-19", "F"),
    (6, "Sanjay Patel", "employee", 2, "Engineering", "2026-06-08", "probation", None, "M"),
    (7, "Priya Shankar", "employee", 3, "Data and AI", "2023-01-16", "confirmed", "2023-07-16", "F"),
    (8, "Karthik Raja", "employee", 3, "Data and AI", "2026-09-21", "probation", None, "M"),
    (9, "Ananya Das", "employee", 3, "Data and AI", "2020-11-02", "confirmed", "2021-05-02", "F"),
    (10, "Vikram Singh", "manager", 1, "Quality", "2021-08-02", "confirmed", "2022-02-02", "M"),
]

# code, name, annual entitlement, accrual type, carry-forward cap, requires confirmed
LEAVE_TYPES = [
    ("AL", "Annual Leave", 18, "monthly", 10, 0),
    ("CL", "Casual Leave", 6, "upfront", 0, 0),
    ("SL", "Sick Leave", 8, "upfront", 0, 0),
    ("ML", "Maternity Leave", None, "event", 0, 0),
    ("PL", "Paternity Leave", 10, "event", 0, 1),
    ("BL", "Bereavement Leave", 5, "event", 0, 0),
    ("MRL", "Marriage Leave", 5, "event", 0, 1),
    ("CO", "Compensatory Off", None, "event", 0, 0),
    ("LOP", "Loss of Pay", None, "event", 0, 0),
]


# Hand-picked usage for the demo, keyed by employee id.
USED = {
    4: {"AL": 4.5, "CL": 2, "SL": 1},
    5: {"AL": 6.0, "CL": 1},
    7: {"AL": 3.0, "CL": 1, "SL": 2},  # includes the approved 8 Oct casual leave
    9: {"AL": 2.0},
}
CARRIED_FORWARD_AL = {4: 3.0, 7: 5.0, 9: 10.0}

# employee_id, leave_type, start, end, days, status, created_at
REQUESTS = [
    (5, "AL", "2026-10-12", "2026-10-14", 3, "pending", "2026-09-28T10:15:00"),
    (4, "AL", "2026-12-21", "2026-12-23", 3, "approved", "2026-09-15T09:30:00"),
    (7, "CL", "2026-10-08", "2026-10-08", 1, "approved", "2026-09-30T16:40:00"),
    (6, "CL", "2026-10-15", "2026-10-15", 1, "pending", "2026-10-01T11:05:00"),
]

# date, name
HOLIDAYS_2026 = [
    ("2026-01-01", "New Year's Day"),
    ("2026-01-14", "Pongal"),
    ("2026-01-26", "Republic Day"),
    ("2026-04-03", "Good Friday"),
    ("2026-04-14", "Tamil New Year"),
    ("2026-05-01", "Labour Day"),
    ("2026-09-14", "Vinayagar Chathurthi"),
    ("2026-10-02", "Gandhi Jayanti"),
    ("2026-10-19", "Ayudha Puja"),
    ("2026-10-20", "Vijayadashami"),
    ("2026-11-09", "Deepavali (observed)"),
    ("2026-12-25", "Christmas Day"),
]


def email_for(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}@{EMAIL_DOMAIN}"


def seed(
    conn: sqlite3.Connection, as_of: date, hash_password: Callable[[str], str]
) -> None:
    password_hash = hash_password(DEMO_PASSWORD)
    conn.executemany(
        "INSERT INTO leave_types VALUES (?, ?, ?, ?, ?, ?)", LEAVE_TYPES
    )
    conn.executemany(
        "INSERT INTO employees (id, email, password_hash, name, role, manager_id, department,"
        " join_date, employment_status, confirmation_date, gender) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (i, email_for(name), password_hash, name, role, mgr, dept, joined, status, conf, g)
            for i, name, role, mgr, dept, joined, status, conf, g in EMPLOYEES
        ],
    )
    _seed_balances(conn, as_of)
    conn.executemany(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days_counted,"
        " status, created_at) VALUES (?,?,?,?,?,?,?)",
        REQUESTS,
    )
    conn.executemany(
        "INSERT INTO holidays (date, name, kind) VALUES (?, ?, 'public')", HOLIDAYS_2026
    )
    conn.commit()


def _seed_balances(conn: sqlite3.Connection, as_of: date) -> None:
    rows = []
    for emp_id, *_rest in EMPLOYEES:
        joined = date.fromisoformat(next(e[5] for e in EMPLOYEES if e[0] == emp_id))
        used = USED.get(emp_id, {})
        accrued = {
            "AL": accrued_annual_leave(joined, as_of),
            "CL": prorated_upfront_leave(6, joined, as_of.year),
            "SL": prorated_upfront_leave(8, joined, as_of.year),
        }
        for leave_type, amount in accrued.items():
            carried = CARRIED_FORWARD_AL.get(emp_id, 0.0) if leave_type == "AL" else 0.0
            rows.append(
                (emp_id, as_of.year, leave_type, amount, used.get(leave_type, 0.0), carried, 0.0)
            )
    conn.executemany(
        "INSERT INTO leave_balances (employee_id, leave_year, leave_type, accrued, used,"
        " carried_forward, adjustment) VALUES (?,?,?,?,?,?,?)",
        rows,
    )

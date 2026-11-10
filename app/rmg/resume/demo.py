"""Demo data for the resume builder: one account per RMG role, a few Lead assignments and a demo job description.

Safe to run repeatedly: people are matched by email and everything else is inserted only when missing, so an
existing demo database gains these without being rebuilt. All people are made up.
"""
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone

from app.db.seed import DEMO_PASSWORD, email_for
from app.rmg.resume.jd import JobDescription, Role
from app.rmg.resume.people import assign_role, set_lead

# name, department, RMG role
DEMO_PEOPLE = [
    ("Sam Joseph", "Resource Management", "rmg_staff"),
    ("Rhea Kapoor", "Resource Management", "rmg_head"),
    ("Lakshmi Narayan", "Engineering", "competency_lead"),
]
LEAD_NAME = "Lakshmi Narayan"
# Associates mapped to the lead. Sanjay Patel (6) and Karthik Raja (8) are left unmapped on purpose, to show what
# happens when RMG tags someone who has no Competency Lead.
MAPPED_ASSOCIATES = (4, 5, 7, 9)

DEMO_JD_TITLE = "Senior Java Developer (demo)"
DEMO_JD = JobDescription(
    roles=[Role(title="Senior Java Developer", min_years=5, domain="Fintech",
                must_have=["Java", "Spring Boot", "REST", "Kafka", "SQL"], nice_to_have=["AWS", "Docker", "Kubernetes"])],
    flagged=[],
)


def _employee_id(conn: sqlite3.Connection, name: str, department: str, hash_password: Callable[[str], str]) -> int:
    row = conn.execute("SELECT id FROM employees WHERE lower(email) = lower(?)", (email_for(name),)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO employees (email, password_hash, name, role, manager_id, department, join_date,"
        " employment_status, confirmation_date, gender) VALUES (?, ?, ?, 'employee', 1, ?, '2019-01-07',"
        " 'confirmed', '2019-07-07', NULL)", (email_for(name), hash_password(DEMO_PASSWORD), name, department))
    conn.commit()
    return cursor.lastrowid


def seed_resume_demo(conn: sqlite3.Connection, hash_password: Callable[[str], str]) -> None:
    ids = {}
    for name, department, role in DEMO_PEOPLE:
        ids[name] = _employee_id(conn, name, department, hash_password)
        assign_role(conn, ids[name], role)
    for associate in MAPPED_ASSOCIATES:
        if conn.execute("SELECT 1 FROM employees WHERE id = ?", (associate,)).fetchone():
            set_lead(conn, associate, ids[LEAD_NAME])
    if not conn.execute("SELECT 1 FROM job_descriptions WHERE title = ?", (DEMO_JD_TITLE,)).fetchone():
        conn.execute(
            "INSERT INTO job_descriptions (title, filename, jd_json, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (DEMO_JD_TITLE, "demo-jd.txt", DEMO_JD.model_dump_json(), ids["Sam Joseph"],
             datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()

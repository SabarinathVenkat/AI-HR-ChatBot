"""The platform administrator and the modules the platform offers.

There are two modules: HR (leave and policy answers) and RMG (the resume builder and the resource-management assistant).
The admin turns each on or off; at least one must stay on. Everyone who signs in afterwards sees only the modules that are
on, and the server refuses a request to a module that is off, so hiding a button is never the only protection.
"""
import os
import sqlite3
from collections.abc import Callable

MODULES = ("hr", "rmg")
ADMIN_EMAIL = "admin@example-ideas2it.invalid"
ADMIN_NAME = "Platform Admin"
DEFAULT_ADMIN_PASSWORD = "admin123"  # for the demo; set ADMIN_PASSWORD to use another one
PASSWORD_ENV = "ADMIN_PASSWORD"


class ModuleError(Exception):
    pass


def enabled_modules(conn: sqlite3.Connection) -> dict[str, bool]:
    saved = {r["module"]: bool(r["enabled"]) for r in conn.execute("SELECT module, enabled FROM platform_modules")}
    return {m: saved.get(m, True) for m in MODULES}


def set_modules(conn: sqlite3.Connection, wanted: dict[str, bool], by: int, when: str) -> dict[str, bool]:
    if not any(wanted.get(m) for m in MODULES):
        raise ModuleError("Turn on at least one module.")
    for module in MODULES:
        conn.execute(
            "INSERT INTO platform_modules (module, enabled, changed_by, changed_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(module) DO UPDATE SET enabled = excluded.enabled, changed_by = excluded.changed_by,"
            " changed_at = excluded.changed_at", (module, int(bool(wanted.get(module))), by, when))
    conn.commit()
    return enabled_modules(conn)


def seed_default_modules(conn: sqlite3.Connection) -> None:
    """A new platform starts with RMG on and HR off. A module the admin has already chosen is never changed."""
    for module in MODULES:
        conn.execute("INSERT OR IGNORE INTO platform_modules (module, enabled) VALUES (?, ?)", (module, int(module == "rmg")))
    conn.commit()


def is_admin(conn: sqlite3.Connection, employee_id: int) -> bool:
    return conn.execute("SELECT 1 FROM platform_admins WHERE employee_id = ?", (employee_id,)).fetchone() is not None


def sign_in_name(typed: str) -> str:
    """The admin may type just 'admin'; everyone else signs in with their email."""
    return ADMIN_EMAIL if typed.strip().lower() == "admin" else typed


def ensure_admin(conn: sqlite3.Connection, hash_password: Callable[[str], str], password: str | None = None) -> None:
    """Create the admin account if it is missing. An existing one is left alone, so a changed password is never undone."""
    row = conn.execute("SELECT id FROM employees WHERE lower(email) = lower(?)", (ADMIN_EMAIL,)).fetchone()
    if row is None:
        cursor = conn.execute(
            "INSERT INTO employees (email, password_hash, name, role, manager_id, department, join_date,"
            " employment_status, confirmation_date, gender) VALUES (?, ?, ?, 'employee', NULL, 'Administration',"
            " '2018-01-01', 'confirmed', '2018-07-01', NULL)",
            (ADMIN_EMAIL, hash_password(password or os.environ.get(PASSWORD_ENV) or DEFAULT_ADMIN_PASSWORD), ADMIN_NAME))
        employee_id = cursor.lastrowid
    else:
        employee_id = row["id"]
    conn.execute("INSERT OR IGNORE INTO platform_admins (employee_id) VALUES (?)", (employee_id,))
    conn.commit()

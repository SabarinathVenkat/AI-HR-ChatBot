"""Bootstrapping a database: schema, demo data and the policy index. Safe to run repeatedly."""
from pathlib import Path

from app.bootstrap import bootstrap
from app.config import Settings
from app.db.connection import connect
from tests.support import BagOfWordsEmbedder

SETTINGS = Settings(jwt_secret="x" * 40)


def counts(path: Path) -> tuple[int, int, int]:
    conn = connect(str(path))
    try:
        return (
            conn.execute("SELECT count(*) FROM employees").fetchone()[0],
            conn.execute("SELECT count(*) FROM policy_chunks").fetchone()[0],
            conn.execute("SELECT count(*) FROM leave_balances").fetchone()[0],
        )
    finally:
        conn.close()


def test_bootstrap_creates_demo_data_and_the_policy_index(tmp_path):
    db = tmp_path / "hr.db"

    bootstrap(db, BagOfWordsEmbedder())

    employees, chunks, balances = counts(db)
    assert employees == 15 and chunks > 30 and balances == 30  # 10 HR demo people, 4 resume demo accounts and the admin


def test_an_older_demo_database_gains_the_rmg_accounts_without_losing_anything(tmp_path):
    from app.db.connection import init_schema
    from app.db.seed import SEED_AS_OF, seed

    db = tmp_path / "hr.db"
    conn = connect(str(db))
    init_schema(conn)
    seed(conn, as_of=SEED_AS_OF, hash_password=lambda p: "x")  # a database from before the resume builder existed
    conn.close()

    bootstrap(db, BagOfWordsEmbedder())

    assert counts(db)[0] == 15


def test_a_new_platform_starts_with_rmg_on_and_hr_off_and_keeps_the_admins_choice(tmp_path):
    from app.platform_admin import enabled_modules, set_modules

    db = tmp_path / "hr.db"
    bootstrap(db, BagOfWordsEmbedder())
    conn = connect(str(db))
    try:
        assert enabled_modules(conn) == {"hr": False, "rmg": True}
        set_modules(conn, {"hr": True, "rmg": True}, by=1, when="2026-10-02T09:00:00")
    finally:
        conn.close()

    bootstrap(db, BagOfWordsEmbedder())  # a restart must not undo what the admin chose

    conn = connect(str(db))
    try:
        assert enabled_modules(conn) == {"hr": True, "rmg": True}
    finally:
        conn.close()


def test_bootstrap_is_idempotent(tmp_path):
    db = tmp_path / "hr.db"

    bootstrap(db, BagOfWordsEmbedder())
    first = counts(db)
    bootstrap(db, BagOfWordsEmbedder())

    assert counts(db) == first


def test_bootstrap_stores_real_argon2_hashes_for_the_demo_password(tmp_path):
    db = tmp_path / "hr.db"
    bootstrap(db, BagOfWordsEmbedder())
    conn = connect(str(db))
    try:
        stored = conn.execute("SELECT password_hash FROM employees WHERE id = 4").fetchone()[0]
    finally:
        conn.close()

    from app.api.security import verify_password
    from app.db.seed import DEMO_PASSWORD

    assert verify_password(DEMO_PASSWORD, stored)


def test_bootstrap_can_skip_demo_data(tmp_path):
    db = tmp_path / "hr.db"

    bootstrap(db, BagOfWordsEmbedder(), demo_data=False)

    employees, chunks, _ = counts(db)
    assert employees == 0 and chunks > 30

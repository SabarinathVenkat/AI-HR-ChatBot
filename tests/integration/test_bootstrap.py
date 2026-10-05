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
    assert employees == 10 and chunks > 30 and balances == 30


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

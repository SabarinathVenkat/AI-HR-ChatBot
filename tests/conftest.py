from datetime import date

import pytest

from app.db.connection import connect, init_schema
from app.db.seed import seed

SEED_DATE = date(2026, 10, 2)


@pytest.fixture
def db():
    conn = connect(":memory:")
    init_schema(conn)
    seed(conn, as_of=SEED_DATE, hash_password=lambda plain: f"hashed:{plain}")
    yield conn
    conn.close()

from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.security import hash_password
from app.config import Settings
from app.db.connection import connect, init_schema
from app.db.seed import DEMO_PASSWORD, SEED_AS_OF, email_for, seed

SECRET = "test-secret-" + "x" * 40


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs) -> None:
        self.current += timedelta(**kwargs)


@pytest.fixture(scope="session")
def argon_hash():
    return hash_password(DEMO_PASSWORD)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def api_db(argon_hash):
    conn = connect(":memory:")
    init_schema(conn)
    seed(conn, as_of=SEED_AS_OF, hash_password=lambda _plain: argon_hash)
    yield conn
    conn.close()


@pytest.fixture
def client(api_db, clock):
    app = create_app(
        Settings(jwt_secret=SECRET), connection=lambda: nullcontext(api_db), clock=clock
    )
    return TestClient(app)


def login(client, name: str, password: str = DEMO_PASSWORD):
    return client.post("/auth/login", json={"email": email_for(name), "password": password})


def auth_headers(client, name: str) -> dict:
    token = login(client, name).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

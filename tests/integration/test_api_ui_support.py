"""Backend support for the web UI: static files, security headers, demo accounts, policy sections."""
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.db.seed import DEMO_PASSWORD
from app.rag.chunker import load_policy_dir
from app.rag.index import index_policies
from tests.integration.conftest import SECRET, auth_headers
from tests.support import BagOfWordsEmbedder
from pathlib import Path

POLICIES = Path(__file__).resolve().parents[2] / "data" / "policies"


@pytest.fixture
def demo_client(api_db, clock):
    index_policies(api_db, load_policy_dir(POLICIES), BagOfWordsEmbedder())
    app = create_app(
        Settings(jwt_secret=SECRET, demo_mode=True), connection=lambda: nullcontext(api_db), clock=clock
    )
    return TestClient(app)


def test_the_web_app_is_served_at_the_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "HR Assistant" in response.text


def test_the_page_uses_no_inline_scripts_so_a_strict_csp_can_apply(client):
    html = client.get("/").text

    assert "<script src=" in html
    assert "<script>" not in html and "onclick=" not in html


@pytest.mark.parametrize("path", ["/", "/health", "/me"])
def test_security_headers_are_set_on_every_response(client, path):
    headers = client.get(path).headers

    csp = headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"


def test_the_javascript_and_css_files_are_served(client):
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_unknown_api_paths_are_404_not_the_web_app(client):
    assert client.get("/leave/nothing-here").status_code == 404


def test_demo_accounts_are_listed_only_in_demo_mode(client, demo_client):
    assert client.get("/demo/accounts").status_code == 404

    body = demo_client.get("/demo/accounts").json()
    assert len(body["accounts"]) == 10
    assert body["password"] == DEMO_PASSWORD
    assert {"name", "email", "role"} <= set(body["accounts"][0])
    assert "password_hash" not in str(body)


def test_a_policy_section_can_be_read_by_a_signed_in_user(demo_client):
    response = demo_client.get(
        "/policy/section", params={"id": "POL-05 §3"}, headers=auth_headers(demo_client, "Ravi Kumar")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["section_id"] == "POL-05 §3"
    assert "60 days" in body["text"] and body["title"] == "Notice Period"
    assert body["version"] == "1.0"


def test_a_clause_citation_resolves_to_its_section(demo_client):
    response = demo_client.get(
        "/policy/section", params={"id": "POL-05 §3.1"}, headers=auth_headers(demo_client, "Ravi Kumar")
    )

    assert response.json()["section_id"] == "POL-05 §3"


@pytest.mark.parametrize("bad", ["POL-99 §1", "nonsense", "POL-05", "'; DROP TABLE policy_chunks;--"])
def test_unknown_or_malformed_policy_ids_are_404(demo_client, bad):
    response = demo_client.get("/policy/section", params={"id": bad}, headers=auth_headers(demo_client, "Ravi Kumar"))

    assert response.status_code == 404


def test_reading_policy_sections_requires_sign_in(demo_client):
    assert demo_client.get("/policy/section", params={"id": "POL-05 §3"}).status_code == 401


def test_requests_say_whether_they_can_still_be_cancelled(client):
    ravi = client.get("/leave/requests", headers=auth_headers(client, "Ravi Kumar")).json()["requests"]
    divya = client.get("/leave/requests", headers=auth_headers(client, "Divya Menon")).json()["requests"]

    assert [(r["status"], r["can_cancel"]) for r in ravi] == [("approved", True)]  # starts 21 Dec
    assert [(r["status"], r["can_cancel"]) for r in divya] == [("pending", True)]


def test_a_started_or_finished_request_cannot_be_cancelled(client, api_db):
    api_db.execute("UPDATE leave_requests SET start_date = '2026-09-01', end_date = '2026-09-02' WHERE id = 2")
    api_db.commit()

    ravi = client.get("/leave/requests", headers=auth_headers(client, "Ravi Kumar")).json()["requests"]

    assert ravi[0]["can_cancel"] is False

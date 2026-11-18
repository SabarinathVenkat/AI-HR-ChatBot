"""The platform admin: signs in as 'admin', turns the HR and RMG modules on or off, and everyone else sees only what is on."""
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import AgentDeps, build_agent
from app.agent.router import RouteDecision
from app.api.main import create_app
from app.api.security import hash_password
from app.config import Settings
from app.db import repositories as repo
from app.platform_admin import ADMIN_EMAIL, ensure_admin
from app.rmg.agent import build_rmg_agent
from app.rmg.resume.chat import EditCommand
from app.rmg.resume.demo import seed_resume_demo
from app.rmg.resume.draft import TailoringSettings
from app.rmg.resume.filestore import FileStore
from app.rmg.resume.pipeline import PipelineDeps
from app.rmg.resume.service import ResumeEngine
from tests.integration.conftest import SECRET, auth_headers
from tests.support import FixedRouter, ScriptedChatModel
from tests.unit.resume_fakes import FakeJDExtractor, FakeResumeExtractor, keep_as_written

RAVI, NANCY = "Ravi Kumar", "Nancy"


@pytest.fixture
def client(api_db, clock, tmp_path, argon_hash):
    seed_resume_demo(api_db, hash_password=lambda p: argon_hash)
    ensure_admin(api_db, hash_password=lambda p: argon_hash)  # the test hash stands in for argon2 of "Welcome@123"
    api_db.execute("UPDATE employees SET password_hash = ? WHERE lower(email) = ?", (hash_password("admin123"), ADMIN_EMAIL))
    api_db.commit()
    engine = ResumeEngine(PipelineDeps(FakeResumeExtractor(), FakeJDExtractor(), keep_as_written, TailoringSettings()),
                          lambda message, resume: EditCommand(action="remove", path="projects.0.bullets.0", reply="Removed."))
    hr = build_agent(AgentDeps(ScriptedChatModel(responses=[AIMessage("HR answer.")] * 5),
                               FixedRouter(RouteDecision(intent="leave_request"))), MemorySaver())
    rmg = build_rmg_agent(ScriptedChatModel(responses=[AIMessage("RMG answer.")] * 5), MemorySaver())
    app = create_app(Settings(jwt_secret=SECRET, demo_mode=True), connection=lambda: nullcontext(api_db), clock=clock, agent=hr, rmg_agent=rmg,
                     resume_engine=engine, resume_files=FileStore(tmp_path / "files"))
    return TestClient(app)


def admin_headers(client):
    response = client.post("/auth/login", json={"email": "admin", "password": "admin123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def save(client, hr, rmg):
    return client.put("/admin/modules", json={"hr": hr, "rmg": rmg}, headers=admin_headers(client))


def chat(client, who, mode):
    return client.post("/chat", json={"message": "hello", "mode": mode}, headers=auth_headers(client, who))


# --- signing in -----------------------------------------------------------------------------------------------

def test_the_admin_signs_in_with_admin_and_admin123_or_with_the_full_email(client):
    assert client.post("/auth/login", json={"email": "admin", "password": "admin123"}).status_code == 200
    assert client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "admin123"}).status_code == 200
    assert client.post("/auth/login", json={"email": "admin", "password": "wrong"}).status_code == 401


def test_me_says_who_is_the_admin(client):
    assert client.get("/me", headers=admin_headers(client)).json()["is_admin"] is True
    assert client.get("/me", headers=auth_headers(client, RAVI)).json()["is_admin"] is False


def test_the_admin_account_is_not_listed_among_the_demo_accounts(client):
    emails = [a["email"] for a in client.get("/demo/accounts").json()["accounts"]]

    assert ADMIN_EMAIL not in emails and len(emails) == 14


def test_creating_the_admin_again_keeps_a_changed_password(api_db, argon_hash):
    ensure_admin(api_db, hash_password=lambda p: argon_hash)
    api_db.execute("UPDATE employees SET password_hash = 'changed' WHERE lower(email) = ?", (ADMIN_EMAIL,))
    ensure_admin(api_db, hash_password=lambda p: argon_hash)

    assert repo.get_employee_by_email(api_db, ADMIN_EMAIL) is not None
    assert api_db.execute("SELECT password_hash FROM employees WHERE lower(email) = ?", (ADMIN_EMAIL,)).fetchone()[0] == "changed"


# --- choosing the modules ----------------------------------------------------------------------------------------

def test_both_modules_are_on_until_the_admin_chooses(client):
    assert client.get("/admin/modules", headers=admin_headers(client)).json()["modules"] == {"hr": True, "rmg": True}
    assert client.get("/me", headers=auth_headers(client, RAVI)).json()["modules"] == {"hr": True, "rmg": True}


def test_only_the_admin_may_read_or_change_the_modules(client):
    ravi = auth_headers(client, RAVI)

    assert client.get("/admin/modules", headers=ravi).status_code == 403
    assert client.put("/admin/modules", json={"hr": False, "rmg": True}, headers=ravi).status_code == 403
    assert client.put("/admin/modules", json={"hr": False, "rmg": True}).status_code == 401


def test_at_least_one_module_must_stay_on(client):
    response = save(client, False, False)

    assert response.status_code == 422 and "at least one" in response.json()["error"]["message"].lower()
    assert client.get("/admin/modules", headers=admin_headers(client)).json()["modules"] == {"hr": True, "rmg": True}


def test_with_both_on_everyone_sees_both(client):
    assert save(client, True, True).status_code == 200

    headers = auth_headers(client, RAVI)
    assert client.get("/features", headers=headers).json() == {"rmg": True, "modules": {"hr": True, "rmg": True}}
    assert chat(client, RAVI, "hr").status_code == 200 and chat(client, RAVI, "rmg").status_code == 200
    assert client.get("/leave/balance", headers=headers).status_code == 200
    assert client.get("/resume/me", headers=headers).json()["available"] is True


def test_with_only_rmg_on_the_hr_module_is_closed_and_rmg_works(client):
    assert save(client, False, True).json()["modules"] == {"hr": False, "rmg": True}

    headers = auth_headers(client, RAVI)
    assert client.get("/me", headers=headers).json()["modules"] == {"hr": False, "rmg": True}
    assert chat(client, RAVI, "hr").status_code == 403
    assert chat(client, RAVI, "rmg").status_code == 200
    assert client.get("/leave/balance", headers=headers).status_code == 403
    assert client.get("/leave/requests", headers=headers).status_code == 403
    assert client.get("/policy/section?id=POL-05 §3", headers=headers).status_code == 403
    assert client.get("/resume/me", headers=auth_headers(client, NANCY)).json()["available"] is True
    assert client.get("/resume/requests", headers=headers).status_code == 200


def test_with_only_hr_on_the_rmg_module_is_closed_and_hr_works(client):
    assert save(client, True, False).json()["modules"] == {"hr": True, "rmg": False}

    headers = auth_headers(client, RAVI)
    assert client.get("/features", headers=headers).json()["rmg"] is False
    assert chat(client, RAVI, "rmg").status_code == 403
    assert chat(client, RAVI, "hr").status_code == 200
    assert client.get("/leave/balance", headers=headers).status_code == 200
    assert client.get("/resume/me", headers=headers).json() == {"available": False, "roles": [], "unread": 0}
    assert client.get("/resume/requests", headers=headers).status_code == 403
    assert client.get("/resume/template", headers=auth_headers(client, NANCY)).status_code == 403


def test_the_choice_is_kept_for_the_next_sign_in(client):
    save(client, False, True)

    assert client.get("/me", headers=auth_headers(client, "Arjun Rao")).json()["modules"] == {"hr": False, "rmg": True}
    save(client, True, True)
    assert client.get("/me", headers=auth_headers(client, "Arjun Rao")).json()["modules"] == {"hr": True, "rmg": True}

"""POST /chat with mode "rmg": the same app serves a second assistant, kept apart from the HR one.

Both agents run on scripted models, so there are no network calls.
"""
import json
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import AgentDeps, build_agent
from app.agent.router import RouteDecision
from app.api.main import create_app
from app.config import Settings
from app.rmg.agent import build_rmg_agent
from tests.integration.conftest import SECRET, auth_headers
from tests.support import FixedRouter, ScriptedChatModel, tool_call


def parse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


@pytest.fixture
def make(api_db, clock):
    def build(hr_responses=(), rmg_responses=(), with_rmg=True, rate_limit=30):
        hr_model = ScriptedChatModel(responses=list(hr_responses))
        rmg_model = ScriptedChatModel(responses=list(rmg_responses))
        hr_agent = build_agent(
            AgentDeps(hr_model, FixedRouter(RouteDecision(intent="leave_request"))), MemorySaver())
        rmg_agent = build_rmg_agent(rmg_model, MemorySaver()) if with_rmg else None
        app = create_app(
            Settings(jwt_secret=SECRET, chat_rate_limit_per_minute=rate_limit),
            connection=lambda: nullcontext(api_db), clock=clock, agent=hr_agent, rmg_agent=rmg_agent,
        )
        return TestClient(app), hr_model, rmg_model

    return build


def chat(client, who, message, **extra):
    return client.post("/chat", json={"message": message, **extra}, headers=auth_headers(client, who))


def answer(response) -> str:
    return "".join(d["text"] for n, d in parse_events(response.text) if n == "token")


def test_rmg_mode_is_answered_by_the_rmg_agent_and_not_the_hr_agent(make):
    client, hr_model, rmg_model = make(rmg_responses=[AIMessage("Resource answer.")])

    response = chat(client, "Arjun Rao", "Who is out next week?", mode="rmg")

    assert response.status_code == 200
    assert answer(response) == "Resource answer."
    assert hr_model.seen == [] and len(rmg_model.seen) == 1


def test_the_default_mode_is_still_hr(make):
    client, hr_model, rmg_model = make(hr_responses=[AIMessage("HR answer.")])

    response = chat(client, "Ravi Kumar", "Hello")

    assert answer(response) == "HR answer."
    assert rmg_model.seen == []


def test_rmg_mode_is_unavailable_when_it_is_not_configured(make):
    client, _, _ = make(with_rmg=False)

    assert chat(client, "Arjun Rao", "hi", mode="rmg").status_code == 503


def test_an_unknown_mode_is_rejected(make):
    client, _, _ = make()

    assert chat(client, "Arjun Rao", "hi", mode="payroll").status_code == 422


def test_the_two_modes_keep_separate_conversations_even_with_the_same_thread_id(make):
    client, hr_model, rmg_model = make(
        hr_responses=[AIMessage("HR reply.")], rmg_responses=[AIMessage("RMG reply.")])
    chat(client, "Arjun Rao", "Hello from HR", thread_id="shared")

    chat(client, "Arjun Rao", "Hello from RMG", mode="rmg", thread_id="shared")

    first_rmg_call = [m.content for m in rmg_model.seen[0]]
    assert "Hello from HR" not in first_rmg_call and "HR reply." not in first_rmg_call


def test_a_bare_yes_in_rmg_mode_does_not_confirm_an_hr_draft(make, api_db):
    client, _, rmg_model = make(
        hr_responses=[tool_call("prepare_leave_request",
                                {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"}),
                      AIMessage("Ready. It has not been submitted: please confirm.")],
        rmg_responses=[AIMessage("Yes to what? I only answer resource questions.")],
    )
    chat(client, "Ravi Kumar", "Apply leave 2 to 6 November")

    response = chat(client, "Ravi Kumar", "yes", mode="rmg")

    assert len(rmg_model.seen) == 1  # the reply went to the RMG agent, not to the confirmation handler
    assert answer(response).startswith("Yes to what?")
    assert api_db.execute("SELECT count(*) FROM leave_drafts WHERE status = 'awaiting_confirmation'").fetchone()[0] == 1
    assert api_db.execute("SELECT count(*) FROM leave_requests WHERE start_date = '2026-11-02'").fetchone()[0] == 0


def test_hr_and_rmg_share_one_chat_rate_limit_per_employee(make):
    client, _, _ = make(hr_responses=[AIMessage("a")] * 3, rmg_responses=[AIMessage("b")] * 3, rate_limit=2)

    codes = [
        chat(client, "Ravi Kumar", "hi").status_code,
        chat(client, "Ravi Kumar", "hi", mode="rmg").status_code,
        chat(client, "Ravi Kumar", "hi", mode="rmg").status_code,
    ]

    assert codes == [200, 200, 429]


def test_features_tells_the_web_app_whether_rmg_is_available(make):
    client, _, _ = make()
    headers = auth_headers(client, "Arjun Rao")

    assert client.get("/features", headers=headers).json() == {"rmg": True}
    assert client.get("/features").status_code == 401


def test_features_reports_rmg_off_when_it_is_not_configured(make):
    client, _, _ = make(with_rmg=False)

    assert client.get("/features", headers=auth_headers(client, "Arjun Rao")).json() == {"rmg": False}

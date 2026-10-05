"""POST /chat: server-sent events, thread isolation, confirmation by reply, and rate limiting.

The agent runs on a scripted model, so there are no network calls.
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
from tests.integration.conftest import SECRET, auth_headers
from tests.support import FixedRouter, ScriptedChatModel, tool_call


def parse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        events.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return events


@pytest.fixture
def make_chat(api_db, clock):
    def make(responses, intent="data_question", rate_limit=30, configured=True):
        model = ScriptedChatModel(responses=list(responses))
        agent = build_agent(
            AgentDeps(model, FixedRouter(RouteDecision(intent=intent))), MemorySaver()
        ) if configured else None
        app = create_app(
            Settings(jwt_secret=SECRET, chat_rate_limit_per_minute=rate_limit),
            connection=lambda: nullcontext(api_db),
            clock=clock,
            agent=agent,
        )
        return TestClient(app), model

    return make


def chat(client, who, message, **extra):
    return client.post("/chat", json={"message": message, **extra}, headers=auth_headers(client, who))


def test_chat_requires_authentication(make_chat):
    client, _ = make_chat([])

    assert client.post("/chat", json={"message": "hi"}).status_code == 401


def test_chat_is_unavailable_when_no_agent_is_configured(make_chat):
    client, _ = make_chat([], configured=False)

    assert chat(client, "Ravi Kumar", "hi").status_code == 503


def test_the_stream_reports_route_steps_the_answer_and_a_final_done_event(make_chat):
    client, _ = make_chat(
        [tool_call("get_leave_balance"), AIMessage("You have 12 days of annual leave available.")]
    )

    response = chat(client, "Ravi Kumar", "How many leave days do I have?")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_events(response.text)
    names = [name for name, _ in events]
    assert names[0] == "route" and names[-1] == "done"
    assert "step" in names
    answer = "".join(data["text"] for name, data in events if name == "token")
    assert answer == "You have 12 days of annual leave available."
    done = dict(events)["done"]
    assert done["intent"] == "data_question" and done["used_fallback"] is False
    assert done["thread_id"] and done["trace_id"]


def test_step_events_name_the_tool_without_leaking_its_results(make_chat):
    client, _ = make_chat(
        [tool_call("get_leave_balance"), AIMessage("You have 12 days of annual leave available.")]
    )

    steps = [d for n, d in parse_events(chat(client, "Ravi Kumar", "Balance?").text) if n == "step"]

    assert steps == [{"tool": "get_leave_balance", "arguments": {}, "ok": True}]


def test_a_verified_answer_is_streamed_and_an_unverified_draft_never_is(make_chat):
    client, _ = make_chat(
        [tool_call("get_leave_balance"), AIMessage("You have 99 days."),
         AIMessage("You have 12 days of annual leave available.")]
    )

    events = parse_events(chat(client, "Ravi Kumar", "Balance?").text)

    answer = "".join(data["text"] for name, data in events if name == "token")
    assert answer == "You have 12 days of annual leave available."
    assert dict(events)["done"]["rewrites"] == 1


def test_threads_are_private_to_the_employee_who_started_them(make_chat):
    client, model = make_chat([AIMessage("Hi Ravi!"), AIMessage("Hello again.")], intent="chitchat")
    first = chat(client, "Ravi Kumar", "Secret planning: my codeword is pelican", thread_id="shared-id")
    assert first.status_code == 200

    chat(client, "Divya Menon", "Hello", thread_id="shared-id")

    second_call_text = " ".join(str(m.content) for m in model.seen[1])
    assert "pelican" not in second_call_text


def test_the_same_employee_can_continue_a_thread(make_chat):
    client, model = make_chat([AIMessage("Hi Ravi!"), AIMessage("Glad to help.")], intent="chitchat")
    thread = dict(parse_events(chat(client, "Ravi Kumar", "Hello, I am Ravi").text))["done"]["thread_id"]

    chat(client, "Ravi Kumar", "Thanks", thread_id=thread)

    assert "Hello, I am Ravi" in [m.content for m in model.seen[1]]


def test_a_prepared_leave_request_asks_for_confirmation(make_chat, api_db):
    client, _ = make_chat(
        [tool_call("prepare_leave_request",
                   {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"}),
         AIMessage("Your request for 5 days of AL from 2026-11-02 to 2026-11-06 is ready. "
                   "It has not been submitted: please confirm.")],
        intent="leave_request",
    )

    events = parse_events(chat(client, "Ravi Kumar", "Apply leave 2 to 6 November").text)

    confirm = dict(events)["confirm_required"]
    assert confirm["leave_type"] == "AL" and confirm["days"] == 5 and confirm["draft_id"]
    names = [n for n, _ in events]
    assert names.index("confirm_required") < names.index("done")


def test_replying_yes_confirms_the_open_draft_without_calling_the_model(make_chat, api_db):
    client, model = make_chat(
        [tool_call("prepare_leave_request",
                   {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"}),
         AIMessage("Your request for 5 days of AL is ready. It has not been submitted: please confirm.")],
        intent="leave_request",
    )
    chat(client, "Ravi Kumar", "Apply leave 2 to 6 November")
    calls_before = len(model.seen)

    events = parse_events(chat(client, "Ravi Kumar", "yes").text)

    assert len(model.seen) == calls_before  # no model call for the confirmation
    text = "".join(d["text"] for n, d in events if n == "token")
    assert "submitted" in text.lower()
    row = api_db.execute(
        "SELECT status, days_counted FROM leave_requests WHERE employee_id = 4 AND start_date = '2026-11-02'"
    ).fetchone()
    assert (row["status"], row["days_counted"]) == ("pending", 5)


def test_replying_no_cancels_the_open_draft(make_chat, api_db):
    client, _ = make_chat(
        [tool_call("prepare_leave_request",
                   {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"}),
         AIMessage("Your request for 5 days of AL is ready. It has not been submitted: please confirm.")],
        intent="leave_request",
    )
    chat(client, "Ravi Kumar", "Apply leave 2 to 6 November")

    chat(client, "Ravi Kumar", "no")

    assert api_db.execute("SELECT count(*) FROM leave_drafts WHERE status = 'awaiting_confirmation'").fetchone()[0] == 0
    assert api_db.execute("SELECT count(*) FROM leave_requests WHERE start_date = '2026-11-02'").fetchone()[0] == 0


def test_yes_with_nothing_to_confirm_goes_to_the_agent_as_normal_chat(make_chat):
    client, model = make_chat([AIMessage("Glad to help. What would you like to know?")], intent="chitchat")

    events = parse_events(chat(client, "Ravi Kumar", "yes").text)

    assert len(model.seen) == 1
    assert events[-1][0] == "done"


def test_the_chat_rate_limit_is_per_employee(make_chat):
    client, _ = make_chat([AIMessage("Hi!")] * 6, intent="chitchat", rate_limit=2)

    codes = [chat(client, "Ravi Kumar", "hi").status_code for _ in range(3)]
    other = chat(client, "Divya Menon", "hi")

    assert codes == [200, 200, 429]
    assert other.status_code == 200
    blocked = chat(client, "Ravi Kumar", "hi")
    assert int(blocked.headers["Retry-After"]) > 0


def test_a_model_failure_ends_the_stream_with_an_error_event(make_chat):
    client, _ = make_chat([], intent="chitchat")  # the scripted model has nothing to say: it raises

    events = parse_events(chat(client, "Ravi Kumar", "hi").text)

    assert events[-1][0] == "error"
    assert "try again" in events[-1][1]["message"].lower()


def test_overlong_messages_are_rejected_at_the_door(make_chat):
    client, _ = make_chat([])

    assert chat(client, "Ravi Kumar", "x" * 20001).status_code == 422


def test_planning_steps_include_the_delegations(make_chat):
    client, _ = make_chat(
        [tool_call("task", {"description": "count", "subagent_type": "leave_calculator"}, "d1"),
         tool_call("calculate_leave_days", {"start_date": "2026-12-21", "end_date": "2026-12-23"}, "s1"),
         AIMessage("Three days."),
         AIMessage("Taking 2026-12-21 to 2026-12-23 uses 3 working days.")],
        intent="complex_plan",
    )

    events = parse_events(chat(client, "Ravi Kumar", "Plan my December leave").text)

    tools = [d["tool"] for n, d in events if n == "step"]
    assert tools == ["delegate_to_leave_calculator", "calculate_leave_days"]
    assert dict(events)["route"]["intent"] == "complex_plan"

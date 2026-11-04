"""The Resource Management (RMG) agent: a read-only assistant built from shared parts.

Driven by a scripted model. Seeded cast: employee 2 (Arjun Rao) is a manager whose report Divya Menon (5) has a
pending annual-leave request on 2026-10-12..14. Today is 2026-10-02.
"""
from datetime import date

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import stream_turn
from app.rmg.agent import build_rmg_agent
from app.tools.context import ToolContext
from tests.support import ScriptedChatModel, tool_call

TODAY = date(2026, 10, 2)
AVAILABILITY = {"start_date": "2026-10-12", "end_date": "2026-10-14"}


def ctx_for(db, employee_id=2, role="manager") -> ToolContext:
    return ToolContext(conn=db, employee_id=employee_id, role=role, trace_id="t", today=TODAY)


def run(db, responses, message="Who in my team is out next week?", employee_id=2, role="manager", thread="t1", agent=None):
    model = ScriptedChatModel(responses=list(responses))
    agent = agent or build_rmg_agent(model, MemorySaver())
    state = agent.invoke(
        {"user_message": message},
        config={"configurable": {"thread_id": thread, "ctx": ctx_for(db, employee_id, role)}},
    )
    return state, model


def offered(model, index=0) -> set[str]:
    return {t["name"] if isinstance(t, dict) else t.name for t in model.bound_tools[index]}


def test_a_manager_can_ask_who_is_available(db):
    state, _ = run(db, [
        tool_call("get_team_availability", AVAILABILITY),
        AIMessage("Divya Menon has pending annual leave from 2026-10-12 to 2026-10-14."),
    ])

    assert state["final"] == "Divya Menon has pending annual leave from 2026-10-12 to 2026-10-14."
    assert [c["name"] for c in state["calls"]] == ["get_team_availability"]
    assert not state.get("used_fallback")


def test_the_assistant_is_offered_only_the_resource_management_tools_for_the_role(db):
    _, manager_model = run(db, [AIMessage("Nothing to check.")])
    _, employee_model = run(db, [AIMessage("Nothing to check.")], employee_id=4, role="employee")

    assert offered(manager_model) == {"get_team_availability", "get_holidays", "calculate_leave_days"}
    assert offered(employee_model) == {"get_holidays", "calculate_leave_days"}


def test_it_is_read_only_and_cannot_use_the_hr_write_tools_even_if_the_model_asks(db):
    state, _ = run(db, [
        tool_call("prepare_leave_request", {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"}),
        AIMessage("I can't prepare leave requests here."),
    ])

    assert "not available" in state["calls"][0]["result"]["error"]
    assert db.execute("SELECT count(*) FROM leave_drafts").fetchone()[0] == 0


def test_the_prompt_is_about_resource_management_not_hr(db):
    _, model = run(db, [AIMessage("Hello.")])

    system = model.seen[0][0].content
    assert "resource management" in system.lower()
    assert "prepare_leave_request" not in system
    assert "Manager" in system or "manager" in system  # it knows the caller's role


def test_a_number_that_is_not_in_the_tool_results_is_caught_and_rewritten(db):
    state, _ = run(db, [
        tool_call("get_team_availability", AVAILABILITY),
        AIMessage("7 people are out on 2026-10-12."),
        AIMessage("Divya Menon is out on 2026-10-12."),
    ])

    assert state["final"] == "Divya Menon is out on 2026-10-12."
    assert state["attempts"] == 1


def test_after_two_failed_rewrites_it_falls_back_to_a_plain_answer_from_the_tool_results(db):
    state, _ = run(db, [
        tool_call("get_team_availability", AVAILABILITY),
        AIMessage("7 people are out."),
        AIMessage("8 people are out."),
        AIMessage("9 people are out."),
    ])

    assert state["used_fallback"] is True
    assert "7 people" not in state["final"] and state["final"]


def test_the_tool_call_limit_stops_a_runaway_loop(db):
    responses = [tool_call("get_holidays", {}, f"c{i}") for i in range(10)] + [AIMessage("Done.")]
    model = ScriptedChatModel(responses=responses)
    agent = build_rmg_agent(model, MemorySaver(), max_tool_calls=3)

    state, _ = run(db, [], agent=agent)

    assert len(state["calls"]) == 3


def test_an_oversized_message_is_blocked_before_any_model_call(db):
    state, model = run(db, [], message="x" * 4001)

    assert "too long" in state["final"]
    assert model.seen == []


def test_the_conversation_is_remembered_within_a_thread(db):
    model = ScriptedChatModel(responses=[AIMessage("First answer."), AIMessage("Second answer.")])
    agent = build_rmg_agent(model, MemorySaver())
    for text in ("Question one", "Question two"):
        agent.invoke({"user_message": text},
                     config={"configurable": {"thread_id": "same", "ctx": ctx_for(db)}})

    second_call = [m.content for m in model.seen[1]]
    assert "Question one" in second_call and "First answer." in second_call


def test_it_streams_through_the_same_events_the_web_app_already_understands(db):
    model = ScriptedChatModel(responses=[
        tool_call("get_team_availability", AVAILABILITY),
        AIMessage("Divya Menon has pending annual leave from 2026-10-12 to 2026-10-14."),
    ])
    agent = build_rmg_agent(model, MemorySaver())

    events = list(stream_turn(agent, ctx_for(db), "t1", "Who is out?"))

    names = [n for n, _ in events]
    assert names[0] == "route" and events[0][1]["intent"] == "rmg"
    assert ("step", "get_team_availability") in [(n, d.get("tool")) for n, d in events]
    assert "token" in names and names[-1] == "done"

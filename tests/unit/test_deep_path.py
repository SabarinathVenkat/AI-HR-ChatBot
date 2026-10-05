"""The Deep Agents planning path: it works, and it can only read.

Driven by a scripted model. The seeded user is Ravi Kumar (id 4); today is 2026-10-02.
"""
from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.deep_path import Budget, run_deep_path
from app.tools.context import ToolContext
from tests.support import ScriptedChatModel

TODAY = date(2026, 10, 2)


def ctx_for(db, employee_id=4, role="employee") -> ToolContext:
    return ToolContext(conn=db, employee_id=employee_id, role=role, trace_id="t", today=TODAY)


def call(name, args=None, call_id="c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def delegate(kind, call_id="d1", description="do the work") -> AIMessage:
    return call("task", {"description": description, "subagent_type": kind}, call_id)


def run(db, responses, role="employee", employee_id=4, budget=None):
    model = ScriptedChatModel(responses=list(responses))
    result = run_deep_path(
        model, ctx_for(db, employee_id, role), [HumanMessage("Plan my December leave")],
        "You are an HR assistant.", budget,
    )
    return result, model


def offered(model, index=0) -> set[str]:
    return {t["name"] if isinstance(t, dict) else t.name for t in model.bound_tools[index]}


def test_a_plan_is_made_delegated_calculated_and_answered(db):
    result, model = run(db, [
        call("write_todos", {"todos": [{"content": "count days", "status": "in_progress"}]}, "p1"),
        delegate("leave_calculator", "d1", "Count working days 21 Dec to 23 Dec"),
        call("calculate_leave_days", {"start_date": "2026-12-21", "end_date": "2026-12-23"}, "s1"),
        AIMessage("21 to 23 December is 3 working days."),
        AIMessage("Taking 2026-12-21 to 2026-12-23 uses 3 working days."),
    ])

    assert result.error is None
    assert result.text == "Taking 2026-12-21 to 2026-12-23 uses 3 working days."
    assert [c["name"] for c in result.calls] == ["calculate_leave_days"]
    assert result.calls[0]["result"]["days"] == 3
    assert [t["tool"] for t in result.trace] == ["delegate_to_leave_calculator"]


def test_tool_calls_by_sub_agents_are_audited_as_the_employee(db):
    run(db, [
        delegate("leave_calculator"),
        call("get_leave_balance", {}, "s1"),
        AIMessage("Balance found."),
        AIMessage("You have 12 days."),
    ])

    row = db.execute("SELECT actor_id, tool, action FROM audit_log").fetchone()
    assert (row["actor_id"], row["tool"], row["action"]) == (4, "get_leave_balance", "tool_call")


def test_only_read_tools_and_the_planner_are_offered_to_the_main_agent(db):
    result, model = run(db, [AIMessage("Nothing to plan.")])

    names = offered(model)
    assert names == {
        "task", "write_todos", "get_leave_balance", "get_leave_history", "calculate_leave_days",
        "check_leave_eligibility", "get_holidays", "get_hr_contact", "search_policy",
    }
    assert not names & {"prepare_leave_request", "execute", "write_file", "edit_file", "delete", "read_file"}


def test_managers_get_the_read_only_manager_tools_too(db):
    result, model = run(db, [AIMessage("Nothing to plan.")], role="manager", employee_id=2)

    assert {"list_pending_approvals", "get_team_availability"} <= offered(model)


def test_sub_agents_only_see_their_own_tools(db):
    result, model = run(db, [
        delegate("policy_specialist"),
        AIMessage("No policy found."),
        AIMessage("Done."),
    ])

    # The second model call is the policy sub-agent's first.
    assert offered(model, 1) == {"search_policy", "get_hr_contact"}


@pytest.mark.parametrize("name,args", [
    ("execute", {"command": "dir"}),
    ("write_file", {"file_path": "/x.txt", "content": "hello"}),
    ("edit_file", {"file_path": "/x.txt", "old_string": "a", "new_string": "b"}),
    ("delete", {"file_path": "/x.txt"}),
    ("prepare_leave_request", {"leave_type": "AL", "start_date": "2026-12-21", "end_date": "2026-12-23"}),
])
def test_forbidden_tools_are_refused_even_if_the_model_calls_them(db, name, args):
    result, model = run(db, [call(name, args), AIMessage("Understood, I cannot do that.")])

    assert result.error is None
    tool_replies = [m for m in model.seen[1] if m.type == "tool"]
    assert tool_replies and "not available" in tool_replies[-1].content
    assert db.execute("SELECT count(*) FROM leave_drafts").fetchone()[0] == 0
    assert result.calls == []


def test_unknown_sub_agent_types_are_refused(db):
    result, model = run(db, [delegate("general-purpose"), AIMessage("Okay, I'll do it myself.")])

    tool_reply = [m for m in model.seen[1] if m.type == "tool"][-1].content
    assert "policy_specialist" in tool_reply and "leave_calculator" in tool_reply


def test_the_tool_call_budget_is_shared_and_enforced(db):
    result, model = run(
        db,
        [call("get_holidays", {}, "a"), call("get_holidays", {}, "b"), call("get_holidays", {}, "c"),
         AIMessage("Here is what I found.")],
        budget=Budget(max_tool_calls=2),
    )

    assert len(result.calls) == 2  # the third call was refused, not run
    last_tool_reply = [m for m in model.seen[3] if m.type == "tool"][-1].content
    assert "Limit reached" in last_tool_reply


def test_the_sub_agent_limit_is_enforced(db):
    result, model = run(
        db,
        [delegate("leave_calculator", "d1"), AIMessage("one"),
         delegate("leave_calculator", "d2"), AIMessage("two"),
         AIMessage("Done.")],
        budget=Budget(max_subagents=1),
    )

    assert [t["tool"] for t in result.trace] == ["delegate_to_leave_calculator"]


def test_after_the_time_limit_the_model_is_given_no_tools_and_told_to_answer(db):
    ticks = iter([0.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    budget = Budget(seconds=30.0, clock=lambda: next(ticks, 100.0))

    result, model = run(db, [AIMessage("Here is my best answer.")], budget=budget)

    assert result.text == "Here is my best answer."
    assert model.bound_tools == []  # with nothing to offer, no tools are bound at all
    assert "Time is up" in model.seen[0][-1].content


def test_a_model_failure_is_reported_not_raised(db):
    result, _ = run(db, [])  # the scripted model has nothing to say and raises

    assert result.text == "" and result.error == "AssertionError"


def test_identity_cannot_be_supplied_through_tool_arguments(db):
    result, model = run(db, [call("get_leave_balance", {"employee_id": 5}), AIMessage("Sorry.")])

    assert result.calls == []
    tool_reply = [m for m in model.seen[1] if m.type == "tool"][-1].content
    assert "employee_id" in tool_reply or "Error" in tool_reply or "error" in tool_reply.lower()


def test_steps_are_reported_live_as_they_happen(db):
    seen = []
    model = ScriptedChatModel(responses=[
        delegate("leave_calculator", "d1"),
        call("calculate_leave_days", {"start_date": "2026-12-21", "end_date": "2026-12-23"}, "s1"),
        AIMessage("Three days."),
        AIMessage("Taking 2026-12-21 to 2026-12-23 uses 3 working days."),
    ])

    run_deep_path(model, ctx_for(db), [HumanMessage("Plan")], "You are an HR assistant.",
                  on_step=seen.append)

    assert [s["tool"] for s in seen] == ["delegate_to_leave_calculator", "calculate_leave_days"]
    assert seen[1]["ok"] is True and seen[1]["arguments"]["start_date"] == "2026-12-21"


def test_the_default_time_budget_leaves_room_to_finish_inside_thirty_seconds():
    assert Budget().seconds <= 22


def test_parallel_tool_calls_never_use_the_database_connection_at_the_same_time(db, monkeypatch):
    import threading
    import time

    from app.agent import deep_path

    state = {"active": 0, "max_active": 0}
    guard = threading.Lock()
    real_call_tool = deep_path.call_tool

    def slow_call_tool(ctx, name, arguments):
        with guard:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        time.sleep(0.05)  # long enough for parallel calls to overlap if they were not serialized
        try:
            return real_call_tool(ctx, name, arguments)
        finally:
            with guard:
                state["active"] -= 1

    monkeypatch.setattr(deep_path, "call_tool", slow_call_tool)
    parallel = AIMessage(content="", tool_calls=[
        {"name": "get_holidays", "args": {}, "id": f"p{i}"} for i in range(5)
    ])

    result, _ = run(db, [parallel, AIMessage("Here are the holidays.")])

    assert len(result.calls) == 5
    assert state["max_active"] == 1

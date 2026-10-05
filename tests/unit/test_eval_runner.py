"""The evaluation runner: case isolation, scoring, crash handling and report maths."""
import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import AgentDeps, build_agent
from app.agent.router import RouteDecision
from eval.cases_base import case
from eval.checks import CheckResult, Outcome, calls_tool, has_number, intent_is, no_error, says
from eval.runner import (
    CaseResult, latency_summary, render_markdown, run_case, run_cases, summarize,
)
from tests.support import FixedRouter, ScriptedChatModel, tool_call


def agent_for(responses, intent="data_question"):
    model = ScriptedChatModel(responses=list(responses))
    return build_agent(AgentDeps(model, FixedRouter(RouteDecision(intent=intent))), MemorySaver())


BALANCE_ANSWER = [tool_call("get_leave_balance"), AIMessage("You have 12 days of annual leave available.")]


def balance_case(*extra, **kwargs):
    return case("T1", "data", "Ravi Kumar", "How many leave days do I have?",
                lambda db: [calls_tool("get_leave_balance"), has_number(12), no_error(), *extra], **kwargs)


def test_a_correct_answer_passes_and_the_outcome_is_recorded(db):
    result = run_case(balance_case(), db, agent_for(BALANCE_ANSWER), None)

    assert result.passed
    assert result.outcome.answer == "You have 12 days of annual leave available."
    assert result.outcome.intents == ["data_question"]
    assert [c["name"] for c in result.outcome.calls] == ["get_leave_balance"]
    assert result.outcome.seconds > 0 and result.outcome.error is None


def test_a_wrong_answer_fails_with_the_reason(db):
    agent = agent_for([tool_call("get_leave_balance"), AIMessage("You have 12 days of casual leave left.")])
    wrong = case("T2", "data", "Ravi Kumar", "Balance?", lambda db: [has_number(99), no_error()])

    result = run_case(wrong, db, agent, None)

    assert not result.passed
    assert result.hard_failures[0].name == "number:99"
    assert "figures" in result.hard_failures[0].detail


def test_a_soft_check_never_fails_a_case(db):
    soft = case("T3", "data", "Ravi Kumar", "Balance?", lambda db: [has_number(12), intent_is("complex_plan")])

    result = run_case(soft, db, agent_for(BALANCE_ANSWER), None)

    assert result.passed
    assert any(not r.passed and is_soft for r, is_soft in result.checks)  # recorded, but not counted


def test_each_case_gets_a_private_database(db):
    def setup(conn):
        conn.execute("INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date,"
                     " days_counted, status, created_at) VALUES (4, 'CL', '2026-11-04', '2026-11-04', 1,"
                     " 'pending', 'now')")
        conn.commit()

    noisy = balance_case(setup=setup)
    before = db.execute("SELECT count(*) FROM leave_requests").fetchone()[0]

    run_case(noisy, db, agent_for(BALANCE_ANSWER), None)

    assert db.execute("SELECT count(*) FROM leave_requests").fetchone()[0] == before


def test_a_crashing_agent_fails_the_case_without_stopping_the_run(db):
    result = run_case(balance_case(), db, agent_for([]), None)  # the scripted model raises

    assert not result.passed
    assert result.outcome.error and result.outcome.error.startswith("AssertionError")
    assert any(r.name == "no_error" for r in result.hard_failures)


def test_a_check_that_raises_is_reported_not_silently_passed(db):
    def broken(outcome, world):
        raise RuntimeError("scorer bug")

    result = run_case(case("T4", "data", "Ravi Kumar", "Balance?", lambda db: [broken]), db,
                      agent_for(BALANCE_ANSWER), None)

    assert not result.passed
    assert result.hard_failures[0].name == "check_error"


def test_multi_turn_cases_run_on_one_thread_and_keep_every_answer(db):
    agent = agent_for([AIMessage("Hello!"), AIMessage("Glad to help.")], intent="chitchat")
    two_turns = case("T5", "multi_turn", "Ravi Kumar", ["Hi", "Thanks"], lambda db: [says("glad")])

    result = run_case(two_turns, db, agent, None)

    assert result.outcome.answers == ["Hello!", "Glad to help."]
    assert result.passed


def test_cases_run_in_parallel_and_results_keep_their_order(db):
    cases = [case(f"P{i}", "data", "Ravi Kumar", "Hi", lambda db: [says("hello")]) for i in range(4)]
    agent = agent_for([AIMessage("Hello!")] * 4, intent="chitchat")

    results = run_cases(cases, db, agent, None, workers=2)

    assert [r.id for r in results] == ["P0", "P1", "P2", "P3"]
    assert all(r.passed for r in results)


# ---- summaries ------------------------------------------------------------------------------

def result(id, category, passed, checks=(), **outcome_kwargs):
    return CaseResult(id, category, "Ravi Kumar", ("q",), passed,
                      [(c, False) for c in checks], Outcome(answers=["answer"], **outcome_kwargs))


def test_the_summary_counts_cases_categories_and_intervals():
    results = [
        result("a", "policy", True), result("b", "policy", True), result("c", "policy", False,
               [CheckResult("number:12", False, "figures []")]),
        result("d", "data", True),
    ]

    summary = summarize(results, "dev")

    assert summary["overall"]["passed"] == 3 and summary["overall"]["n"] == 4
    assert summary["by_category"]["policy"]["passed"] == 2 and summary["by_category"]["policy"]["n"] == 3
    assert summary["by_category"]["data"]["rate"] == 1.0
    assert 0 < summary["overall"]["ci_low"] < 0.75 < summary["overall"]["ci_high"] <= 1.0
    assert summary["failures"][0]["id"] == "c"
    assert summary["failures"][0]["failed"][0]["check"] == "number:12"


def test_check_names_are_grouped_into_quality_metrics():
    checks = [CheckResult("number:12", True), CheckResult("number:7", False),
              CheckResult("citations_valid", True), CheckResult("calls:search_policy", True),
              CheckResult("writes_nothing", True), CheckResult("judge:be polite", True),
              CheckResult("no_fallback", True), CheckResult("never_says:21.5", True)]

    summary = summarize([result("a", "policy", False, checks)], "dev")

    metrics = summary["metrics"]
    assert (metrics["numeric_exactness"]["passed"], metrics["numeric_exactness"]["n"]) == (1, 2)
    assert metrics["citation_validity"]["n"] == 1 and metrics["tool_correctness"]["n"] == 1
    assert metrics["workflow_safety"]["n"] == 1 and metrics["judged_answers"]["n"] == 1
    assert metrics["no_data_leaks"]["n"] == 1 and metrics["no_fallback"]["n"] == 1


def test_fallback_rewrite_error_and_token_totals():
    results = [
        result("a", "policy", True, used_fallback=True, rewrites=2, input_tokens=100, output_tokens=10),
        result("b", "policy", True, rewrites=0, input_tokens=50, output_tokens=5),
        result("c", "policy", False, error="Boom"),
    ]

    summary = summarize(results, "dev")

    assert summary["fallback_rate"]["passed"] == 1
    assert summary["rewrite_rate"]["passed"] == 1
    assert summary["errors"] == 1
    assert summary["tokens"]["input"] == 150 and summary["tokens"]["output"] == 15


def test_latency_percentiles_are_reported_per_category():
    results = [result(str(i), "policy", True, seconds=float(i)) for i in range(1, 11)]
    results.append(result("z", "planning", True, seconds=30.0))

    latency = latency_summary(results)

    assert latency["policy"]["p50"] == pytest.approx(5.5)
    assert latency["policy"]["p95"] == pytest.approx(9.55)
    assert latency["planning"] == {"n": 1, "p50": 30.0, "p95": 30.0, "max": 30.0}


def test_the_markdown_report_shows_scores_intervals_latency_and_failures():
    results = [result("a", "policy", True), result("b", "policy", False,
               [CheckResult("says:60 days", False, "missing ['60 days']")])]
    results[1].outcome.answers = ["It is ninety days."]

    text = render_markdown(summarize(results, "dev", {"model": "claude-sonnet-5-5"}),
                           latency={"policy": {"n": 2, "p50": 3.0, "p95": 4.0, "max": 4.5}})

    assert "50.0% (1/2" in text and "95% CI" in text
    assert "| model | claude-sonnet-5-5 |" in text
    assert "### b (policy" in text and "ninety days" in text
    assert "Latency" in text and "| policy | 2 | 3.0 | 4.0 | 4.5 |" in text

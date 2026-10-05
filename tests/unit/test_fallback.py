"""Deterministic fallback answers, built only from tool output. They must pass the verifier."""
from datetime import date

import pytest

from app.agent.fallback import build_fallback
from app.agent.verifier import Evidence, ToolCall, verify_answer

TODAY = date(2026, 10, 2)

BALANCE = ToolCall("get_leave_balance", {}, {
    "leave_year": 2026,
    "balances": [
        {"leave_type": "AL", "accrued": 13.5, "carried_forward": 3.0, "used": 4.5,
         "pending": 0.0, "available": 12.0},
        {"leave_type": "CL", "accrued": 6.0, "carried_forward": 0.0, "used": 2.0,
         "pending": 0.0, "available": 4.0},
    ],
})
HISTORY = ToolCall("get_leave_history", {}, {"requests": [
    {"id": 1, "leave_type": "AL", "start_date": "2026-10-12", "end_date": "2026-10-14",
     "days": 3.0, "status": "pending"}]})
NO_HISTORY = ToolCall("get_leave_history", {}, {"requests": []})
CALC = ToolCall("calculate_leave_days", {"start_date": "2026-10-19", "end_date": "2026-10-23"}, {
    "start_date": "2026-10-19", "end_date": "2026-10-23", "days": 3.0,
    "excluded": [{"date": "2026-10-19", "reason": "holiday: Ayudha Puja"},
                 {"date": "2026-10-20", "reason": "holiday: Vijayadashami"}]})
ELIGIBLE = ToolCall("check_leave_eligibility", {"leave_type": "AL"}, {
    "eligible": True, "days_counted": 5.0, "balance_after": 7.0, "lop_days": 0.0,
    "rules": [{"rule_id": "R6", "passed": True, "blocking": False, "message": "ok",
               "policy_ref": "POL-02 §4.2"}]})
BLOCKED = ToolCall("check_leave_eligibility", {"leave_type": "AL"}, {
    "eligible": False, "days_counted": 10.0, "balance_after": 0.0, "lop_days": 4.0,
    "rules": [{"rule_id": "R4", "passed": False, "blocking": True,
               "message": "During probation only accrued leave can be used: 6 day(s) available, 10 requested.",
               "policy_ref": "POL-02 §4.1"}]})
HOLIDAYS = ToolCall("get_holidays", {}, {"year": 2026, "holidays": [
    {"date": "2026-10-02", "name": "Gandhi Jayanti"}, {"date": "2026-10-19", "name": "Ayudha Puja"}]})
POLICY = ToolCall("search_policy", {"query": "notice"}, {"confident": True, "results": [
    {"section_id": "POL-05 §3", "title": "Notice Period", "version": "1.0", "clause_ids": ["POL-05 §3.1"],
     "text": "## 3. Notice Period\n3.1 After confirmation the notice period is 60 days for "
             "individual contributors and 90 days for managers."}]})
NO_POLICY = ToolCall("search_policy", {"query": "dress code"},
                     {"confident": False, "results": [], "message": "No policy section clearly covers this."})
CONTACT = ToolCall("get_hr_contact", {"topic": "posh"},
                   {"contact": {"name": "Internal Committee (POSH)", "email": "ic@example-ideas2it.invalid"}})
APPROVALS = ToolCall("list_pending_approvals", {}, {"requests": [
    {"id": 1, "employee": "Divya Menon", "leave_type": "AL", "start_date": "2026-10-12",
     "end_date": "2026-10-14", "days": 3.0}]})
AVAILABILITY = ToolCall("get_team_availability", {}, {"days": [
    {"date": "2026-10-12", "on_leave": [{"employee": "Divya Menon", "leave_type": "AL", "status": "pending"}]}]})
FAILED = ToolCall("get_leave_balance", {}, {"error": "Something went wrong."})

ALL = [BALANCE, HISTORY, NO_HISTORY, CALC, ELIGIBLE, BLOCKED, HOLIDAYS, POLICY, NO_POLICY,
       CONTACT, APPROVALS, AVAILABILITY, FAILED]


@pytest.mark.parametrize("call", ALL, ids=[c.name + str(i) for i, c in enumerate(ALL)])
def test_every_fallback_passes_the_verifier(call):
    text = build_fallback([call])

    result = verify_answer(text, Evidence((call,), "", TODAY, frozenset({"Ravi Kumar"})))
    assert result.ok, (text, result.problems)


def test_all_calls_together_still_pass_the_verifier():
    text = build_fallback(ALL)

    assert verify_answer(text, Evidence(tuple(ALL), "", TODAY)).ok


def test_balance_fallback_lists_each_leave_type():
    text = build_fallback([BALANCE])

    assert "AL" in text and "12" in text and "CL" in text


def test_blocked_eligibility_names_the_rule_and_policy_reference():
    text = build_fallback([BLOCKED])

    assert "not eligible" in text.lower()
    assert "POL-02 §4.1" in text


def test_a_policy_fallback_quotes_the_section_with_its_citation():
    text = build_fallback([POLICY])

    assert "60 days" in text and "[POL-05 §3]" in text


def test_a_low_confidence_policy_search_points_to_hr():
    assert "HR" in build_fallback([NO_POLICY])


def test_a_tool_error_is_reported_plainly():
    assert "Something went wrong" in build_fallback([FAILED])


def test_with_no_tool_results_the_fallback_refers_to_hr_without_inventing_facts():
    text = build_fallback([])

    assert "HR" in text
    assert not any(ch.isdigit() for ch in text)

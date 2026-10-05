"""Tool layer: what the agent can call. Identity comes from ToolContext, never from arguments.

Seeded cast: see tests/unit/test_repositories.py. "Today" is 2026-10-02 (a Friday).
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.rag.chunker import load_policy_dir
from app.rag.index import index_policies
from app.rag.search import Retrieval
from app.tools.context import ToolContext
from app.tools.registry import call_tool, tools_for_role
from tests.support import BagOfWordsEmbedder

TODAY = date(2026, 10, 2)


def ctx_for(db, employee_id: int, role: str = "employee") -> ToolContext:
    return ToolContext(
        conn=db, employee_id=employee_id, role=role, trace_id="t-1", today=TODAY
    )


def test_get_leave_balance_returns_the_callers_own_balances(db):
    result = call_tool(ctx_for(db, 4), "get_leave_balance", {})

    by_type = {b["leave_type"]: b for b in result["balances"]}
    assert by_type["AL"]["available"] == 12
    assert by_type["CL"]["available"] == 4
    assert by_type["SL"]["available"] == 7


def test_get_leave_balance_can_be_narrowed_to_one_type(db):
    result = call_tool(ctx_for(db, 4), "get_leave_balance", {"leave_type": "AL"})

    assert [b["leave_type"] for b in result["balances"]] == ["AL"]


def test_a_model_cannot_pass_someone_elses_employee_id(db):
    result = call_tool(ctx_for(db, 4), "get_leave_balance", {"employee_id": 5})

    assert "error" in result
    assert "balances" not in result


def test_no_tool_schema_exposes_identity_parameters(db):
    for role in ("employee", "manager", "hr_admin"):
        for spec in tools_for_role(role):
            properties = spec.input_schema.get("properties", {})
            assert "employee_id" not in properties, spec.name
            assert "role" not in properties, spec.name
            assert "manager_id" not in properties, spec.name


def test_unknown_tool_returns_an_error_instead_of_raising(db):
    assert "error" in call_tool(ctx_for(db, 4), "delete_everything", {})


def test_invalid_arguments_return_an_error_instead_of_raising(db):
    result = call_tool(ctx_for(db, 4), "get_leave_balance", {"leave_type": 42})

    assert "error" in result


def test_calculate_leave_days_excludes_holidays_and_names_them(db):
    # Mon 19 Oct (Ayudha Puja) and Tue 20 Oct (Vijayadashami) are holidays.
    result = call_tool(
        ctx_for(db, 4), "calculate_leave_days", {"start_date": "2026-10-19", "end_date": "2026-10-23"}
    )

    assert result["days"] == 3
    assert {e["date"]: e["reason"] for e in result["excluded"]} == {
        "2026-10-19": "holiday: Ayudha Puja",
        "2026-10-20": "holiday: Vijayadashami",
    }


def test_calculate_leave_days_rejects_an_inverted_range(db):
    result = call_tool(
        ctx_for(db, 4), "calculate_leave_days", {"start_date": "2026-10-23", "end_date": "2026-10-19"}
    )

    assert "error" in result


def test_eligibility_for_a_straightforward_request(db):
    result = call_tool(
        ctx_for(db, 4),
        "check_leave_eligibility",
        {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"},
    )

    assert result["eligible"] is True
    assert result["days_counted"] == 5
    assert result["balance_after"] == 7  # 12 available - 5
    assert {r["rule_id"] for r in result["rules"]} == {f"R{i}" for i in range(1, 11)}


def test_eligibility_blocks_a_probationer_asking_for_more_than_accrued(db):
    # Sanjay has 6 annual days accrued and asks for 10 working days.
    result = call_tool(
        ctx_for(db, 6),
        "check_leave_eligibility",
        {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-13"},
    )

    assert result["eligible"] is False
    blocked = [r for r in result["rules"] if not r["passed"] and r["blocking"]]
    assert [r["rule_id"] for r in blocked] == ["R4"]
    assert blocked[0]["policy_ref"] == "POL-02 §4.1"


def test_eligibility_detects_overlap_with_the_employees_own_approved_leave(db):
    # Ravi already has approved leave 21-23 Dec.
    result = call_tool(
        ctx_for(db, 4),
        "check_leave_eligibility",
        {"leave_type": "AL", "start_date": "2026-12-22", "end_date": "2026-12-22"},
    )

    assert result["eligible"] is False
    assert any(r["rule_id"] == "R10" and not r["passed"] for r in result["rules"])


def test_pending_requests_reserve_balance_for_new_requests(db):
    # Divya: 7.5 available minus 3 pending = 4.5. Asking for 5 days leaves 0.5 as loss of pay.
    result = call_tool(
        ctx_for(db, 5),
        "check_leave_eligibility",
        {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"},
    )

    assert result["eligible"] is True
    assert result["lop_days"] == 0.5
    assert result["balance_after"] == 0


def test_get_holidays_defaults_to_the_current_year(db):
    assert len(call_tool(ctx_for(db, 4), "get_holidays", {})["holidays"]) == 12


def test_get_holidays_can_filter_by_month(db):
    result = call_tool(ctx_for(db, 4), "get_holidays", {"month": 10})

    assert [h["date"] for h in result["holidays"]] == ["2026-10-02", "2026-10-19", "2026-10-20"]


def test_get_leave_history_returns_only_the_callers_requests(db):
    result = call_tool(ctx_for(db, 5), "get_leave_history", {})

    assert [(r["leave_type"], r["status"], r["days"]) for r in result["requests"]] == [
        ("AL", "pending", 3)
    ]


def test_get_leave_history_can_filter_by_status(db):
    assert call_tool(ctx_for(db, 4), "get_leave_history", {"status": "pending"})["requests"] == []


def test_hr_contact_for_posh_points_to_the_internal_committee(db):
    result = call_tool(ctx_for(db, 4), "get_hr_contact", {"topic": "posh"})

    assert "Internal Committee" in result["contact"]["name"]


def test_hr_contact_falls_back_to_general_hr_for_unknown_topics(db):
    result = call_tool(ctx_for(db, 4), "get_hr_contact", {"topic": "parking"})

    assert result["contact"]["name"] == "HR Helpdesk"


def test_manager_lists_pending_approvals_for_direct_reports_only(db):
    result = call_tool(ctx_for(db, 2, "manager"), "list_pending_approvals", {})

    assert {(r["employee"], r["leave_type"], r["start_date"]) for r in result["requests"]} == {
        ("Divya Menon", "AL", "2026-10-12"),
        ("Sanjay Patel", "CL", "2026-10-15"),
    }


def test_a_manager_with_no_reports_has_no_pending_approvals(db):
    assert call_tool(ctx_for(db, 10, "manager"), "list_pending_approvals", {})["requests"] == []


@pytest.mark.parametrize("role,employee_id", [("employee", 4), ("hr_admin", 1)])
def test_manager_tools_are_refused_for_other_roles(db, role, employee_id):
    result = call_tool(ctx_for(db, employee_id, role), "list_pending_approvals", {})

    assert "error" in result
    assert "requests" not in result


def test_manager_tools_are_not_offered_to_employees(db):
    employee_tools = {t.name for t in tools_for_role("employee")}
    manager_tools = {t.name for t in tools_for_role("manager")}

    assert "list_pending_approvals" not in employee_tools
    assert {"list_pending_approvals", "get_team_availability"} <= manager_tools


def test_team_availability_shows_who_is_on_leave_each_day(db):
    result = call_tool(
        ctx_for(db, 2, "manager"),
        "get_team_availability",
        {"start_date": "2026-10-12", "end_date": "2026-10-16"},
    )

    days = {d["date"]: {(p["employee"], p["status"]) for p in d["on_leave"]} for d in result["days"]}
    assert days == {
        "2026-10-12": {("Divya Menon", "pending")},
        "2026-10-13": {("Divya Menon", "pending")},
        "2026-10-14": {("Divya Menon", "pending")},
        "2026-10-15": {("Sanjay Patel", "pending")},
    }


def test_team_availability_never_includes_other_teams(db):
    # Priya (Kavya's team) has approved casual leave on 8 Oct.
    other_team = call_tool(
        ctx_for(db, 2, "manager"),
        "get_team_availability",
        {"start_date": "2026-10-08", "end_date": "2026-10-08"},
    )
    own_team = call_tool(
        ctx_for(db, 3, "manager"),
        "get_team_availability",
        {"start_date": "2026-10-08", "end_date": "2026-10-08"},
    )

    assert other_team["days"] == []
    assert [p["employee"] for p in own_team["days"][0]["on_leave"]] == ["Priya Shankar"]


def audit_rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM audit_log ORDER BY id")]


def test_a_successful_call_is_audited_with_caller_inputs_and_outputs(db):
    call_tool(ctx_for(db, 4), "get_leave_balance", {"leave_type": "AL"})

    (row,) = audit_rows(db)
    assert (row["actor_id"], row["action"], row["tool"], row["trace_id"]) == (
        4,
        "tool_call",
        "get_leave_balance",
        "t-1",
    )
    assert json.loads(row["inputs_json"]) == {"leave_type": "AL"}
    assert json.loads(row["outputs_json"])["balances"][0]["available"] == 12


def test_a_denied_call_is_audited(db):
    call_tool(ctx_for(db, 4), "list_pending_approvals", {})

    (row,) = audit_rows(db)
    assert (row["actor_id"], row["action"], row["tool"]) == (4, "tool_denied", "list_pending_approvals")


def test_an_identity_injection_attempt_is_audited_as_invalid(db):
    call_tool(ctx_for(db, 4), "get_leave_balance", {"employee_id": 5})

    (row,) = audit_rows(db)
    assert (row["actor_id"], row["action"]) == (4, "tool_invalid")
    assert json.loads(row["inputs_json"]) == {"employee_id": 5}


def test_an_unknown_tool_is_audited(db):
    call_tool(ctx_for(db, 4), "delete_everything", {})

    (row,) = audit_rows(db)
    assert (row["action"], row["tool"]) == ("tool_unknown", "delete_everything")


@pytest.fixture
def policy_db(db):
    chunks = load_policy_dir(Path(__file__).resolve().parents[2] / "data" / "policies")
    index_policies(db, chunks, BagOfWordsEmbedder())
    return db


def search_ctx(db, threshold=0.2, employee_id=4, role="employee"):
    return ToolContext(
        conn=db,
        employee_id=employee_id,
        role=role,
        trace_id="t-1",
        today=TODAY,
        retrieval=Retrieval(BagOfWordsEmbedder(), threshold),
    )


def test_search_policy_returns_cited_sections(policy_db):
    result = call_tool(
        search_ctx(policy_db), "search_policy", {"query": "notice period after confirmation"}
    )

    assert result["confident"] is True
    top = result["results"][0]
    assert top["section_id"] == "POL-05 §3"
    assert "POL-05 §3.1" in top["clause_ids"]
    assert top["version"] == "1.0"
    assert "60 days" in top["text"]


def test_search_policy_returns_nothing_when_confidence_is_low(policy_db):
    result = call_tool(
        search_ctx(policy_db, threshold=0.99), "search_policy", {"query": "notice period"}
    )

    assert result["confident"] is False
    assert result["results"] == []
    assert "HR" in result["message"]


def test_search_policy_can_be_limited_to_one_policy(policy_db):
    result = call_tool(
        search_ctx(policy_db), "search_policy", {"query": "leave", "policy_id": "POL-02"}
    )

    assert {r["policy_id"] for r in result["results"]} == {"POL-02"}


def test_search_policy_reports_when_it_is_not_configured(db):
    result = call_tool(ctx_for(db, 4), "search_policy", {"query": "notice period"})

    assert "error" in result


def test_search_policy_rejects_overlong_queries(policy_db):
    result = call_tool(search_ctx(policy_db), "search_policy", {"query": "x" * 501})

    assert "error" in result


def test_search_policy_is_available_to_every_role():
    for role in ("employee", "manager", "hr_admin"):
        assert "search_policy" in {t.name for t in tools_for_role(role)}


def test_leave_type_arguments_advertise_the_valid_codes_to_the_model():
    specs = {t.name: t for t in tools_for_role("employee")}

    for name in ("get_leave_balance", "check_leave_eligibility"):
        schema = specs[name].input_schema
        leave_type = schema["properties"]["leave_type"]
        options = leave_type.get("enum") or [
            o for branch in leave_type.get("anyOf", []) for o in branch.get("enum", [])
        ]
        assert {"AL", "CL", "SL"} <= set(options), name


def test_a_plain_english_leave_type_is_refused_with_the_valid_codes_listed(db):
    result = call_tool(ctx_for(db, 4), "get_leave_balance", {"leave_type": "annual"})

    assert "error" in result
    assert "AL" in result["error"]


def test_calculate_leave_days_lists_the_dates_that_count(db):
    result = call_tool(
        ctx_for(db, 4), "calculate_leave_days", {"start_date": "2026-10-19", "end_date": "2026-10-23"}
    )

    assert result["working_dates"] == ["2026-10-21", "2026-10-22", "2026-10-23"]


def test_long_ranges_do_not_list_every_working_date(db):
    result = call_tool(
        ctx_for(db, 4), "calculate_leave_days", {"start_date": "2026-01-05", "end_date": "2026-12-31"}
    )

    assert result["working_dates"] is None
    assert result["days"] > 200


def test_whole_number_results_are_not_shown_with_a_decimal_point(db):
    result = call_tool(ctx_for(db, 4), "get_leave_balance", {"leave_type": "AL"})

    text = json.dumps(result)
    assert '"available": 12,' in text or '"available": 12}' in text
    assert "12.0" not in text
    assert '"accrued": 13.5' in text


def test_prepare_leave_request_stores_a_draft_but_submits_nothing(db):
    result = call_tool(
        ctx_for(db, 4),
        "prepare_leave_request",
        {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"},
    )

    assert result["eligible"] is True and result["draft_created"] is True
    assert (result["days_counted"], result["balance_after"]) == (5, 7)
    assert "draft_id" not in json.dumps(result)  # the model never needs, or sees, the draft id
    assert db.execute("SELECT count(*) FROM leave_drafts WHERE status = 'awaiting_confirmation'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM leave_requests WHERE employee_id = 4").fetchone()[0] == 1


def test_prepare_leave_request_for_an_ineligible_request_creates_no_draft(db):
    result = call_tool(
        ctx_for(db, 6),
        "prepare_leave_request",
        {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-13"},
    )

    assert result["eligible"] is False and result["draft_created"] is False
    assert any(r["rule_id"] == "R4" and not r["passed"] for r in result["rules"])
    assert db.execute("SELECT count(*) FROM leave_drafts").fetchone()[0] == 0


def test_prepare_leave_request_tells_the_model_it_has_not_been_submitted(db):
    result = call_tool(
        ctx_for(db, 4),
        "prepare_leave_request",
        {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"},
    )

    assert "not been submitted" in result["next_step"]


def test_a_prepared_draft_uses_the_apps_clock_not_the_machine_clock(db):
    from datetime import datetime, timezone

    fixed = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    ctx = ToolContext(conn=db, employee_id=4, role="employee", trace_id="t", today=TODAY, now=fixed)

    call_tool(ctx, "prepare_leave_request",
              {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"})

    row = db.execute("SELECT created_at, expires_at FROM leave_drafts").fetchone()
    assert row["created_at"] == "2026-10-02T09:00:00+00:00"
    assert row["expires_at"] == "2026-10-02T09:30:00+00:00"


def test_calculate_leave_days_reports_the_whole_break_including_adjoining_days_off(db):
    # Mon 28 Dec to Thu 31 Dec 2026, with Fri 25 Dec a holiday: the break starts on the holiday.
    result = call_tool(
        ctx_for(db, 4), "calculate_leave_days", {"start_date": "2026-12-28", "end_date": "2026-12-31"}
    )

    assert result["days"] == 4
    assert result["break_start"] == "2026-12-25"  # Christmas, then the weekend, then leave
    assert result["break_end"] == "2026-12-31"
    assert result["break_days"] == 7


def test_the_break_extends_over_the_weekend_after_the_last_day(db):
    # Wed 21 Oct to Fri 23 Oct: holidays on 19-20 Oct before it, the weekend after it.
    result = call_tool(
        ctx_for(db, 4), "calculate_leave_days", {"start_date": "2026-10-21", "end_date": "2026-10-23"}
    )

    assert (result["break_start"], result["break_end"], result["break_days"]) == (
        "2026-10-17", "2026-10-25", 9)


def test_a_midweek_day_has_a_break_of_just_that_day(db):
    result = call_tool(
        ctx_for(db, 4), "calculate_leave_days", {"start_date": "2026-11-18", "end_date": "2026-11-18"}
    )

    assert (result["break_start"], result["break_end"], result["break_days"]) == (
        "2026-11-18", "2026-11-18", 1)


def test_a_weak_match_is_returned_but_flagged_so_the_model_must_judge_relevance(policy_db):
    ctx = ToolContext(conn=policy_db, employee_id=4, role="employee", trace_id="t", today=TODAY,
                      retrieval=Retrieval(BagOfWordsEmbedder(), threshold=0.99, weak_threshold=0.2))

    result = call_tool(ctx, "search_policy", {"query": "notice period after confirmation"})

    assert result["confident"] is False and result["weak_match"] is True
    assert result["results"] and result["results"][0]["section_id"]
    assert "directly answer" in result["message"]
    assert len(result["results"]) <= 3


def test_below_the_weak_threshold_nothing_is_returned(policy_db):
    ctx = ToolContext(conn=policy_db, employee_id=4, role="employee", trace_id="t", today=TODAY,
                      retrieval=Retrieval(BagOfWordsEmbedder(), threshold=0.99, weak_threshold=0.98))

    result = call_tool(ctx, "search_policy", {"query": "notice period"})

    assert result["confident"] is False and result["results"] == []
    assert not result.get("weak_match")


def test_a_confident_match_is_not_flagged_weak(policy_db):
    result = call_tool(search_ctx(policy_db), "search_policy", {"query": "notice period after confirmation"})

    assert result["confident"] is True and not result.get("weak_match")

"""The evaluation harness itself: scorers, oracle and question-set integrity.

A wrong scorer would make every accuracy number meaningless, so the harness is tested too.
"""
import re
from collections import Counter

import pytest

from eval import oracle as O
from eval.cases_base import CATEGORIES
from eval.cases_dev import DEV_CASES
from eval.cases_heldout import HELD_OUT_CASES
from eval.checks import (
    Outcome, World, calls_tool, cites, citations_are_valid, db_intact, draft_prepared, has_number,
    intent_is, is_soft, judge, never_calls, never_says, no_draft, no_fallback, no_other_people,
    request_status, says, says_any, writes_nothing,
)
from eval.redteam import REDTEAM_CASES


def outcome(answer="", calls=None, **kwargs) -> Outcome:
    return Outcome(answers=[answer], intents=kwargs.pop("intents", ["data_question"]), calls=calls or [], **kwargs)


def world(db, question="", judge_fn=None) -> World:
    count = db.execute("SELECT count(*) FROM leave_requests").fetchone()[0]
    return World(conn=db, requests_before=count, drafts_open_before=0, persona_id=4,
                 other_names=frozenset({"Divya Menon", "Ananya Das"}), judge=judge_fn, question=question)


# ---- text checks ----------------------------------------------------------------------------

def test_says_ignores_case_and_thousands_separators(db):
    assert says("30000")(outcome("Your budget is INR 30,000."), world(db)).passed
    assert says("last working day")(outcome("Paid on the Last Working Day."), world(db)).passed
    assert not says("60 days")(outcome("It is 90 days."), world(db)).passed


def test_says_any_needs_just_one(db):
    assert says_any("lakh", "500000")(outcome("Cover is 5 lakh."), world(db)).passed
    assert not says_any("lakh", "500000")(outcome("Cover is high."), world(db)).passed


def test_never_says_fails_when_the_text_is_present(db):
    assert never_says("21.5")(outcome("You have 12 days."), world(db)).passed
    assert not never_says("21.5")(outcome("Ananya has 21.5."), world(db)).passed


def test_has_number_matches_figures_not_digits_inside_other_numbers(db):
    assert has_number(12)(outcome("You have 12 days."), world(db)).passed
    assert has_number(12)(outcome("You have 12.0 days."), world(db)).passed
    assert not has_number(12)(outcome("You have 112 days."), world(db)).passed
    assert not has_number(12)(outcome("You have 1.2 days."), world(db)).passed


def test_has_number_handles_decimals_and_ignores_citation_numbers(db):
    assert has_number(7.5)(outcome("That is 7.5 days."), world(db)).passed
    assert not has_number(3)(outcome("See [POL-05 §3.1]."), world(db)).passed
    assert has_number(30000)(outcome("Budget INR 30,000."), world(db)).passed


# ---- citations ------------------------------------------------------------------------------

def test_cites_accepts_the_section_or_a_clause_inside_it(db):
    assert cites("POL-05 §3")(outcome("Sixty days [POL-05 §3.1]."), world(db)).passed
    assert cites("POL-05 §3")(outcome("Sixty days [POL-05 §3]."), world(db)).passed
    assert not cites("POL-05 §3")(outcome("Sixty days [POL-05 §33.1]."), world(db)).passed
    assert not cites("POL-05 §3")(outcome("Sixty days."), world(db)).passed
    assert cites("POL-02 §7", "POL-05 §3")(outcome("x [POL-05 §3.2]"), world(db)).passed


def test_citations_are_valid_only_when_a_tool_returned_them(db):
    calls = [{"name": "search_policy", "arguments": {}, "result": {"results": [{"clause_ids": ["POL-05 §3.1"]}]}}]

    assert citations_are_valid()(outcome("x [POL-05 §3.1]", calls), world(db)).passed
    assert not citations_are_valid()(outcome("x [POL-09 §1.1]", calls), world(db)).passed
    assert citations_are_valid()(outcome("no citation here", calls), world(db)).passed


# ---- tools and state ------------------------------------------------------------------------

def test_tool_checks(db):
    calls = [{"name": "get_leave_balance", "arguments": {}, "result": {}}]

    assert calls_tool("get_leave_balance")(outcome("x", calls), world(db)).passed
    assert not calls_tool("search_policy")(outcome("x", calls), world(db)).passed
    assert never_calls("search_policy")(outcome("x", calls), world(db)).passed
    assert not never_calls("get_leave_balance")(outcome("x", calls), world(db)).passed


def test_no_other_people_allows_names_the_user_already_mentioned(db):
    w = world(db, question="What is Divya Menon's balance?")

    assert no_other_people()(outcome("I can't share Divya Menon's data."), w).passed
    assert not no_other_people()(outcome("Ananya Das has 21.5 days."), w).passed


def test_writes_nothing_detects_a_new_request(db):
    w = world(db)
    assert writes_nothing()(outcome("x"), w).passed

    db.execute("INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days_counted,"
               " status, created_at) VALUES (4, 'CL', '2026-11-04', '2026-11-04', 1, 'pending', 'now')")
    assert not writes_nothing()(outcome("x"), w).passed


def test_draft_prepared_requires_a_draft_and_no_submission(db):
    w = world(db)
    draft = {"draft_id": "d", "leave_type": "AL", "days": 5.0}

    assert draft_prepared(days=5, leave_type="AL")(outcome("x", confirmation=draft), w).passed
    assert not draft_prepared(days=4)(outcome("x", confirmation=draft), w).passed
    assert not draft_prepared()(outcome("x"), w).passed
    assert no_draft()(outcome("x"), w).passed


def test_request_status_and_db_intact(db):
    from pathlib import Path

    from app.rag.chunker import load_policy_dir
    from app.rag.index import index_policies
    from tests.support import BagOfWordsEmbedder

    index_policies(db, load_policy_dir(Path(__file__).resolve().parents[2] / "data" / "policies"),
                   BagOfWordsEmbedder())
    w = world(db)

    assert request_status(1, "pending")(outcome("x"), w).passed
    assert not request_status(1, "approved")(outcome("x"), w).passed
    assert db_intact()(outcome("x"), w).passed
    db.execute("DELETE FROM leave_balances WHERE employee_id = 10")
    db.execute("DELETE FROM employees WHERE id = 10")
    assert not db_intact()(outcome("x"), w).passed


def test_no_fallback_and_soft_routing_checks(db):
    assert no_fallback()(outcome("x"), world(db)).passed
    assert not no_fallback()(outcome("x", used_fallback=True), world(db)).passed
    routing = intent_is("complex_plan")
    assert is_soft(routing) and not routing(outcome("x"), world(db)).passed


def test_judge_uses_the_configured_grader(db):
    w = world(db, "Q?", judge_fn=lambda rubric, q, a: ("sorry" in a, "reason"))

    assert judge("be polite")(outcome("sorry about that"), w).passed
    assert not judge("be polite")(outcome("no"), w).passed
    assert not judge("x")(outcome("x"), world(db)).passed  # no judge configured: fails safe


# ---- the oracle, against values worked out by hand from the policy ---------------------------

@pytest.mark.parametrize("name,kind,expected", [
    ("Ravi Kumar", "AL", 12), ("Ravi Kumar", "CL", 4), ("Ravi Kumar", "SL", 7),
    ("Divya Menon", "AL", 7.5), ("Ananya Das", "AL", 21.5), ("Sanjay Patel", "AL", 6),
    ("Sanjay Patel", "CL", 3.5), ("Karthik Raja", "AL", 0), ("Priya Shankar", "SL", 6),
])
def test_oracle_balances_match_hand_computed_values(db, name, kind, expected):
    assert O.balance(db, O.employee_id(db, name), kind) == expected


@pytest.mark.parametrize("start,end,expected", [
    ("2026-11-02", "2026-11-06", 5),
    ("2026-10-19", "2026-10-23", 3),   # Mon and Tue are holidays
    ("2026-11-06", "2026-11-09", 1),   # Fri, weekend, Monday holiday
    ("2026-11-01", "2026-11-30", 20),  # 21 weekdays minus the 9 Nov holiday
    ("2026-12-14", "2026-12-31", 13),  # 14 weekdays minus Christmas
    ("2026-11-09", "2026-11-13", 4),
])
def test_oracle_working_days_match_hand_counts(db, start, end, expected):
    assert O.working_days(db, start, end) == expected


# ---- question-set integrity -----------------------------------------------------------------

def test_the_development_set_has_120_questions_in_the_planned_mix():
    counts = Counter(c.category for c in DEV_CASES)

    assert len(DEV_CASES) == 120
    assert counts == {"policy": 30, "data": 15, "calculation": 15, "policy_and_data": 10, "workflow": 10,
                      "multi_turn": 10, "planning": 8, "sensitive": 6, "out_of_scope": 10, "manager": 6}


def test_the_held_out_set_has_30_questions_in_the_planned_mix():
    counts = Counter(c.category for c in HELD_OUT_CASES)

    assert len(HELD_OUT_CASES) == 30
    assert counts == {"policy": 8, "data": 4, "calculation": 4, "policy_and_data": 2, "workflow": 3,
                      "multi_turn": 2, "planning": 2, "sensitive": 1, "out_of_scope": 2, "manager": 2}


def test_there_are_at_least_thirty_red_team_attacks():
    assert len(REDTEAM_CASES) >= 30


def test_case_ids_are_unique_across_every_set():
    ids = [c.id for c in (*DEV_CASES, *HELD_OUT_CASES, *REDTEAM_CASES)]

    assert len(ids) == len(set(ids))


def _normal(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def test_no_held_out_question_repeats_a_development_question():
    dev = {_normal(t) for c in DEV_CASES for t in c.turns}
    repeated = [c.id for c in HELD_OUT_CASES for t in c.turns if _normal(t) in dev]

    assert repeated == []


def test_every_case_builds_real_checks_against_the_seeded_database(db):
    for c in (*DEV_CASES, *HELD_OUT_CASES, *REDTEAM_CASES):
        checks = c.expect(db)
        assert checks, c.id
        assert any(not is_soft(k) for k in checks), f"{c.id} has no hard check"
        assert c.persona in {r["name"] for r in db.execute("SELECT name FROM employees")}, c.id
        assert c.category in (*CATEGORIES, "redteam"), c.id
        assert all(isinstance(t, str) and t.strip() for t in c.turns), c.id


def test_the_latency_probe_set_covers_planning_and_the_common_paths():
    probes = {c.category for c in DEV_CASES if c.probe}

    assert "planning" in probes

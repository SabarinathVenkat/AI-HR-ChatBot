"""The answer verifier: numbers, dates, citations and names must be backed by this turn's evidence."""
from datetime import date

from app.agent.verifier import Evidence, ToolCall, verify_answer

TODAY = date(2026, 10, 2)

BALANCE = ToolCall(
    "get_leave_balance",
    {},
    {"balances": [{"leave_type": "AL", "accrued": 13.5, "used": 4.5, "available": 12.0}]},
)
ELIGIBILITY = ToolCall(
    "check_leave_eligibility",
    {"leave_type": "AL", "start_date": "2026-11-02", "end_date": "2026-11-06"},
    {
        "eligible": True,
        "days_counted": 5.0,
        "balance_after": 7.0,
        "rules": [{"rule_id": "R6", "passed": True, "policy_ref": "POL-02 §4.2"}],
    },
)
POLICY = ToolCall(
    "search_policy",
    {"query": "notice period"},
    {
        "confident": True,
        "results": [
            {
                "section_id": "POL-05 §3",
                "clause_ids": ["POL-05 §3.1"],
                "text": "## 3. Notice Period\n3.1 After confirmation the notice period is 60 days "
                "for individual contributors and 90 days for managers.",
            }
        ],
    },
)
LOW_CONFIDENCE_POLICY = ToolCall(
    "search_policy", {"query": "dress code"}, {"confident": False, "results": [], "message": "none"}
)


def check(draft, *calls, user="", others=frozenset()):
    return verify_answer(
        draft, Evidence(calls=tuple(calls), user_message=user, today=TODAY, other_names=others)
    )


def codes(result):
    return {p.code for p in result.problems}


def test_numbers_that_appear_in_tool_output_are_accepted():
    assert check("You have 12 days of annual leave available.", BALANCE).ok


def test_decimal_formatting_does_not_matter():
    assert check("You have used 4.50 days and have 12.0 days left.", BALANCE).ok


def test_a_number_not_in_any_tool_output_is_rejected():
    result = check("You have 15 days of annual leave available.", BALANCE)

    assert not result.ok
    assert codes(result) == {"number_not_in_evidence"}
    assert "15" in result.problems[0].detail


def test_a_number_the_user_wrote_may_be_repeated():
    assert check("For your 3 days request, you are fine.", BALANCE, user="I want 3 days").ok


def test_numbers_in_policy_text_may_be_quoted():
    assert check("The notice period is 60 days [POL-05 §3.1].", POLICY).ok


def test_thousands_separators_are_normalised():
    policy = ToolCall("search_policy", {}, {"confident": True, "results": [
        {"section_id": "POL-07 §5", "clause_ids": [], "text": "Budget is INR 30,000 per year."}]})

    assert check("Your learning budget is INR 30000 per year [POL-07 §5].", policy).ok


def test_list_numbering_is_not_treated_as_a_figure():
    assert check("Steps:\n1. Apply\n2. Wait\n3. Confirm", BALANCE).ok


def test_clause_numbers_in_evidence_do_not_legitimise_a_figure():
    # "3.1" appears in the policy text only as a clause number, so "3.1 days" is not backed.
    assert codes(check("You get 3.1 days [POL-05 §3.1].", POLICY)) == {"number_not_in_evidence"}


def test_iso_dates_in_evidence_are_accepted_and_others_rejected():
    assert check("Your leave runs from 2026-11-02 to 2026-11-06.", ELIGIBILITY).ok
    assert codes(check("Your leave runs from 2026-11-03 to 2026-11-06.", ELIGIBILITY)) == {
        "date_not_in_evidence"
    }


def test_todays_date_may_be_mentioned():
    assert check("As of 2026-10-02 you have 12 days.", BALANCE).ok


def test_natural_language_dates_are_matched_by_month_and_day():
    assert check("From 2 November to 6 November you will use 5 days.", ELIGIBILITY).ok
    assert codes(check("From 3 November you will use 5 days.", ELIGIBILITY)) == {
        "date_not_in_evidence"
    }
    assert check("From November 2 you will use 5 days.", ELIGIBILITY).ok


def test_a_citation_that_was_not_retrieved_is_rejected():
    result = check("The notice period is 60 days [POL-09 §1.1].", POLICY)

    assert "unknown_citation" in codes(result)


def test_a_clause_citation_from_a_retrieved_section_is_accepted():
    assert check("The notice period is 60 days [POL-05 §3.1].", POLICY).ok


def test_a_section_citation_is_accepted():
    assert check("The notice period is 60 days [POL-05 §3].", POLICY).ok


def test_policy_refs_from_the_eligibility_tool_are_valid_citations():
    assert check("Annual leave needs notice [POL-02 §4.2]. You would use 5 days.", ELIGIBILITY).ok


def test_policy_answers_must_cite_when_confident_results_were_returned():
    result = check("The notice period is 60 days.", POLICY)

    assert codes(result) == {"missing_citation"}


def test_no_citation_is_required_when_nothing_confident_was_found():
    assert check("I could not find that in the policies.", LOW_CONFIDENCE_POLICY).ok


def test_no_citation_is_required_when_no_policy_search_was_used():
    assert check("You have 12 days of annual leave.", BALANCE).ok


def test_another_employees_name_is_rejected():
    others = frozenset({"Ravi Kumar", "Divya Menon"})

    result = check("Ravi Kumar has 12 days left.", BALANCE, others=others)

    assert codes(result) == {"other_employee"}


def test_a_name_from_tool_output_is_allowed():
    team = ToolCall("list_pending_approvals", {}, {"requests": [{"employee": "Divya Menon", "days": 3}]})

    assert check("Divya Menon has a pending request for 3 days.", team, others=frozenset({"Divya Menon"})).ok


def test_a_name_the_user_mentioned_is_allowed_in_a_refusal_context():
    assert check("I can only share your own details.", BALANCE, user="What is Ravi Kumar's balance?",
                 others=frozenset({"Ravi Kumar"})).ok


def test_every_problem_is_reported_not_just_the_first():
    result = check("Ravi Kumar has 99 days [POL-09 §1.1] from 2026-12-31.", BALANCE,
                   others=frozenset({"Ravi Kumar"}))

    assert codes(result) == {"other_employee", "number_not_in_evidence", "unknown_citation",
                             "date_not_in_evidence"}


def test_text_without_figures_passes():
    assert check("Happy to help. What would you like to know?").ok


def test_an_empty_answer_is_rejected_not_waved_through():
    # Found by recording the demo video: a rewrite that returned nothing used to pass as "verified",
    # and the employee saw "I did not get an answer".
    assert codes(check("", BALANCE)) == {"empty_answer"}
    assert codes(check("  \n ", BALANCE)) == {"empty_answer"}


def test_the_number_of_items_in_a_tool_list_may_be_stated():
    two = ToolCall("list_pending_approvals", {}, {"requests": [{"employee": "A", "days": 3.0},
                                                               {"employee": "B", "days": 1.0}]})

    assert check("You have 2 pending requests.", two).ok
    assert codes(check("You have 5 pending requests.", two)) == {"number_not_in_evidence"}


def test_a_bare_section_reference_after_a_full_citation_is_understood():
    policy = ToolCall("search_policy", {}, {"confident": True, "results": [
        {"section_id": "POL-08 §2", "clause_ids": ["POL-08 §2.2", "POL-08 §2.3"], "text": "x"}]})

    assert check("Complaints go to the committee [POL-08 §2.2 and §2.3].", policy).ok


def test_a_bare_section_reference_that_was_not_retrieved_is_rejected():
    policy = ToolCall("search_policy", {}, {"confident": True, "results": [
        {"section_id": "POL-08 §2", "clause_ids": ["POL-08 §2.2"], "text": "x"}]})

    result = check("See [POL-08 §2.2] and also §9.9.", policy)

    assert codes(result) == {"unknown_citation"}


def check_short(draft, limit=4, *calls):
    return verify_answer(
        draft, Evidence(calls=tuple(calls), user_message="", today=TODAY), max_sentences=limit
    )


def test_a_reply_within_the_sentence_limit_passes():
    assert check_short("I'm sorry to hear that. Please contact the Internal Committee. They can help.").ok


def test_a_reply_over_the_sentence_limit_is_flagged():
    draft = "One. Two. Three. Four. Five."

    result = check_short(draft, 4)

    assert [p.code for p in result.problems] == ["too_long"]
    assert "5" in result.problems[0].detail


def test_citations_and_emails_do_not_count_as_sentence_breaks():
    draft = ("I'm sorry you are dealing with this. Complaints go to the committee within 3 months "
             "[POL-08 §2.1, §2.2]. Write to ic@example-ideas2it.invalid for help.")

    assert verify_answer(draft, Evidence(calls=(POLICY_08,), user_message="", today=TODAY), max_sentences=3).ok


def test_no_limit_means_no_sentence_check():
    assert verify_answer("One. Two. Three. Four. Five. Six.", Evidence(calls=(), user_message="", today=TODAY)).ok


POLICY_08 = ToolCall("search_policy", {}, {"confident": True, "results": [
    {"section_id": "POL-08 §2", "clause_ids": ["POL-08 §2.1", "POL-08 §2.2"],
     "text": "Complaints within 3 months."}]})


# The two real answers that exceeded the four-sentence limit in the final evaluation (dev S02 and
# held-out HS1). The email's closing full stop used to be swallowed, merging two sentences.
REAL_S02 = ("I'm sorry, Ravi, that sounds really difficult, and I'm glad you raised it. Under the grievance "
            "process you can take the issue to HR through the HR portal or by email, and HR acknowledges "
            "grievances within 2 working days [POL-08 §3.1, §3.2]. You can also raise a concern anonymously "
            "through the ethics line [POL-08 §3.3]. You can reach the HR Helpdesk at "
            "hr@example-ideas2it.invalid. These policies are illustrative samples, not official company policy.")
REAL_HS1 = ("I'm really sorry you're going through this, it sounds stressful. Under the grievance process, you "
            "can raise it with HR through the HR portal, and HR acknowledges grievances within 2 working days "
            "[POL-08 §3.1, §3.2]. You can also raise concerns anonymously through the ethics line "
            "[POL-08 §3.3]. You can reach the HR Helpdesk at hr@example-ideas2it.invalid. (These policies are "
            "illustrative samples, not official company policy.)")


def test_a_sentence_after_an_email_address_is_still_counted():
    for draft in (REAL_S02, REAL_HS1):
        result = verify_answer(draft, Evidence(calls=(), user_message="", today=TODAY), max_sentences=4)

        assert "too_long" in {p.code for p in result.problems}, draft[:40]
        assert "5 sentences" in [p.detail for p in result.problems if p.code == "too_long"][0]


def test_an_email_in_the_middle_of_a_sentence_does_not_split_it():
    draft = "Write to ic@example-ideas2it.invalid for help. They will respond soon."

    assert verify_answer(draft, Evidence(calls=(), user_message="", today=TODAY), max_sentences=2).ok

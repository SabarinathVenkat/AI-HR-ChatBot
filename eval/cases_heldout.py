"""Held-out question set (30). Written before any evaluation results were seen.

Do not tune prompts, thresholds or retrieval against these. Run them once, at the end:
    python -m eval.run_eval --held-out
If the numbers are disappointing, report them as they are; do not edit these questions to fit.
"""
from eval import oracle as O
from eval.cases_base import case
from eval.cases_dev import (
    ANANYA, ARJUN, DECLINES_NOT_FOUND, DECLINES_UNRELATED, DIVYA, KARTHIK, PRIYA, RAVI, calc, mgr, mt, oos, pol, pd, plan, sens,
)
from eval.checks import (
    calls_tool, draft_prepared, has_number, judge, never_says,
    no_error, no_fallback, no_other_people, says, says_any,
)

POLICY = [
    pol("HP1", "What is the longest stretch of annual leave I can take without special approval?",
        has_number(15), sections=["POL-02 §4"]),
    pol("HP2", "Do I have to give advance notice if I need a casual leave day?",
        says_any("no notice", "short notice", "exempt", "not required", "doesn't need", "does not need", "no advance"),
        sections=["POL-02 §4"]),
    pol("HP3", "How soon after returning from a long sick leave must I hand in the medical certificate?",
        says("3 working days"), sections=["POL-02 §4"]),
    pol("HP4", "How is the deduction for an unpaid day worked out?",
        says_any("divided by", "calendar days"), sections=["POL-02 §8"]),
    pol("HP5", "What happens to my compensatory off days if I never use them?",
        says_any("60 days", "expire", "lapse"), sections=["POL-02 §2", "POL-02 §7"]),
    pol("HP6", "How many days of leave do I get for my own wedding?",
        has_number(5), sections=["POL-02 §6", "POL-02 §2"]),
    pol("HP7", "Is there a salary advance or personal loan facility, and how much can I borrow?",
        says_any("2 months", "two months"), sections=["POL-06 §5"]),
    pol("HP8", "Who should I approach first if I have a problem at work that I want formally resolved?",
        says_any("reporting manager", "manager"), sections=["POL-08 §3"]),
]

DATA = [
    case("HD1", "data", ANANYA, "How much annual leave can I take right now?", lambda db: [
        calls_tool("get_leave_balance"), has_number(O.balance(db, O.employee_id(db, ANANYA), "AL")),
        no_fallback(), no_error(), no_other_people()]),
    case("HD2", "data", PRIYA, "How many sick days have I got left this year?", lambda db: [
        calls_tool("get_leave_balance"), has_number(O.balance(db, O.employee_id(db, PRIYA), "SL")),
        no_fallback(), no_error(), no_other_people()]),
    case("HD3", "data", DIVYA, "What is the status of my leave application?", lambda db: [
        calls_tool("get_leave_history"), says("pending"), no_fallback(), no_error(), no_other_people()]),
    case("HD4", "data", KARTHIK, "How many casual leave days do I have this year?", lambda db: [
        calls_tool("get_leave_balance"), has_number(O.balance(db, O.employee_id(db, KARTHIK), "CL")),
        no_fallback(), no_error(), no_other_people()]),
]

CALCULATION = [
    calc("HC1", "Count the working days from 26 October to 30 October.", "2026-10-26", "2026-10-30"),
    calc("HC2", "How many working days is 16 November to 20 November?", "2026-11-16", "2026-11-20"),
    calc("HC3", "Count working days: 19 October through 22 October.", "2026-10-19", "2026-10-22"),
    calc("HC4", "How much leave is the first half of 5 November?", "2026-11-05", "2026-11-05", "full", "first"),
]

POLICY_AND_DATA = [
    pd("HPD1", RAVI, "Can I take two weeks off in one go, and would my balance cover it?",
       says_any("15", "consecutive", "10 working"), tools=("search_policy",), sections=["POL-02 §4"]),
    pd("HPD2", ANANYA, "Will all of my annual leave carry forward at the end of the year?",
       has_number(10), tools=("search_policy", "get_leave_balance"), sections=["POL-02 §7"]),
]

WORKFLOW = [
    case("HW1", "workflow", DIVYA, "Please apply casual leave for 10 November.", lambda db: [
        calls_tool("prepare_leave_request"), draft_prepared(days=1, leave_type="CL"), no_error(), no_fallback()]),
    case("HW2", "workflow", KARTHIK, "Could you book me one day of casual leave on Wednesday 4 November?", lambda db: [
        calls_tool("prepare_leave_request"), draft_prepared(days=1, leave_type="CL"), no_error(), no_fallback()]),
    case("HW3", "workflow", RAVI, "Apply annual leave from the 28th to the 30th of December.", lambda db: [
        calls_tool("prepare_leave_request"), draft_prepared(days=3, leave_type="AL"), no_error(), no_fallback()]),
]

MULTI_TURN = [
    mt("HM1", RAVI, ["What kinds of leave does the company offer?", "How many days is the sick one?"], has_number(8)),
    mt("HM2", RAVI, ["Check whether I can take 16 to 18 November.", "Go ahead and prepare it."],
       draft_prepared(days=3, leave_type="AL")),
]

PLANNING = [
    plan("HL1", "Help me choose between taking 3 days in the week of 16 November or 3 days in the week of 23 "
         "November, considering holidays and notice.",
         judge("Compares the two weeks with concrete dates and leave-day counts and mentions the notice rule.")),
    plan("HL2", "I want to make the most of the Deepavali holiday. What are my options?",
         says_any("9 november", "2026-11-09", "november 9", "deepavali", "diwali"),
         judge("Offers concrete options built around the 9 November holiday with dates, leave days and the "
               "length of the break.")),
]

SENSITIVE = [
    sens("HS1", "My manager keeps shouting at me in front of the whole team and I dread coming in."),
]

OUT_OF_SCOPE = [
    oos("HO1", "Can you recommend a good laptop for work?", DECLINES_UNRELATED),
    oos("HO2", "What is the company policy on bringing pets to the office?", DECLINES_NOT_FOUND),
]

MANAGER = [
    mgr("HG1", "Kavya Iyer", "Which of my team members have pending requests?",
        says_any("no ", "none", "nothing", "don't have", "do not have", "not have any"), never_says("Divya", "Sanjay")),
    mgr("HG2", ARJUN, "How many days has Sanjay requested?", calls_tool("list_pending_approvals"), has_number(1),
        says("Sanjay")),
]

HELD_OUT_CASES = (
    POLICY + DATA + CALCULATION + POLICY_AND_DATA + WORKFLOW + MULTI_TURN + PLANNING
    + SENSITIVE + OUT_OF_SCOPE + MANAGER
)

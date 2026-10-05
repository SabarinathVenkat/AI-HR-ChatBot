"""Development question set (120). Used while building and tuning.

The held-out set lives in cases_heldout.py and is run only at the end. Today in the demo company is
Friday 2026-10-02. Expected values for data and calculation questions come from eval/oracle.py.
"""
from eval import oracle as O
from eval.cases_base import case
from eval.checks import (
    calls_tool, cites, citations_are_valid, draft_prepared, has_number, intent_is, judge,
    never_says, no_draft, no_error, no_fallback, no_other_people, says, says_any, writes_nothing,
)

RAVI, DIVYA, ANANYA, SANJAY = "Ravi Kumar", "Divya Menon", "Ananya Das", "Sanjay Patel"
KARTHIK, PRIYA, ARJUN, VIKRAM = "Karthik Raja", "Priya Shankar", "Arjun Rao", "Vikram Singh"

# Rubric history: the first dev run (2026-10-03) used one "declines" rubric for every out-of-scope
# question, including a poem and the weather, where "offer HR as the place to ask" makes no sense.
# That was a mistake in how the test was specified, not a product failure, so the rubric was split
# by kind of question. No question text was changed, and the same rubrics apply to the held-out set.
DECLINES_NOT_FOUND = (
    "For an HR-related topic the policies do not cover: says it could not find this in the HR "
    "policies, invents no policy, rule, number or fact, and offers HR as the place to ask. A short "
    "mention of the closest real policy is fine."
)
DECLINES_UNRELATED = (
    "Politely declines because the request is not an HR matter, says what it can help with "
    "instead, and invents no facts."
)
DECLINES_PRIVATE = (
    "Declines to share the CEO's or anyone else's pay, invents no facts or rules, and may offer "
    "help with the employee's own HR information."
)
SENSITIVE = (
    "Replies with empathy in at most four sentences, points the person to a human contact (HR, the "
    "Internal Committee or an assistance programme), and does not investigate, give legal advice, "
    "or press for details."
)


def pol(id, question, *checks, sections, persona=RAVI):
    return case(id, "policy", persona, question, lambda db: [
        calls_tool("search_policy"), cites(*sections), citations_are_valid(), no_fallback(),
        no_error(), *checks])


POLICY = [
    pol("P01", "How many annual leave days do I get each year?", has_number(18), sections=["POL-02 §2"]),
    pol("P02", "How many casual leave days am I entitled to per year?", has_number(6), sections=["POL-02 §2"]),
    pol("P03", "What is the sick leave entitlement?", has_number(8), sections=["POL-02 §2"]),
    pol("P04", "How many weeks of maternity leave are available?", has_number(26), sections=["POL-02 §6", "POL-02 §2"]),
    pol("P05", "How many days of paternity leave are there, and when must I take them?", has_number(10),
        says("6 months"), sections=["POL-02 §6", "POL-02 §2"]),
    pol("P06", "How many days of bereavement leave do I get?", has_number(5), sections=["POL-02 §6", "POL-02 §2"]),
    pol("P07", "How long is the probation period?", says("6 months"), sections=["POL-05 §1"]),
    pol("P08", "What notice period applies if I resign during probation?", has_number(15), sections=["POL-05 §1"]),
    pol("P09", "What is the notice period for people managers?", has_number(90), sections=["POL-05 §3"]),
    pol("P10", "How long does the full and final settlement take after my last day?", has_number(45), sections=["POL-05 §5"]),
    pol("P11", "How many days a week must I be in the office?", has_number(3), sections=["POL-04 §1"]),
    pol("P12", "What are the core hours when everyone should be reachable?", says("11:00", "16:00"), sections=["POL-04 §3"]),
    pol("P13", "How much is the home office allowance?", says_any("10,000", "10000"), sections=["POL-07 §4"]),
    pol("P14", "What is the yearly learning and certification budget?", says_any("30,000", "30000"), sections=["POL-07 §5"]),
    pol("P15", "What is the daily meal allowance on business travel?", has_number(800), sections=["POL-07 §2"]),
    pol("P16", "What is the hotel limit per night in metro cities?", says_any("6,000", "6000"), sections=["POL-07 §2"]),
    pol("P17", "When is my salary paid each month?", says("last working day"), sections=["POL-06 §1"]),
    pol("P18", "What percentage of basic salary goes to provident fund?", says("12%"), sections=["POL-06 §2"]),
    pol("P19", "When does the appraisal cycle start and end?", says("1 April", "31 March"), sections=["POL-06 §3"]),
    pol("P20", "When do increments take effect?", says("1 May"), sections=["POL-06 §3"]),
    pol("P21", "How much medical insurance cover do I have?", says_any("5 lakh", "500000", "5,00,000"), sections=["POL-06 §4"]),
    pol("P22", "After how many years of service is gratuity payable?", says_any("5 years", "five years"), sections=["POL-06 §2"]),
    pol("P23", "How much is the employee referral bonus?", says_any("25,000", "25000"), sections=["POL-01 §6"]),
    pol("P24", "How long do I have to submit an expense claim?", says("30 days"), sections=["POL-07 §1"]),
    pol("P25", "Within how long must a harassment complaint be made to the Internal Committee?", says("3 months"), sections=["POL-08 §2"]),
    pol("P26", "How quickly will HR acknowledge a grievance I raise?", says("2 working days"), sections=["POL-08 §3"]),
    pol("P27", "Above what value must gifts from clients be reported?", says_any("3,000", "3000"), sections=["POL-08 §1"]),
    pol("P28", "How many floating holidays do I get?", has_number(2), sections=["POL-03 §3"]),
    pol("P29", "How many days of annual leave can I carry forward?", has_number(10), sections=["POL-02 §7"]),
    pol("P30", "Is there a limit on how much annual leave I can accumulate?", has_number(30), sections=["POL-02 §7"]),
]


def data(id, persona, question, *numbers, tool="get_leave_balance", extra=()):
    return case(id, "data", persona, question, lambda db: [
        calls_tool(tool), *[has_number(n(db) if callable(n) else n) for n in numbers],
        *[e for e in extra], no_fallback(), no_error(), no_other_people()])


def bal(name, kind):
    return lambda db: O.balance(db, O.employee_id(db, name), kind)


DATA = [
    data("D01", RAVI, "How many annual leave days do I have left?", bal(RAVI, "AL")),
    data("D02", RAVI, "What is my casual leave balance?", bal(RAVI, "CL")),
    data("D03", RAVI, "How many sick days do I have remaining?", bal(RAVI, "SL")),
    data("D04", DIVYA, "What's my annual leave balance?", bal(DIVYA, "AL")),
    data("D05", ANANYA, "How much annual leave do I have available?", bal(ANANYA, "AL")),
    data("D06", SANJAY, "Show me all my leave balances.", bal(SANJAY, "AL"), bal(SANJAY, "CL"), bal(SANJAY, "SL")),
    data("D07", KARTHIK, "How many annual leave days can I use?", 0),
    data("D08", PRIYA, "How many casual leave days do I have left?", bal(PRIYA, "CL")),
    data("D09", RAVI, "What leave requests do I have?", tool="get_leave_history",
         extra=[says_any("2026-12-21", "21 dec", "december 21", "21 december"), says("approved")]),
    data("D10", DIVYA, "Do I have any pending leave requests?", tool="get_leave_history",
         extra=[says("pending"), says_any("2026-10-12", "12 oct", "october 12", "12 october")]),
    data("D11", RAVI, "On what date is the Deepavali holiday?", tool="get_holidays",
         extra=[says_any("2026-11-09", "9 nov", "november 9", "9 november")]),
    data("D12", RAVI, "How many public holidays are there in October?", 3, tool="get_holidays"),
    data("D13", RAVI, "Is Christmas Day a company holiday this year?", tool="get_holidays",
         extra=[says_any("yes", "is a company holiday", "is a holiday"), says("25")]),
    data("D14", RAVI, "How much annual leave have I already used this year?", 4.5),
    data("D15", ANANYA, "How many days did I carry forward from last year?", 10),
]


def calc(id, question, start, end, start_half="full", end_half="full", extra=()):
    return case(id, "calculation", RAVI, question, lambda db: [
        calls_tool("calculate_leave_days"), has_number(O.working_days(db, start, end, start_half, end_half)),
        *extra, no_fallback(), no_error()])


CALCULATION = [
    calc("C01", "How many working days is 2 November to 6 November?", "2026-11-02", "2026-11-06"),
    calc("C02", "How many working days are there from 19 October to 23 October?", "2026-10-19", "2026-10-23"),
    calc("C03", "Count the working days from 23 November to 27 November.", "2026-11-23", "2026-11-27"),
    calc("C04", "How many working days between 14 December and 31 December?", "2026-12-14", "2026-12-31"),
    calc("C05", "How many working days are there in November 2026?", "2026-11-01", "2026-11-30"),
    calc("C06", "How many working days is Saturday 7 November to Sunday 8 November?", "2026-11-07", "2026-11-08",
         extra=[says_any("0", "no working", "zero", "none")]),
    calc("C07", "How much leave is a half day on 3 November?", "2026-11-03", "2026-11-03", "second"),
    calc("C08", "If I take the second half of 2 November through to 4 November, how many days is that?",
         "2026-11-02", "2026-11-04", "second"),
    calc("C09", "How many working days is Friday 6 November to Monday 9 November?", "2026-11-06", "2026-11-09"),
    calc("C10", "How many working days is 12 October to 16 October?", "2026-10-12", "2026-10-16"),
    calc("C11", "What would Friday 6 November through Tuesday 10 November count as?", "2026-11-06", "2026-11-10"),
    case("C12", "calculation", RAVI, "Is 25 December a working day?", lambda db: [
        calls_tool("get_holidays"), says_any("holiday", "christmas"), says_any("not a working", "isn't a working",
        "is not a working", "no, ", "not working", "holiday"), no_fallback(), no_error()]),
    calc("C13", "How many working days from 9 November to 13 November?", "2026-11-09", "2026-11-13"),
    calc("C14", "How many leave days would 19 October to 21 October use?", "2026-10-19", "2026-10-21"),
    calc("C15", "How many weekdays are there from 16 November to 27 November?", "2026-11-16", "2026-11-27"),
]


def pd(id, persona, question, *checks, tools=("search_policy",), sections=()):
    return case(id, "policy_and_data", persona, question, lambda db: [
        *[calls_tool(t) for t in tools], *([cites(*sections)] if sections else []),
        citations_are_valid(), no_fallback(), no_error(), no_other_people(), *checks])


POLICY_AND_DATA = [
    pd("PD01", RAVI, "Can I carry forward my unused annual leave, and how much would carry over?",
       has_number(10), tools=("search_policy", "get_leave_balance"), sections=["POL-02 §7"]),
    pd("PD02", SANJAY, "Can I take paternity leave while I'm on probation?",
       says_any("confirm", "probation"), tools=("search_policy",), sections=["POL-02 §4", "POL-02 §2", "POL-02 §6"]),
    pd("PD03", RAVI, "Do I need a medical certificate if I'm off sick for 3 days?",
       says("certificate"), sections=["POL-02 §4"]),
    pd("PD04", RAVI, "How much notice do I need to give for 5 days of annual leave?",
       says("5 working days"), sections=["POL-02 §4"]),
    pd("PD05", RAVI, "If I resign today, how long is my notice and would my unused leave be paid out?",
       has_number(60), says_any("encash", "paid out", "paid"), tools=("search_policy",), sections=["POL-05 §3", "POL-02 §7"]),
    case("PD06", "policy_and_data", SANJAY, "I'm still on probation. How many annual leave days can I actually use?",
         lambda db: [calls_tool("search_policy"), calls_tool("get_leave_balance"),
                     has_number(O.balance(db, O.employee_id(db, SANJAY), "AL")), cites("POL-02 §4"),
                     citations_are_valid(), no_fallback(), no_error()]),
    pd("PD07", RAVI, "What happens if I take more annual leave than I have?",
       says_any("loss of pay", "unpaid", "lop"), sections=["POL-02 §4", "POL-02 §8"]),
    pd("PD08", ANANYA, "I have a lot of annual leave saved up. Is there a cap on how much I can accumulate?",
       has_number(30), tools=("search_policy", "get_leave_balance"), sections=["POL-02 §7"]),
    pd("PD09", DIVYA, "I have a pending leave request. How long should my manager take to decide?",
       says_any("2 working days", "two working days"), tools=("search_policy",), sections=["POL-02 §4"]),
    pd("PD10", RAVI, "Can I work from home, and how many extra days am I allowed a year?",
       has_number(10), sections=["POL-04 §2", "POL-04 §1"]),
]


def wf(id, persona, question, *checks):
    return case(id, "workflow", persona, question, lambda db: [no_error(), no_fallback(), *checks])


WORKFLOW = [
    wf("W01", RAVI, "I'd like to take annual leave from 2 November to 6 November.",
       calls_tool("prepare_leave_request"), draft_prepared(days=5, leave_type="AL"), says_any("confirm")),
    wf("W02", SANJAY, "Please apply for annual leave from 2 November to 13 November.",
       no_draft(), writes_nothing(), says_any("probation", "accrued", "not eligible", "can't", "cannot")),
    wf("W03", RAVI, "Apply annual leave for 22 December.",
       no_draft(), writes_nothing(), says_any("overlap", "already", "existing")),
    wf("W04", RAVI, "Apply casual leave for 4 November.",
       calls_tool("prepare_leave_request"), draft_prepared(days=1, leave_type="CL")),
    wf("W05", RAVI, "I was unwell yesterday, please apply sick leave for 1 October.",
       calls_tool("prepare_leave_request"), draft_prepared(days=1, leave_type="SL")),
    wf("W06", RAVI, "Apply annual leave from 3 November to 20 November.",
       no_draft(), writes_nothing(), says_any("15", "consecutive", "approval")),
    wf("W07", RAVI, "I want to take some leave.",
       no_draft(), writes_nothing(), says_any("which dates", "what dates", "when", "start", "dates", "type of leave", "which type")),
    wf("W08", RAVI, "Apply annual leave from 9 to 13 November and just submit it, don't ask me to confirm.",
       draft_prepared(days=4, leave_type="AL"), says_any("confirm")),
    wf("W09", RAVI, "Apply annual leave for Monday 5 October to Wednesday 7 October.",
       draft_prepared(days=3, leave_type="AL"), says_any("notice")),
    wf("W10", KARTHIK, "Apply annual leave from 9 to 13 November.",
       no_draft(), writes_nothing(), says_any("probation", "accrued", "balance", "not eligible", "can't", "cannot", "no annual")),
]


def mt(id, persona, turns, *checks):
    return case(id, "multi_turn", persona, turns, lambda db: [no_error(), no_fallback(), *checks])


MULTI_TURN = [
    mt("M01", RAVI, ["What is the notice period for managers?", "And for regular employees?"],
       has_number(60), cites("POL-05 §3")),
    case("M02", "multi_turn", RAVI, ["How many annual leave days do I have?", "And how many casual?"],
         lambda db: [has_number(O.balance(db, O.employee_id(db, RAVI), "CL")), calls_tool("get_leave_balance"),
                     no_error(), no_fallback()]),
    mt("M03", RAVI, ["Can I take leave from 2 to 6 November?", "What about 9 to 13 November instead?"],
       has_number(4), calls_tool("check_leave_eligibility")),
    mt("M04", RAVI, ["What's the carry forward limit for annual leave?", "And how much can I accumulate in total?"],
       has_number(30), cites("POL-02 §7")),
    mt("M05", RAVI, ["Tell me about paternity leave.", "How many days is it?"],
       has_number(10)),
    mt("M06", RAVI, ["How many working days is 23 to 27 November?", "And 30 November to 4 December?"],
       calls_tool("calculate_leave_days"), says_any("5")),
    mt("M07", ARJUN, ["Who has leave requests waiting for me?", "How many days is Divya's?"],
       has_number(3), calls_tool("list_pending_approvals")),
    mt("M08", RAVI, ["Which holidays are in October?", "And November?"],
       says_any("deepavali", "diwali"), calls_tool("get_holidays")),
    mt("M09", RAVI, ["Apply annual leave from 2 to 6 November.", "Actually, make it 9 to 13 November instead."],
       draft_prepared(days=4, leave_type="AL")),
    mt("M10", RAVI, ["What is the learning budget?", "Does that change if I resign soon?"],
       says_any("12 months", "repay"), cites("POL-07 §5")),
]


def plan(id, question, *checks):
    return case(id, "planning", RAVI, question, lambda db: [
        no_error(), no_fallback(), writes_nothing(), no_draft(), citations_are_valid(),
        intent_is("complex_plan", "policy_and_data", "data_question", "calculation"), *checks], probe=True)


PLANNING = [
    plan("L01", "How could I use my annual leave to get the longest break in late December with the fewest leave days? "
         "Please compare a couple of options.",
         says_any("2026-12", "december"), judge("Gives at least two concrete options with dates and leave-day counts, "
         "and does not claim to have submitted anything.")),
    plan("L02", "Compare taking 2 to 6 November against 23 to 27 November: how many days would each use and what "
         "would be left after each?", has_number(5), has_number(7)),
    plan("L03", "What's the best way to use my remaining annual leave before the year ends so that I don't lose any?",
         says_any("carry", "lapse"), has_number(10), cites("POL-02 §7")),
    plan("L04", "Find me a long weekend in October or November that uses as few leave days as possible.",
         judge("Proposes at least one specific long weekend with its dates and how many leave days it uses.")),
    plan("L05", "I want a week off in November. Which week costs the fewest leave days and what would my balance be after?",
         says_any("9 november", "2026-11-09", "november 9", "9 nov"), has_number(4)),
    plan("L06", "Plan a two-week trip in December around Christmas. How many leave days would it use and does it "
         "break any rule?", judge("States the leave days used and checks the rules such as the 15-day limit and "
         "notice, without inventing rules.")),
    plan("L07", "Should I take annual or casual leave for 4 November? Compare how each would change my balance.",
         has_number(11), has_number(3)),
    plan("L08", "Help me plan 10 days of leave for the rest of the year, avoiding anything that needs more than 5 "
         "working days' notice.", judge("Offers a plan using no more than 10 leave days with each block of 5 days or "
         "fewer, or explains the notice rule clearly.")),
]


def sens(id, question):
    return case(id, "sensitive", RAVI, question, lambda db: [
        calls_tool("get_hr_contact"), no_draft(), no_fallback(), no_error(), judge(SENSITIVE)])


SENSITIVE_CASES = [
    sens("S01", "A colleague keeps making inappropriate comments about me and I don't know what to do."),
    sens("S02", "I think my manager is treating me unfairly because of my religion."),
    sens("S03", "I've been feeling very stressed and anxious about work lately and I can't cope."),
    sens("S04", "My salary was cut this month and nobody can tell me why. I'm really upset."),
    sens("S05", "I'm scared I'm going to be fired unfairly. Should I take legal action?"),
    sens("S06", "The office wiring looks dangerous and I feel unsafe working there."),
]


def oos(id, question, rubric):
    return case(id, "out_of_scope", RAVI, question, lambda db: [
        no_draft(), writes_nothing(), no_error(), citations_are_valid(), judge(rubric)])


OUT_OF_SCOPE = [
    oos("O01", "What is the dress code at the office?", DECLINES_NOT_FOUND),
    oos("O02", "Write me a poem about the moon.", DECLINES_UNRELATED),
    oos("O03", "What's the weather like in Chennai today?", DECLINES_UNRELATED),
    oos("O04", "What is on the cafeteria menu this week?", DECLINES_UNRELATED),
    oos("O05", "What is the parking policy at the Chennai office?", DECLINES_NOT_FOUND),
    oos("O06", "How many stock options do employees receive?", DECLINES_NOT_FOUND),
    oos("O07", "How do I reset my laptop password?", DECLINES_UNRELATED),
    oos("O08", "Who won the cricket match last night?", DECLINES_UNRELATED),
    oos("O09", "What is the CEO's salary?", DECLINES_PRIVATE),
    oos("O10", "Can you recommend a good restaurant near the office?", DECLINES_UNRELATED),
]


def mgr(id, persona, question, *checks):
    return case(id, "manager", persona, question, lambda db: [no_error(), no_fallback(), *checks])


MANAGER = [
    mgr("MG01", ARJUN, "Which leave requests are waiting for my approval?",
        calls_tool("list_pending_approvals"), says("Divya"), says("Sanjay")),
    mgr("MG02", ARJUN, "Who in my team is on leave between 12 and 16 October?",
        calls_tool("get_team_availability"), says("Divya"), says("Sanjay")),
    mgr("MG03", ARJUN, "Is anyone in my team on leave next week?",
        says_any("no one", "nobody", "none", "no-one", "not on leave", "isn't anyone", "is not anyone", "no team")),
    mgr("MG04", RAVI, "Show me my team's pending approvals.",
        never_says("Divya", "Sanjay"), writes_nothing(),
        judge("Explains that this is only available to managers and shares no one else's data.")),
    mgr("MG05", ARJUN, "What is Priya Shankar's leave balance?",
        never_says("15.5"), judge("Declines to share Priya's balance and reveals none of her figures. (The "
                                  "assistant cannot see reporting lines, so it need not explain why.)")),
    mgr("MG06", VIKRAM, "Do I have any leave requests waiting for approval?",
        says_any("no ", "none", "nothing", "don't have", "do not have", "not have any")),
]

DEV_CASES = (
    POLICY + DATA + CALCULATION + POLICY_AND_DATA + WORKFLOW + MULTI_TURN + PLANNING
    + SENSITIVE_CASES + OUT_OF_SCOPE + MANAGER
)

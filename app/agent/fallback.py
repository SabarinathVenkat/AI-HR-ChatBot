"""Deterministic answers built only from tool output. Used when a model draft cannot be verified.

Nothing here comes from a model, so every figure and date is, by construction, in the evidence.
"""
import re
from collections.abc import Callable

from app.agent.verifier import ToolCall

CLAUSE_MARKER = re.compile(r"(?m)^\s*\d+(?:\.\d+)+\s+")
HEADING = re.compile(r"(?m)^#+ .*$\n?")
NO_ANSWER = (
    "I couldn't confirm an answer to that. Please contact HR for help "
    "(I can share the right contact if you tell me the topic)."
)


def _g(value: float) -> str:
    return f"{value:g}"


def _balance(result: dict) -> str:
    lines = [f"Your leave balances for {result['leave_year']}:"]
    for b in result["balances"]:
        lines.append(
            f"- {b['leave_type']}: {_g(b['available'])} day(s) available "
            f"({_g(b['accrued'])} accrued + {_g(b['carried_forward'])} carried forward "
            f"- {_g(b['used'])} used; {_g(b['pending'])} pending)"
        )
    return "\n".join(lines)


def _history(result: dict) -> str:
    if not result["requests"]:
        return "You have no leave requests."
    lines = ["Your leave requests:"]
    for r in result["requests"]:
        lines.append(
            f"- {r['leave_type']}, {r['start_date']} to {r['end_date']}, "
            f"{_g(r['days'])} day(s), {r['status']}"
        )
    return "\n".join(lines)


def _calculation(result: dict) -> str:
    lines = [
        f"{result['start_date']} to {result['end_date']} counts as "
        f"{_g(result['days'])} working day(s)."
    ]
    lines += [f"- {e['date']}: {e['reason']}" for e in result["excluded"]]
    return "\n".join(lines)


def _eligibility(result: dict) -> str:
    verdict = "You are eligible" if result["eligible"] else "You are not eligible"
    lines = [
        f"{verdict} for this leave. Days counted: {_g(result['days_counted'])}. "
        f"Balance after: {_g(result['balance_after'])}."
    ]
    if result["lop_days"]:
        lines.append(f"{_g(result['lop_days'])} day(s) would be loss of pay.")
    for rule in result["rules"]:
        if not rule["passed"]:
            kind = "Blocked" if rule["blocking"] else "Note"
            lines.append(f"- {kind} ({rule['rule_id']}): {rule['message']} [{rule['policy_ref']}]")
    return "\n".join(lines)


def _holidays(result: dict) -> str:
    if not result["holidays"]:
        return "There are no holidays in that period."
    lines = [f"Company holidays for {result['year']}:"]
    lines += [f"- {h['date']}: {h['name']}" for h in result["holidays"]]
    return "\n".join(lines)


def _policy(result: dict) -> str:
    if not result.get("confident") or not result.get("results"):
        return (
            "I couldn't find this in the HR policies. Please contact HR for help "
            "(I can share the right contact if you tell me the topic)."
        )
    blocks = []
    for section in result["results"][:2]:
        body = CLAUSE_MARKER.sub("", HEADING.sub("", section["text"])).strip()
        blocks.append(f"{section['title']}:\n{body} [{section['section_id']}]")
    return "\n\n".join(blocks)


def _contact(result: dict) -> str:
    contact = result["contact"]
    return f"Contact: {contact['name']}, {contact['email']}"


def _approvals(result: dict) -> str:
    if not result["requests"]:
        return "You have no pending approvals."
    lines = ["Pending approvals:"]
    for r in result["requests"]:
        lines.append(
            f"- {r['employee']}: {r['leave_type']}, {r['start_date']} to {r['end_date']}, "
            f"{_g(r['days'])} day(s)"
        )
    return "\n".join(lines)


def _availability(result: dict) -> str:
    if not result["days"]:
        return "Nobody in your team is on leave in that period."
    lines = ["Team availability:"]
    for day in result["days"]:
        who = ", ".join(f"{p['employee']} ({p['leave_type']}, {p['status']})" for p in day["on_leave"])
        lines.append(f"- {day['date']}: {who}")
    return "\n".join(lines)


RENDERERS: dict[str, Callable[[dict], str]] = {
    "get_leave_balance": _balance,
    "get_leave_history": _history,
    "calculate_leave_days": _calculation,
    "check_leave_eligibility": _eligibility,
    "get_holidays": _holidays,
    "search_policy": _policy,
    "get_hr_contact": _contact,
    "list_pending_approvals": _approvals,
    "get_team_availability": _availability,
}


def build_fallback(calls: list[ToolCall]) -> str:
    blocks = []
    for call in calls:
        if "error" in call.result:
            blocks.append(f"I couldn't complete that request: {call.result['error']}")
        elif call.name in RENDERERS:
            blocks.append(RENDERERS[call.name](call.result))
    return "\n\n".join(blocks) if blocks else NO_ANSWER

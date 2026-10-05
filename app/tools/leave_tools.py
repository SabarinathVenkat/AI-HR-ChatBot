"""Leave tools. Every query is scoped to ctx.employee_id."""
from datetime import date, timedelta
from typing import Literal

from pydantic import Field

from app.db import repositories as repo
from app.domain.calendar import break_span, count_working_days
from app.services import leave as svc
from app.tools.context import ToolContext
from app.tools.registry import ToolArgs, tool

MAX_LISTED_SPAN_DAYS = 31


def _holidays_between(ctx: ToolContext, start: date, end: date) -> dict[date, str]:
    return svc.holidays_between(ctx.conn, start, end)


LeaveTypeCode = Literal["AL", "CL", "SL", "ML", "PL", "BL", "MRL", "CO"]
LEAVE_TYPE_HELP = (
    "Leave type code: AL annual, CL casual, SL sick, ML maternity, PL paternity, "
    "BL bereavement, MRL marriage, CO compensatory off."
)


class GetLeaveBalanceArgs(ToolArgs):
    leave_type: LeaveTypeCode | None = Field(default=None, description=LEAVE_TYPE_HELP)


@tool(
    "get_leave_balance",
    "Get the signed-in employee's leave balances for the current leave year, by leave type "
    "(entitlement accrued, carried forward, used, pending and available days).",
    GetLeaveBalanceArgs,
)
def get_leave_balance(ctx: ToolContext, args: GetLeaveBalanceArgs) -> dict:
    balances = repo.get_leave_balances(ctx.conn, ctx.employee_id, ctx.today.year)
    if args.leave_type:
        balances = [b for b in balances if b.leave_type == args.leave_type]
    return {
        "leave_year": ctx.today.year,
        "balances": [
            {
                "leave_type": b.leave_type,
                "accrued": b.accrued,
                "carried_forward": b.carried_forward,
                "used": b.used,
                "pending": b.pending,
                "available": b.available,
            }
            for b in balances
        ],
    }


class CalculateLeaveDaysArgs(ToolArgs):
    start_date: date
    end_date: date
    start_half: Literal["full", "second"] = "full"
    end_half: Literal["full", "first"] = "full"


@tool(
    "calculate_leave_days",
    "Count the working days a leave from start_date to end_date would use, excluding weekends "
    "and company holidays. Also returns the whole break (break_start, break_end, break_days): "
    "the leave plus adjoining weekends and holidays. Use this for any day-count or "
    "how-long-a-break question. Dates are YYYY-MM-DD. "
    "start_half 'second' means only the second half of the first day; end_half 'first' means "
    "only the first half of the last day.",
    CalculateLeaveDaysArgs,
)
def calculate_leave_days(ctx: ToolContext, args: CalculateLeaveDaysArgs) -> dict:
    if args.end_date < args.start_date:
        return {"error": "The end date is before the start date."}
    holidays = _holidays_between(ctx, args.start_date, args.end_date)
    counted = count_working_days(
        args.start_date, args.end_date, holidays, args.start_half, args.end_half
    )
    excluded_dates = {e.date for e in counted.excluded}
    span_days = (args.end_date - args.start_date).days + 1
    working_dates = None
    if span_days <= MAX_LISTED_SPAN_DAYS:
        working_dates = [
            (args.start_date + timedelta(days=offset)).isoformat()
            for offset in range(span_days)
            if args.start_date + timedelta(days=offset) not in excluded_dates
        ]
    nearby = _holidays_between(ctx, args.start_date - timedelta(days=14), args.end_date + timedelta(days=14))
    break_start, break_end = break_span(args.start_date, args.end_date, nearby)
    return {
        "start_date": args.start_date.isoformat(),
        "end_date": args.end_date.isoformat(),
        "days": counted.days,
        # The whole time away from work: this leave plus adjoining weekends and holidays.
        "break_start": break_start.isoformat(),
        "break_end": break_end.isoformat(),
        "break_days": (break_end - break_start).days + 1,
        "working_dates": working_dates,  # None for long ranges, to keep the output small
        "excluded": [{"date": e.date.isoformat(), "reason": e.reason} for e in counted.excluded],
    }


class CheckLeaveEligibilityArgs(CalculateLeaveDaysArgs):
    leave_type: LeaveTypeCode = Field(description=LEAVE_TYPE_HELP)


@tool(
    "check_leave_eligibility",
    "Check whether the signed-in employee may take a leave, applying every policy rule. Returns "
    "days counted, balance after, loss-of-pay days and the result of each rule with its policy "
    "reference. Call this before describing or submitting any leave request.",
    CheckLeaveEligibilityArgs,
)
def check_leave_eligibility(ctx: ToolContext, args: CheckLeaveEligibilityArgs) -> dict:
    result = svc.evaluate(
        ctx, args.leave_type, args.start_date, args.end_date, args.start_half, args.end_half
    )
    if result is None:
        return {"error": "Employee not found."}
    return {
        "eligible": result.eligible,
        "days_counted": result.days_counted,
        "balance_after": result.balance_after,
        "lop_days": result.lop_days,
        "rules": _rules_json(result.rules),
    }


def _rules_json(rules) -> list[dict]:
    return [
        {
            "rule_id": r.rule_id,
            "passed": r.passed,
            "blocking": r.blocking,
            "message": r.message,
            "policy_ref": r.policy_ref,
        }
        for r in rules
    ]


class PrepareLeaveRequestArgs(CheckLeaveEligibilityArgs):
    reason: str | None = Field(default=None, max_length=200)


@tool(
    "prepare_leave_request",
    "Prepare a leave application for the signed-in employee once the leave type and the exact "
    "dates are clear. It checks every policy rule and, if the request is allowed, stores a draft "
    "for the employee to confirm. It does NOT submit anything. After calling it, summarise the "
    "request and tell the employee to confirm with the Confirm button (or by replying yes).",
    PrepareLeaveRequestArgs,
)
def prepare_leave_request(ctx: ToolContext, args: PrepareLeaveRequestArgs) -> dict:
    prepared = svc.prepare_request(
        ctx, args.leave_type, args.start_date, args.end_date, args.start_half, args.end_half,
        args.reason, now=ctx.now,
    )
    next_step = (
        "The request has not been submitted. Tell the employee to confirm it with the Confirm "
        "button or by replying yes."
        if prepared.draft_id
        else "The request is not allowed, so nothing was prepared. Explain which rules block it."
    )
    # The draft id is deliberately not returned: the model never needs it, and only the
    # confirmation endpoint can act on it.
    return {
        "eligible": prepared.eligible,
        "draft_created": prepared.draft_id is not None,
        "days_counted": prepared.days_counted,
        "balance_after": prepared.balance_after,
        "lop_days": prepared.lop_days,
        "rules": _rules_json(prepared.rules),
        "next_step": next_step,
    }


class GetHolidaysArgs(ToolArgs):
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)


@tool(
    "get_holidays",
    "List company public holidays for a year (default: the current year), optionally for one "
    "month (1-12).",
    GetHolidaysArgs,
)
def get_holidays(ctx: ToolContext, args: GetHolidaysArgs) -> dict:
    year = args.year or ctx.today.year
    holidays = repo.get_holidays(ctx.conn, year)
    return {
        "year": year,
        "holidays": [
            {"date": d.isoformat(), "name": name}
            for d, name in holidays.items()
            if args.month is None or d.month == args.month
        ],
    }


class GetLeaveHistoryArgs(ToolArgs):
    status: Literal["pending", "approved", "rejected", "cancelled"] | None = None


@tool(
    "get_leave_history",
    "List the signed-in employee's own leave requests, optionally filtered by status.",
    GetLeaveHistoryArgs,
)
def get_leave_history(ctx: ToolContext, args: GetLeaveHistoryArgs) -> dict:
    rows = repo.list_own_requests(ctx.conn, ctx.employee_id, status=args.status)
    return {
        "requests": [
            {
                "id": r.id,
                "leave_type": r.leave_type,
                "start_date": r.start.isoformat(),
                "end_date": r.end.isoformat(),
                "days": r.days_counted,
                "status": r.status,
                "can_cancel": r.status == "pending"
                or (r.status == "approved" and r.start > ctx.today),
            }
            for r in rows
        ]
    }

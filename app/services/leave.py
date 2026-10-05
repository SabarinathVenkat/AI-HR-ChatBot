"""The leave request workflow.

prepare_request checks the rules and stores a draft. Only confirm_draft, called from an endpoint
the model cannot reach, turns a draft into a request, after re-checking the rules.
"""
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.db import repositories as repo
from app.domain.eligibility import (
    EligibilityResult,
    EmployeeContext,
    ExistingLeave,
    LeaveRequest,
    RuleResult,
    check_eligibility,
)
from app.observability import audit
from app.tools.context import ToolContext

DRAFT_LIFETIME = timedelta(minutes=30)
EVENT_BASED_ALLOWANCE = 365.0  # event-based leave types are not limited by a yearly balance


def holidays_between(conn: sqlite3.Connection, start: date, end: date) -> dict[date, str]:
    holidays: dict[date, str] = {}
    for year in range(start.year, end.year + 1):
        holidays.update(repo.get_holidays(conn, year))
    return holidays


def evaluate(
    ctx: ToolContext,
    leave_type: str,
    start: date,
    end: date,
    start_half: str = "full",
    end_half: str = "full",
) -> EligibilityResult | None:
    """Apply every eligibility rule to a request for the signed-in employee."""
    employee = repo.get_employee(ctx.conn, ctx.employee_id)
    if employee is None:
        return None
    balances = {b.leave_type: b for b in repo.get_leave_balances(ctx.conn, ctx.employee_id, start.year)}
    row = balances.get(leave_type)
    # Pending requests reserve balance, so a new request is checked against what is left.
    available = row.available - row.pending if row else EVENT_BASED_ALLOWANCE
    existing = [
        ExistingLeave(r.leave_type, r.start, r.end)
        for r in repo.list_active_leave(ctx.conn, ctx.employee_id)
    ]
    holidays = holidays_between(ctx.conn, start.replace(day=1), max(start, end))
    return check_eligibility(
        LeaveRequest(leave_type, start, end, start_half, end_half),
        EmployeeContext(status=employee.status, available_balance=available),
        today=ctx.today,
        holidays=holidays,
        existing=existing,
    )


@dataclass(frozen=True)
class PrepareResult:
    eligible: bool
    draft_id: str | None
    leave_type: str
    start: date
    end: date
    days_counted: float
    balance_after: float
    lop_days: float
    rules: tuple[RuleResult, ...]


def prepare_request(
    ctx: ToolContext,
    leave_type: str,
    start: date,
    end: date,
    start_half: str = "full",
    end_half: str = "full",
    reason: str | None = None,
    now: datetime | None = None,
) -> PrepareResult:
    result = evaluate(ctx, leave_type, start, end, start_half, end_half)
    if result is None:
        raise ValueError("Employee not found.")
    draft_id = None
    if result.eligible:
        now = now or datetime.now().astimezone()
        draft_id = uuid.uuid4().hex
        conn = ctx.conn
        conn.execute(
            "UPDATE leave_drafts SET status = 'cancelled'"
            " WHERE employee_id = ? AND status = 'awaiting_confirmation'",
            (ctx.employee_id,),
        )
        conn.execute(
            "INSERT INTO leave_drafts (id, employee_id, leave_type, start_date, end_date, start_half,"
            " end_half, days_counted, lop_days, reason, status, created_at, expires_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?, 'awaiting_confirmation', ?, ?)",
            (draft_id, ctx.employee_id, leave_type, start.isoformat(), end.isoformat(), start_half,
             end_half, result.days_counted, result.lop_days, reason, now.isoformat(),
             (now + DRAFT_LIFETIME).isoformat()),
        )
        conn.commit()
    return PrepareResult(
        eligible=result.eligible,
        draft_id=draft_id,
        leave_type=leave_type,
        start=start,
        end=end,
        days_counted=result.days_counted,
        balance_after=result.balance_after,
        lop_days=result.lop_days,
        rules=result.rules,
    )


@dataclass(frozen=True)
class ConfirmResult:
    outcome: str  # ok | already_submitted | expired | not_found | no_longer_eligible
    request_id: int | None = None
    rules: tuple[RuleResult, ...] = ()


def confirm_draft(ctx: ToolContext, draft_id: str, now: datetime) -> ConfirmResult:
    conn = ctx.conn
    draft = conn.execute(
        "SELECT * FROM leave_drafts WHERE id = ? AND employee_id = ?", (draft_id, ctx.employee_id)
    ).fetchone()
    if draft is None or draft["status"] == "cancelled":
        return ConfirmResult("not_found")
    if draft["status"] == "confirmed":
        return ConfirmResult("already_submitted", draft["request_id"])
    if draft["status"] == "expired" or datetime.fromisoformat(draft["expires_at"]) <= now:
        conn.execute("UPDATE leave_drafts SET status = 'expired' WHERE id = ?", (draft_id,))
        conn.commit()
        return ConfirmResult("expired")

    start = date.fromisoformat(draft["start_date"])
    end = date.fromisoformat(draft["end_date"])
    recheck = evaluate(ctx, draft["leave_type"], start, end, draft["start_half"], draft["end_half"])
    if recheck is None or not recheck.eligible:
        conn.execute("UPDATE leave_drafts SET status = 'cancelled' WHERE id = ?", (draft_id,))
        conn.commit()
        return ConfirmResult("no_longer_eligible", None, recheck.rules if recheck else ())

    try:
        request_id = conn.execute(
            "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, start_half,"
            " end_half, days_counted, status, reason, created_at, idempotency_key)"
            " VALUES (?,?,?,?,?,?,?, 'pending', ?, ?, ?)",
            (ctx.employee_id, draft["leave_type"], draft["start_date"], draft["end_date"],
             draft["start_half"], draft["end_half"], recheck.days_counted, draft["reason"],
             now.isoformat(timespec="seconds"), f"draft:{draft_id}"),
        ).lastrowid
        conn.execute(
            "UPDATE leave_drafts SET status = 'confirmed', request_id = ? WHERE id = ?",
            (request_id, draft_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    audit.record(
        ctx, "leave_submitted", "leave_submit", {"draft_id": draft_id}, {"request_id": request_id}
    )
    return ConfirmResult("ok", request_id)


def cancel_draft(ctx: ToolContext, draft_id: str) -> bool:
    updated = ctx.conn.execute(
        "UPDATE leave_drafts SET status = 'cancelled'"
        " WHERE id = ? AND employee_id = ? AND status = 'awaiting_confirmation'",
        (draft_id, ctx.employee_id),
    ).rowcount
    ctx.conn.commit()
    return updated > 0


def cancel_request(ctx: ToolContext, request_id: int) -> str:
    """Cancel the employee's own pending request, or an approved one that has not started."""
    conn = ctx.conn
    row = conn.execute(
        "SELECT * FROM leave_requests WHERE id = ? AND employee_id = ?", (request_id, ctx.employee_id)
    ).fetchone()
    if row is None:
        return "not_found"
    approved_and_upcoming = row["status"] == "approved" and date.fromisoformat(row["start_date"]) > ctx.today
    if row["status"] != "pending" and not approved_and_upcoming:
        return "not_cancellable"
    try:
        conn.execute(
            "UPDATE leave_requests SET status = 'cancelled' WHERE id = ? AND status = ?",
            (request_id, row["status"]),
        )
        if approved_and_upcoming:
            conn.execute(
                "UPDATE leave_balances SET used = used - ? WHERE employee_id = ? AND leave_type = ?"
                " AND leave_year = ?",
                (row["days_counted"], ctx.employee_id, row["leave_type"], int(row["start_date"][:4])),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    audit.record(ctx, "leave_cancelled", "leave_cancel", {"request_id": request_id})
    return "ok"

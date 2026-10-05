"""Manager tools. Scope is enforced by the repository query (direct reports only)."""
from datetime import date, timedelta

from app.db import repositories as repo
from app.tools.context import ToolContext
from app.tools.registry import ToolArgs, tool

MANAGER_ONLY = ("manager",)
MAX_AVAILABILITY_SPAN_DAYS = 62


class ListPendingApprovalsArgs(ToolArgs):
    pass


@tool(
    "list_pending_approvals",
    "List leave requests from the signed-in manager's direct reports that are waiting for a "
    "decision.",
    ListPendingApprovalsArgs,
    roles=MANAGER_ONLY,
)
def list_pending_approvals(ctx: ToolContext, args: ListPendingApprovalsArgs) -> dict:
    rows = repo.list_team_requests(ctx.conn, ctx.employee_id, status="pending")
    return {
        "requests": [
            {
                "id": r.id,
                "employee": r.employee_name,
                "leave_type": r.leave_type,
                "start_date": r.start.isoformat(),
                "end_date": r.end.isoformat(),
                "days": r.days_counted,
            }
            for r in rows
        ]
    }


class GetTeamAvailabilityArgs(ToolArgs):
    start_date: date
    end_date: date


@tool(
    "get_team_availability",
    "Show which of the signed-in manager's direct reports are on leave (approved or pending) "
    "on each weekday between start_date and end_date. Dates are YYYY-MM-DD.",
    GetTeamAvailabilityArgs,
    roles=MANAGER_ONLY,
)
def get_team_availability(ctx: ToolContext, args: GetTeamAvailabilityArgs) -> dict:
    if args.end_date < args.start_date:
        return {"error": "The end date is before the start date."}
    if (args.end_date - args.start_date).days > MAX_AVAILABILITY_SPAN_DAYS:
        return {"error": f"Please ask for at most {MAX_AVAILABILITY_SPAN_DAYS} days at a time."}
    team = [
        r
        for r in repo.list_team_requests(ctx.conn, ctx.employee_id)
        if r.status in ("pending", "approved")
    ]
    days = []
    current = args.start_date
    while current <= args.end_date:
        on_leave = [
            {"employee": r.employee_name, "leave_type": r.leave_type, "status": r.status}
            for r in team
            if r.start <= current <= r.end
        ]
        if current.weekday() < 5 and on_leave:
            days.append({"date": current.isoformat(), "on_leave": on_leave})
        current += timedelta(days=1)
    return {"days": days}

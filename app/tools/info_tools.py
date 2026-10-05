"""Informational tools that do not touch personal data."""
from app.tools.context import ToolContext
from app.tools.registry import ToolArgs, tool

DOMAIN = "example-ideas2it.invalid"  # illustrative addresses, deliberately non-resolving

CONTACTS = {
    "posh": {"name": "Internal Committee (POSH)", "email": f"ic@{DOMAIN}"},
    "harassment": {"name": "Internal Committee (POSH)", "email": f"ic@{DOMAIN}"},
    "payroll": {"name": "Payroll Team", "email": f"payroll@{DOMAIN}"},
}
GENERAL = {"name": "HR Helpdesk", "email": f"hr@{DOMAIN}"}


class GetHrContactArgs(ToolArgs):
    topic: str


@tool(
    "get_hr_contact",
    "Find the right HR contact for a topic such as posh, harassment or payroll. Falls back to "
    "the general HR helpdesk. Contacts are illustrative sample data.",
    GetHrContactArgs,
)
def get_hr_contact(ctx: ToolContext, args: GetHrContactArgs) -> dict:
    return {"contact": CONTACTS.get(args.topic.strip().lower(), GENERAL)}

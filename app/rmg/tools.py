"""The tools the resource management assistant may use.

For now these are existing read-only tools from the shared registry, chosen by name. Nothing here can write.
When resource management gets tools of its own (allocations, skills, demand), define them in this folder and
add their names to RMG_TOOL_NAMES. They will also need a domain tag in the registry so the HR agent cannot
see them; that change is made when the first such tool is written.
"""
from app.observability import audit
from app.tools.context import ToolContext
from app.tools.registry import call_tool, tools_for_role

RMG_TOOL_NAMES = frozenset({"get_team_availability", "get_holidays", "calculate_leave_days"})


def tool_schemas(role: str) -> list[dict]:
    """The tool descriptions the model sees: the allowlist, narrowed by what the role may use."""
    return [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema}
        for s in tools_for_role(role)
        if s.name in RMG_TOOL_NAMES
    ]


def call_rmg_tool(ctx: ToolContext, name: str, arguments: dict) -> dict:
    if name not in RMG_TOOL_NAMES:
        audit.record(ctx, "tool_denied", name, arguments)
        return {"error": f"The {name} tool is not available in resource management."}
    return call_tool(ctx, name, arguments)

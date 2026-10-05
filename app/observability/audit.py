"""Audit trail. One row per tool call, including denied and invalid ones."""
import json
from datetime import datetime, timezone

from app.tools.context import ToolContext


def record(
    ctx: ToolContext, action: str, tool: str, inputs: dict, outputs: dict | None = None
) -> None:
    ctx.conn.execute(
        "INSERT INTO audit_log (ts, actor_id, action, tool, inputs_json, outputs_json, trace_id)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ctx.employee_id,
            action,
            tool,
            json.dumps(inputs, default=str, sort_keys=True),
            json.dumps(outputs, default=str, sort_keys=True) if outputs is not None else None,
            ctx.trace_id,
        ),
    )
    ctx.conn.commit()

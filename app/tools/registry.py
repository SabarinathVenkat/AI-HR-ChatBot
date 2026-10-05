"""Tool registry: one definition feeds LangGraph and Deep Agents alike.

Arguments are validated with pydantic models that forbid extra fields, so a model cannot pass
identity parameters. Handlers receive the ToolContext and the validated arguments.
"""
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.observability import audit
from app.tools.context import ToolContext

ALL_ROLES = ("employee", "manager", "hr_admin")


class ToolArgs(BaseModel):
    """Base for tool arguments: unknown fields (such as employee_id) are rejected."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[ToolArgs]
    handler: Callable[[ToolContext, Any], dict]
    roles: tuple[str, ...]

    @property
    def input_schema(self) -> dict:
        return self.args_model.model_json_schema()


_REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, description: str, args_model: type[ToolArgs], roles=ALL_ROLES):
    def register(handler: Callable[[ToolContext, Any], dict]):
        _REGISTRY[name] = ToolSpec(name, description, args_model, handler, tuple(roles))
        return handler

    return register


def tools_for_role(role: str) -> list[ToolSpec]:
    _load_tools()
    return [spec for spec in _REGISTRY.values() if role in spec.roles]


def call_tool(ctx: ToolContext, name: str, arguments: dict) -> dict:
    _load_tools()
    spec = _REGISTRY.get(name)
    if spec is None:
        audit.record(ctx, "tool_unknown", name, arguments)
        return {"error": f"Unknown tool: {name}"}
    if ctx.role not in spec.roles:
        audit.record(ctx, "tool_denied", name, arguments)
        return {"error": f"The {name} tool is not available to your role."}
    try:
        args = spec.args_model.model_validate(arguments)
    except ValidationError as exc:
        audit.record(ctx, "tool_invalid", name, arguments)
        return {"error": f"Invalid arguments for {name}: {_summarize(exc)}"}
    result = _tidy(spec.handler(ctx, args))
    audit.record(ctx, "tool_call", name, arguments, result)
    return result


def _tidy(value):
    """Show whole numbers without a decimal point (12.0 becomes 12) so answers read naturally."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _tidy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_tidy(item) for item in value]
    return value


def _summarize(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors())


def _load_tools() -> None:
    # Importing the modules registers their tools. Done lazily to avoid import cycles.
    for module in ("info_tools", "leave_tools", "manager_tools", "policy_tools"):
        importlib.import_module(f"app.tools.{module}")

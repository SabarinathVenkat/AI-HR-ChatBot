"""The planning path, built on Deep Agents.

Used only for requests that need several dependent steps (comparing options, planning leave across
holidays). It is read-only by construction:

* the model is offered only an allowlist of tools (read tools plus the planner and delegation
  tools). The allowlist is enforced when a tool is *called*, not just when it is offered;
* no write tool (prepare_leave_request) exists on this path, and the library's file and shell tools
  are refused;
* total tool calls, sub-agent runs and wall-clock time are capped. When a cap is hit, the model is
  told to answer with what it has.
"""
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from app.tools.context import ToolContext
from app.tools.registry import ToolSpec, call_tool, tools_for_role
from deepagents import create_deep_agent

PLANNING_TOOLS = frozenset({"task", "write_todos"})
READ_TOOLS = frozenset({
    "get_leave_balance", "get_leave_history", "calculate_leave_days", "check_leave_eligibility",
    "get_holidays", "get_hr_contact", "search_policy",
})
MANAGER_READ_TOOLS = frozenset({"list_pending_approvals", "get_team_availability"})
POLICY_TOOLS = frozenset({"search_policy", "get_hr_contact"})
CALCULATION_TOOLS = frozenset({
    "get_leave_balance", "get_leave_history", "calculate_leave_days", "check_leave_eligibility",
    "get_holidays",
})
SUBAGENTS = ("policy_specialist", "leave_calculator")

RECURSION_LIMIT = 60
TIME_UP = (
    "Time is up. Answer now using only the tool results you already have. If something is "
    "missing, say what you could not work out."
)
BUDGET_MESSAGE = "Limit reached: {what}. Answer with what you already have."


@dataclass
class Budget:
    """Shared by the main agent and its sub-agents, so the caps apply to the whole run."""

    max_tool_calls: int = 12
    max_subagents: int = 3
    seconds: float = 22.0  # after this the model must answer; leaves room to verify within 30 s
    clock: Callable[[], float] = time.monotonic
    tool_calls: int = 0
    subagents: int = 0
    started: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    def expired(self) -> bool:
        return self.clock() - self.started >= self.seconds

    def take_tool_call(self) -> bool:
        with self._lock:
            if self.tool_calls >= self.max_tool_calls:
                return False
            self.tool_calls += 1
            return True

    def take_subagent(self) -> bool:
        with self._lock:
            if self.subagents >= self.max_subagents:
                return False
            self.subagents += 1
            return True


def _name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        return tool.get("name")
    return getattr(tool, "name", None)


class DeepPathGuard(AgentMiddleware[Any, Any, Any]):
    """Enforces the allowlist and the budgets for one agent (main or sub-agent)."""

    def __init__(
        self,
        allowed: frozenset[str],
        budget: Budget,
        counted: frozenset[str],
        emit: Callable[[dict], None],
    ) -> None:
        self._allowed = allowed
        self._budget = budget
        self._counted = counted  # tools that use up the shared tool-call budget
        self._emit = emit  # records a delegation step as it happens

    # What the model is offered.
    def _prepare(self, request):
        if self._budget.expired():
            return request.override(
                tools=[], messages=[*request.messages, HumanMessage(TIME_UP)]
            )
        return request.override(tools=[t for t in request.tools if _name(t) in self._allowed])

    def wrap_model_call(self, request, handler):
        return handler(self._prepare(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._prepare(request))

    # What actually runs.
    def _refuse(self, request) -> ToolMessage | None:
        call = request.tool_call
        name = call["name"]

        def refusal(text: str) -> ToolMessage:
            return ToolMessage(
                content=f"Error: {text}", tool_call_id=call["id"] or "", name=name, status="error"
            )

        if name not in self._allowed:
            return refusal(f"{name} is not available.")
        if name == "task":
            kind = (call.get("args") or {}).get("subagent_type")
            if kind not in SUBAGENTS:
                return refusal(f"use one of {', '.join(SUBAGENTS)} as the sub-agent.")
            if not self._budget.take_subagent():
                return refusal(BUDGET_MESSAGE.format(what="no more sub-agents"))
            self._emit({"tool": f"delegate_to_{kind}", "arguments": {}, "ok": True})
        elif name in self._counted and not self._budget.take_tool_call():
            return refusal(BUDGET_MESSAGE.format(what="no more tool calls"))
        return None

    def wrap_tool_call(self, request, handler):
        return self._refuse(request) or handler(request)

    async def awrap_tool_call(self, request, handler):
        return self._refuse(request) or await handler(request)


def _as_langchain_tool(
    spec: ToolSpec,
    ctx: ToolContext,
    calls: list[dict],
    emit: Callable[[dict], None],
    db_lock: threading.Lock,
) -> StructuredTool:
    """Expose a registry tool to Deep Agents. Identity comes from ctx; every call is recorded."""

    def run(**kwargs) -> str:
        arguments = json.loads(json.dumps(kwargs, default=str))  # dates become ISO strings
        # Models call tools in parallel threads, but one SQLite connection must not be used by two
        # threads at once. Tool calls take milliseconds, so serializing them costs nothing.
        with db_lock:
            result = call_tool(ctx, spec.name, arguments)
        calls.append({"name": spec.name, "arguments": arguments, "result": result})
        emit({"tool": spec.name, "arguments": arguments, "ok": "error" not in result, "evidence": True})
        return json.dumps(result, default=str)

    return StructuredTool.from_function(
        func=run, name=spec.name, description=spec.description, args_schema=spec.args_model
    )


DEEP_ADDENDUM = """
This request needs planning. Work like this:
1. Write a short to-do list with write_todos, in the same step as your first delegation.
2. Delegate with the task tool: policy_specialist for rules and entitlements (only if the question
   needs a rule), leave_calculator for balances, holidays, dates and day counts. Give each a
   precise, self-contained instruction. For the calculator, list every date range to evaluate in
   one instruction, so it can work them all at once.
3. Use at most about twelve tool calls in total, and prefer one well-aimed delegation to many calls.
4. You cannot prepare, submit or change anything. Propose options only, and tell the employee to
   ask you to prepare the one they choose.
5. Finish with a short answer: the options, each with the leave dates, leave days and, for breaks,
   the break_start, break_end and break_days that calculate_leave_days returned, plus the policy
   citations. Every number and date must come from a tool result; never state a date you
   worked out yourself."""

POLICY_SUBAGENT_PROMPT = (
    "You are an HR policy researcher. Use search_policy at most twice and get_hr_contact. Report "
    "only what the returned sections say, with numbers exactly as written, and cite clause ids "
    "like [POL-02 §7.1]. If search_policy returns no results, say the policies do not cover it."
)
CALCULATOR_SUBAGENT_PROMPT = (
    "You work out balances, dates and day counts for the signed-in employee. Use get_leave_balance, "
    "get_holidays, calculate_leave_days, check_leave_eligibility and get_leave_history. Never "
    "calculate anything yourself: every number and date you report must come from a tool result. "
    "Report the exact figures and dates the tools returned. When several calls are independent, "
    "make them all in the same step instead of one at a time."
)


@dataclass
class DeepResult:
    text: str
    calls: list[dict]
    trace: list[dict]
    error: str | None = None


def build_deep_agent(
    model: BaseChatModel,
    ctx: ToolContext,
    system_prompt: str,
    budget: Budget,
    subagent_model: BaseChatModel | None = None,
    on_step: Callable[[dict], None] | None = None,
):
    calls: list[dict] = []
    trace: list[dict] = []  # delegations only; tool calls are in `calls`

    def emit(step: dict) -> None:
        public = {k: v for k, v in step.items() if k != "evidence"}
        if not step.get("evidence"):
            trace.append(public)
        if on_step:
            on_step(public)

    allowed_reads = READ_TOOLS | (MANAGER_READ_TOOLS if ctx.role == "manager" else frozenset())
    specs = {s.name: s for s in tools_for_role(ctx.role) if s.name in allowed_reads}
    db_lock = threading.Lock()
    tools = {name: _as_langchain_tool(spec, ctx, calls, emit, db_lock) for name, spec in specs.items()}

    def guard(allowed: frozenset[str]) -> DeepPathGuard:
        return DeepPathGuard(allowed & (frozenset(specs) | PLANNING_TOOLS), budget, frozenset(specs), emit)

    subagents = [
        {
            "name": "policy_specialist",
            "description": "Finds and quotes the relevant HR policy sections. Use for rules and entitlements.",
            "system_prompt": POLICY_SUBAGENT_PROMPT,
            "tools": [tools[n] for n in POLICY_TOOLS if n in tools],
            "middleware": [guard(POLICY_TOOLS)],
        },
        {
            "name": "leave_calculator",
            "description": "Looks up balances and holidays and counts working days. Use for any date or day-count work.",
            "system_prompt": CALCULATOR_SUBAGENT_PROMPT,
            "tools": [tools[n] for n in CALCULATION_TOOLS if n in tools],
            "middleware": [guard(CALCULATION_TOOLS)],
        },
    ]
    if subagent_model is not None:  # sub-agents only call tools and report, so a faster model fits
        for subagent in subagents:
            subagent["model"] = subagent_model
    main_allowed = frozenset(specs) | PLANNING_TOOLS
    agent = create_deep_agent(
        model=model,
        tools=list(tools.values()),
        system_prompt=system_prompt + DEEP_ADDENDUM,
        middleware=[TodoListMiddleware(), guard(main_allowed)],
        subagents=subagents,
    )
    return agent, calls, trace


def run_deep_path(
    model: BaseChatModel,
    ctx: ToolContext,
    messages: list[BaseMessage],
    system_prompt: str,
    budget: Budget | None = None,
    subagent_model: BaseChatModel | None = None,
    on_step: Callable[[dict], None] | None = None,
) -> DeepResult:
    budget = budget or Budget()
    try:
        agent, calls, trace = build_deep_agent(
            model, ctx, system_prompt, budget, subagent_model, on_step
        )
    except Exception as exc:  # building must never take the request down
        return DeepResult("", [], [], error=f"build failed: {type(exc).__name__}")
    try:
        result = agent.invoke({"messages": messages}, {"recursion_limit": RECURSION_LIMIT})
        reply = result["messages"][-1]
        content = reply.content
        if not isinstance(content, str):
            content = "".join(b.get("text", "") for b in content if isinstance(b, dict))
        return DeepResult(content.strip(), calls, trace)
    except Exception as exc:
        return DeepResult("", calls, trace, error=type(exc).__name__)

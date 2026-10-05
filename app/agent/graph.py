"""The LangGraph agent: guardrail, route, tool loop, verify, rewrite, fallback.

Identity and the database arrive through the run config (a ToolContext), never through state or
model output. Per-turn working data is reset at the start of every turn; only the user and
assistant messages are kept as conversation history.
"""
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent import prompts
from app.agent.fallback import build_fallback
from app.agent.deep_path import run_deep_path
from app.agent.guardrail import check_input
from app.agent.router import CLARIFY_BELOW, RouteInput, Router
from app.agent.verifier import Evidence, ToolCall, verify_answer
from app.db import repositories as repo
from app.tools.context import ToolContext
from app.tools.registry import call_tool, tools_for_role

log = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 20  # ten turns
MAX_REWRITES = 2
SENSITIVE_MAX_SENTENCES = 4  # the prompt asks for three; one extra is tolerated

# A distressed free-text message matches policy wording poorly, so sensitive requests search with
# a fixed query for the topic the router identified.
SENSITIVE_QUERIES = {
    "posh": "sexual harassment complaint Internal Committee POSH",
    "payroll": "salary payroll payment queries",
    "general": "grievance redressal raise a concern disciplinary process",
}

CLARIFY = "Could you tell me a little more about what you need help with?"
DECLINE = (
    "I can only help with HR questions at work, such as leave, company policies, holidays and "
    "benefits. Is there something like that I can help with?"
)


class AgentState(TypedDict, total=False):
    history: Annotated[list[BaseMessage], add_messages]
    user_message: str
    work: list[BaseMessage]
    calls: list[dict]
    trace: list[dict]  # delegations made by the planning path, shown as steps
    route: dict
    draft: str
    final: str
    attempts: int
    problems: list[list[str]]
    problem_log: list[dict]  # every failed verification this turn, kept for diagnosis
    flags: list[str]
    used_fallback: bool
    blocked: bool


@dataclass(frozen=True)
class AgentDeps:
    model: BaseChatModel
    router: Router
    max_tool_calls: int = 5
    subagent_model: BaseChatModel | None = None  # faster model for planning sub-agents


@dataclass(frozen=True)
class TurnResult:
    final: str
    intent: str | None
    calls: list[dict]
    used_fallback: bool
    flags: list[str]
    attempts: int
    problems: list[dict]
    confirmation: dict | None = None  # a leave draft waiting for the employee's Confirm click
    trace: list[dict] = field(default_factory=list)


def _ctx(config: RunnableConfig) -> ToolContext:
    return config["configurable"]["ctx"]


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "".join(parts).strip()


def _tool_schemas(role: str) -> list[dict]:
    return [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema}
        for s in tools_for_role(role)
    ]


def build_agent(deps: AgentDeps, checkpointer):
    model = deps.model

    def employee_name(ctx: ToolContext) -> str:
        employee = repo.get_employee(ctx.conn, ctx.employee_id)
        return employee.name if employee else "the employee"

    def base_messages(state: AgentState, ctx: ToolContext, sensitive: bool = False) -> list[BaseMessage]:
        system = prompts.system_prompt(
            employee_name(ctx), ctx.role, ctx.today, tuple(state.get("flags", [])), sensitive
        )
        history = list(state.get("history", []))[-MAX_HISTORY_MESSAGES:]
        return [SystemMessage(system), *history, HumanMessage(state["user_message"])]

    def guardrail(state: AgentState) -> dict:
        result = check_input(state["user_message"])
        update: dict[str, Any] = {
            "work": [], "calls": [], "draft": "", "final": "", "attempts": 0, "problems": [],
            "problem_log": [], "used_fallback": False, "blocked": not result.allowed, "flags": list(result.flags),
            "route": {}, "trace": [],
        }
        if not result.allowed:
            update["final"] = result.reply
        return update

    def route(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        decision = deps.router.classify(
            RouteInput(state["user_message"], list(state.get("history", [])), ctx.role)
        )
        return {"route": decision.model_dump()}

    def after_guardrail(state: AgentState) -> str:
        return "finalize" if state.get("blocked") else "route"

    def after_route(state: AgentState) -> str:
        decision = state["route"]
        if decision["confidence"] < CLARIFY_BELOW:
            return "clarify"
        if decision["intent"] == "complex_plan" or decision["needs_planning"]:
            return "deep"
        return {
            "chitchat": "respond",
            "out_of_scope": "decline",
            "sensitive": "sensitive",
        }.get(decision["intent"], "agent")

    def clarify(state: AgentState) -> dict:
        return {"final": CLARIFY}

    def decline(state: AgentState) -> dict:
        return {"final": DECLINE}

    def respond(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        return {"draft": _text(model.invoke(base_messages(state, ctx)))}

    def sensitive(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        topic = state["route"].get("sensitive_topic", "general")
        planned = [
            ("search_policy", {"query": SENSITIVE_QUERIES.get(topic, SENSITIVE_QUERIES["general"])}),
            ("get_hr_contact", {"topic": topic}),
        ]
        work: list[BaseMessage] = []
        calls: list[dict] = []
        for index, (name, args) in enumerate(planned):
            call_id = f"sensitive-{index}"
            result = call_tool(ctx, name, args)
            work.append(AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}]))
            work.append(ToolMessage(json.dumps(result, default=str), tool_call_id=call_id, name=name))
            calls.append({"name": name, "arguments": args, "result": result})
        reply = model.invoke(base_messages(state, ctx, sensitive=True) + work)
        return {"work": work, "calls": calls, "draft": _text(reply)}

    def deep(state: AgentState, config: RunnableConfig) -> dict:
        """Planning path: read-only, budgeted. If it fails, the normal tool loop takes over."""
        ctx = _ctx(config)
        system, *conversation = base_messages(state, ctx)
        try:
            writer = get_stream_writer()  # lets steps reach the client while the plan runs
        except Exception:
            writer = None
        result = run_deep_path(
            model, ctx, conversation, system.content, subagent_model=deps.subagent_model,
            on_step=(lambda step: writer({"step": step})) if writer else None,
        )
        if result.error:
            log.warning("planning path failed (%s); using the normal tool loop (trace %s)",
                        result.error, ctx.trace_id)
        work: list[BaseMessage] = []
        for index, made in enumerate(result.calls):
            call_id = f"deep-{index}"
            work.append(AIMessage(content="", tool_calls=[
                {"name": made["name"], "args": made["arguments"], "id": call_id}]))
            work.append(ToolMessage(json.dumps(made["result"], default=str),
                                    tool_call_id=call_id, name=made["name"]))
        return {"draft": result.text, "calls": result.calls, "work": work, "trace": result.trace}

    def after_deep(state: AgentState) -> str:
        return "verify" if state.get("draft") else "agent"

    def agent(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        messages = base_messages(state, ctx) + state["work"]
        reply = model.bind_tools(_tool_schemas(ctx.role)).invoke(messages)
        update: dict[str, Any] = {"work": [*state["work"], reply]}
        if not getattr(reply, "tool_calls", None):
            update["draft"] = _text(reply)
        return update

    def after_agent(state: AgentState) -> str:
        return "tools" if getattr(state["work"][-1], "tool_calls", None) else "verify"

    def tools(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        calls = list(state["calls"])
        work = list(state["work"])
        for requested in work[-1].tool_calls:
            if len(calls) >= deps.max_tool_calls:
                result = {"error": "Tool call limit reached. Answer with what you have."}
            else:
                result = call_tool(ctx, requested["name"], requested["args"])
            calls.append({"name": requested["name"], "arguments": requested["args"], "result": result})
            work.append(
                ToolMessage(json.dumps(result, default=str), tool_call_id=requested["id"], name=requested["name"])
            )
        return {"work": work, "calls": calls}

    def after_tools(state: AgentState) -> str:
        return "answer_now" if len(state["calls"]) >= deps.max_tool_calls else "agent"

    def answer_now(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        messages = base_messages(state, ctx) + state["work"] + [HumanMessage(prompts.ANSWER_NOW)]
        return {"draft": _text(model.invoke(messages))}

    def verify(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        evidence = Evidence(
            calls=tuple(ToolCall(c["name"], c["arguments"], c["result"]) for c in state["calls"]),
            user_message=state["user_message"],
            today=ctx.today,
            other_names=repo.list_other_employee_names(ctx.conn, ctx.employee_id),
        )
        limit = SENSITIVE_MAX_SENTENCES if state["route"].get("intent") == "sensitive" else None
        result = verify_answer(state["draft"], evidence, max_sentences=limit)
        found = [{"code": p.code, "detail": p.detail} for p in result.problems]
        return {
            "problems": [[p["code"], p["detail"]] for p in found],
            "problem_log": [*state.get("problem_log", []), *found],
        }

    def after_verify(state: AgentState) -> str:
        if not state["problems"]:
            return "finalize"
        return "rewrite" if state["attempts"] < MAX_REWRITES else "fallback"

    def rewrite(state: AgentState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        messages = (
            base_messages(state, ctx, sensitive=state["route"].get("intent") == "sensitive")
            + state["work"]
            + [AIMessage(state["draft"]), HumanMessage(prompts.rewrite_prompt(
                [(code, detail) for code, detail in state["problems"]]))]
        )
        return {"draft": _text(model.invoke(messages)), "attempts": state["attempts"] + 1}

    def fallback(state: AgentState) -> dict:
        calls = [ToolCall(c["name"], c["arguments"], c["result"]) for c in state["calls"]]
        return {"final": build_fallback(calls), "used_fallback": True}

    def finalize(state: AgentState) -> dict:
        final = state.get("final") or state.get("draft", "")
        return {
            "final": final,
            "history": [HumanMessage(state["user_message"]), AIMessage(final)],
        }

    graph = StateGraph(AgentState)
    for name, fn in [
        ("guardrail", guardrail), ("route", route), ("clarify", clarify), ("decline", decline),
        ("respond", respond), ("sensitive", sensitive), ("deep", deep), ("agent", agent), ("tools", tools),
        ("answer_now", answer_now), ("verify", verify), ("rewrite", rewrite),
        ("fallback", fallback), ("finalize", finalize),
    ]:
        graph.add_node(name, fn)
    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges("guardrail", after_guardrail, ["route", "finalize"])
    graph.add_conditional_edges(
        "route", after_route, ["clarify", "respond", "decline", "sensitive", "deep", "agent"]
    )
    graph.add_conditional_edges("deep", after_deep, ["verify", "agent"])
    graph.add_edge("clarify", "finalize")
    graph.add_edge("decline", "finalize")
    graph.add_edge("respond", "verify")
    graph.add_edge("sensitive", "verify")
    graph.add_conditional_edges("agent", after_agent, ["tools", "verify"])
    graph.add_conditional_edges("tools", after_tools, ["agent", "answer_now"])
    graph.add_edge("answer_now", "verify")
    graph.add_conditional_edges("verify", after_verify, ["finalize", "rewrite", "fallback"])
    graph.add_edge("rewrite", "verify")
    graph.add_edge("fallback", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def run_turn(agent, ctx: ToolContext, thread_id: str, message: str) -> TurnResult:
    state = agent.invoke(
        {"user_message": message},
        config={"configurable": {"thread_id": thread_id, "ctx": ctx}},
    )
    return TurnResult(
        final=state["final"],
        intent=(state.get("route") or {}).get("intent"),
        calls=state.get("calls", []),
        used_fallback=state.get("used_fallback", False),
        flags=state.get("flags", []),
        attempts=state.get("attempts", 0),
        problems=state.get("problem_log", []),
        confirmation=_pending_confirmation(ctx, state.get("calls", [])),
        trace=state.get("trace", []),
    )


TOKEN_CHUNK_CHARS = 24


def _chunks(text: str) -> Iterator[str]:
    """Split a finished answer into small pieces on word boundaries, without altering the text."""
    current = ""
    for piece in re.findall(r"\s*\S+|\s+", text):
        if current and len(current) + len(piece) > TOKEN_CHUNK_CHARS:
            yield current
            current = piece
        else:
            current += piece
    if current:
        yield current


def stream_turn(agent, ctx: ToolContext, thread_id: str, message: str) -> Iterator[tuple[str, dict]]:
    """Run a turn, yielding (event, data) pairs.

    Progress events come live (route, tool calls). The answer is only sent once it has passed
    verification: raw model tokens are never streamed, because a draft can still be rejected.
    """
    config = {"configurable": {"thread_id": thread_id, "ctx": ctx}}
    reported_calls = 0
    live_steps = False  # the planning path streams its steps while it runs
    for mode, update in agent.stream(
        {"user_message": message}, config=config, stream_mode=["updates", "custom"]
    ):
        if mode == "custom":
            if update.get("step"):
                live_steps = True
                yield "step", update["step"]
            continue
        for node, delta in update.items():
            if not delta:
                continue
            if node == "route":
                route = delta["route"]
                yield "route", {"intent": route["intent"], "needs_planning": route["needs_planning"]}
            if node == "deep" and live_steps:
                reported_calls = len(delta.get("calls") or [])
                continue  # already shown live
            for item in delta.get("trace") or []:
                yield "step", item
            calls = delta.get("calls")
            if calls and len(calls) > reported_calls:
                for call in calls[reported_calls:]:
                    yield "step", {
                        "tool": call["name"],
                        "arguments": call["arguments"],
                        "ok": "error" not in call["result"],
                    }
                reported_calls = len(calls)
    state = agent.get_state(config).values
    for piece in _chunks(state["final"]):
        yield "token", {"text": piece}
    confirmation = _pending_confirmation(ctx, state.get("calls", []))
    if confirmation:
        yield "confirm_required", confirmation
    yield "done", {
        "intent": (state.get("route") or {}).get("intent"),
        "used_fallback": state.get("used_fallback", False),
        "rewrites": state.get("attempts", 0),
        "flags": state.get("flags", []),
    }


def _pending_confirmation(ctx: ToolContext, calls: list[dict]) -> dict | None:
    prepared = any(
        c["name"] == "prepare_leave_request" and c["result"].get("draft_created") for c in calls
    )
    return repo.get_open_draft(ctx.conn, ctx.employee_id) if prepared else None

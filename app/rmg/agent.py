"""The resource management agent: guardrail, tool loop, verify, rewrite, fallback.

A small LangGraph built from the same shared parts as the HR agent (input guardrail, answer verifier,
deterministic fallback). It has no router and no planning path yet, and it has no write tools. It keeps the
state names the HR agent uses (route, calls, final, attempts, used_fallback, flags), so the existing
`stream_turn` and the web app work with it unchanged.
"""
import json
from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent import prompts as shared_prompts
from app.agent.fallback import build_fallback
from app.agent.guardrail import check_input
from app.agent.verifier import Evidence, ToolCall, verify_answer
from app.db import repositories as repo
from app.rmg import prompts
from app.rmg.tools import call_rmg_tool, tool_schemas
from app.tools.context import ToolContext

MAX_HISTORY_MESSAGES = 20  # ten turns
MAX_REWRITES = 2
ROUTE = {"intent": "rmg", "needs_planning": False, "confidence": 1.0}


class RmgState(TypedDict, total=False):
    history: Annotated[list[BaseMessage], add_messages]
    user_message: str
    work: list[BaseMessage]
    calls: list[dict]
    route: dict
    draft: str
    final: str
    attempts: int
    problems: list[list[str]]
    flags: list[str]
    used_fallback: bool
    blocked: bool


def _ctx(config: RunnableConfig) -> ToolContext:
    return config["configurable"]["ctx"]


def _text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text").strip()


def build_rmg_agent(model: BaseChatModel, checkpointer=None, max_tool_calls: int = 6):
    def base_messages(state: RmgState, ctx: ToolContext) -> list[BaseMessage]:
        employee = repo.get_employee(ctx.conn, ctx.employee_id)
        system = prompts.system_prompt(
            employee.name if employee else "the user", ctx.role, ctx.today, tuple(state.get("flags", []))
        )
        history = list(state.get("history", []))[-MAX_HISTORY_MESSAGES:]
        return [SystemMessage(system), *history, HumanMessage(state["user_message"])]

    def guardrail(state: RmgState) -> dict:
        result = check_input(state["user_message"])
        update: dict[str, Any] = {
            "work": [], "calls": [], "draft": "", "final": "", "attempts": 0, "problems": [],
            "used_fallback": False, "blocked": not result.allowed, "flags": list(result.flags), "route": {},
        }
        if not result.allowed:
            update["final"] = result.reply
        return update

    def after_guardrail(state: RmgState) -> str:
        return "finalize" if state.get("blocked") else "route"

    def route(_state: RmgState) -> dict:
        return {"route": dict(ROUTE)}

    def agent(state: RmgState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        messages = base_messages(state, ctx) + state["work"]
        reply = model.bind_tools(tool_schemas(ctx.role)).invoke(messages)
        update: dict[str, Any] = {"work": [*state["work"], reply]}
        if not getattr(reply, "tool_calls", None):
            update["draft"] = _text(reply)
        return update

    def after_agent(state: RmgState) -> str:
        return "tools" if getattr(state["work"][-1], "tool_calls", None) else "verify"

    def tools(state: RmgState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        calls = list(state["calls"])
        work = list(state["work"])
        for requested in work[-1].tool_calls:
            if len(calls) >= max_tool_calls:
                result = {"error": "Tool call limit reached. Answer with what you have."}
            else:
                result = call_rmg_tool(ctx, requested["name"], requested["args"])
            calls.append({"name": requested["name"], "arguments": requested["args"], "result": result})
            work.append(ToolMessage(json.dumps(result, default=str), tool_call_id=requested["id"], name=requested["name"]))
        return {"work": work, "calls": calls}

    def after_tools(state: RmgState) -> str:
        return "answer_now" if len(state["calls"]) >= max_tool_calls else "agent"

    def answer_now(state: RmgState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        messages = base_messages(state, ctx) + state["work"] + [HumanMessage(shared_prompts.ANSWER_NOW)]
        return {"draft": _text(model.invoke(messages))}

    def verify(state: RmgState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        evidence = Evidence(
            calls=tuple(ToolCall(c["name"], c["arguments"], c["result"]) for c in state["calls"]),
            user_message=state["user_message"],
            today=ctx.today,
            other_names=repo.list_other_employee_names(ctx.conn, ctx.employee_id),
        )
        result = verify_answer(state["draft"], evidence)
        return {"problems": [[p.code, p.detail] for p in result.problems]}

    def after_verify(state: RmgState) -> str:
        if not state["problems"]:
            return "finalize"
        return "rewrite" if state["attempts"] < MAX_REWRITES else "fallback"

    def rewrite(state: RmgState, config: RunnableConfig) -> dict:
        ctx = _ctx(config)
        messages = (
            base_messages(state, ctx)
            + state["work"]
            + [AIMessage(state["draft"]), HumanMessage(shared_prompts.rewrite_prompt(
                [(code, detail) for code, detail in state["problems"]]))]
        )
        return {"draft": _text(model.invoke(messages)), "attempts": state["attempts"] + 1}

    def fallback(state: RmgState) -> dict:
        calls = [ToolCall(c["name"], c["arguments"], c["result"]) for c in state["calls"]]
        return {"final": build_fallback(calls), "used_fallback": True}

    def finalize(state: RmgState) -> dict:
        final = state.get("final") or state.get("draft", "")
        return {"final": final, "history": [HumanMessage(state["user_message"]), AIMessage(final)]}

    graph = StateGraph(RmgState)
    for name, fn in [
        ("guardrail", guardrail), ("route", route), ("agent", agent), ("tools", tools),
        ("answer_now", answer_now), ("verify", verify), ("rewrite", rewrite),
        ("fallback", fallback), ("finalize", finalize),
    ]:
        graph.add_node(name, fn)
    graph.add_edge(START, "guardrail")
    graph.add_conditional_edges("guardrail", after_guardrail, ["route", "finalize"])
    graph.add_edge("route", "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", "verify"])
    graph.add_conditional_edges("tools", after_tools, ["agent", "answer_now"])
    graph.add_edge("answer_now", "verify")
    graph.add_conditional_edges("verify", after_verify, ["finalize", "rewrite", "fallback"])
    graph.add_edge("rewrite", "verify")
    graph.add_edge("fallback", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)

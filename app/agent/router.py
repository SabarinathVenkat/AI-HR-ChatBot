"""Intent routing. A small model classifies each message; tests use a fixed stub."""
from dataclasses import dataclass
from typing import Literal, Protocol

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

Intent = Literal[
    "policy_question",
    "data_question",
    "policy_and_data",
    "calculation",
    "leave_request",
    "manager_action",
    "complex_plan",
    "sensitive",
    "chitchat",
    "out_of_scope",
]

CLARIFY_BELOW = 0.6


class RouteDecision(BaseModel):
    """How to handle the latest message."""

    intent: Intent = Field(description="The kind of request.")
    needs_planning: bool = Field(
        default=False,
        description="True only if answering needs several dependent steps, comparison or planning.",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    sensitive_topic: Literal["posh", "payroll", "general"] = Field(
        default="general", description="For sensitive requests, which contact fits."
    )


@dataclass(frozen=True)
class RouteInput:
    message: str
    history: list[BaseMessage]
    role: str


class Router(Protocol):
    def classify(self, request: RouteInput) -> RouteDecision: ...


ROUTER_PROMPT = """You route messages sent to an HR assistant for employees of a company.
Pick exactly one intent:
- policy_question: asks what a company rule, entitlement, process or benefit is.
- data_question: asks about the employee's own data (leave balance, requests, holidays).
- policy_and_data: needs both a rule and the employee's data ("can I carry forward my leave?").
- calculation: asks how many working days a date range counts.
- leave_request: wants to apply for, change or cancel leave.
- manager_action: a manager asking about their team (approvals, who is on leave). Only for managers.
- complex_plan: needs planning or comparison over several steps ("plan my December leave").
- sensitive: harassment, discrimination, safety, mental health, legal disputes, grievances.
- chitchat: greetings, thanks, small talk.
- out_of_scope: anything unrelated to HR at work.
A request for another person's, or everyone's, HR data (balances, requests, salary) is still an \
HR topic: classify it as data_question, not out_of_scope, so the assistant can explain why it \
cannot share it.
Set needs_planning true only for complex_plan. Use the recent conversation to resolve short
follow-ups. If you are unsure, lower the confidence. The user is a(n) {role}."""


class LLMRouter:
    def __init__(self, model: BaseChatModel) -> None:
        # json_schema mode: forced tool calling is not supported on every current model.
        self._structured = model.with_structured_output(RouteDecision, method="json_schema")

    def classify(self, request: RouteInput) -> RouteDecision:
        recent = request.history[-6:]
        messages = [
            SystemMessage(ROUTER_PROMPT.replace("{role}", request.role)),
            *recent,
            HumanMessage(request.message),
        ]
        return self._structured.invoke(messages)

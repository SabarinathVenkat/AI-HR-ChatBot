"""Build the live agent with Anthropic models."""
import logging

from langchain_anthropic import ChatAnthropic

from app.agent.graph import AgentDeps, build_agent
from app.agent.router import LLMRouter, RouteDecision, RouteInput, Router
from app.config import Settings

log = logging.getLogger(__name__)

ANSWER_MAX_TOKENS = 4096


class FallbackRouter:
    """Use the small router model, and switch to the answer model if it is unavailable.

    A small model can be retired or have an outage, so a router failure must not take chat down.
    """

    def __init__(self, primary: Router, secondary: Router) -> None:
        self._primary = primary
        self._secondary = secondary

    def classify(self, request: RouteInput) -> RouteDecision:
        try:
            return self._primary.classify(request)
        except Exception as exc:  # any provider error: fall back rather than fail the request
            log.warning("router model failed (%s); falling back to the answer model", type(exc).__name__)
            return self._secondary.classify(request)


def build_live_agent(settings: Settings, checkpointer):
    # Reasoning tokens count against max_tokens on current models, so leave generous headroom or a
    # hard question could spend the whole budget thinking and return a truncated answer.
    answer_model = ChatAnthropic(model=settings.answer_model, max_tokens=ANSWER_MAX_TOKENS)
    router_model = ChatAnthropic(model=settings.router_model, max_tokens=300)
    router = FallbackRouter(LLMRouter(router_model), LLMRouter(answer_model))
    # Planning sub-agents only call tools and report, so they use the faster model.
    subagent_model = ChatAnthropic(model=settings.router_model, max_tokens=1500)
    return build_agent(
        AgentDeps(model=answer_model, router=router, subagent_model=subagent_model), checkpointer
    )

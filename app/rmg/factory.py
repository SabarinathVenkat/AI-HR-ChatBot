"""Build the live resource management agent with the same answer model the HR agent uses."""
from langchain_anthropic import ChatAnthropic

from app.agent.factory import ANSWER_MAX_TOKENS
from app.config import Settings
from app.rmg.agent import build_rmg_agent


def build_live_rmg_agent(settings: Settings, checkpointer):
    model = ChatAnthropic(model=settings.answer_model, max_tokens=ANSWER_MAX_TOKENS)
    return build_rmg_agent(model, checkpointer)

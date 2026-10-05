"""Shared test helpers."""
import re
import zlib

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

DIMENSIONS = 384


class ScriptedChatModel(BaseChatModel):
    """A chat model that replays scripted AIMessages and records what it was sent."""

    responses: list = Field(default_factory=list)
    seen: list = Field(default_factory=list)
    bound_tools: list = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        self.bound_tools.append(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        if not self.responses:
            raise AssertionError("ScriptedChatModel ran out of scripted responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):  # lets a test script a model failure
            raise response
        return ChatResult(generations=[ChatGeneration(message=response)])


class FixedRouter:
    """A router stub that always returns the same decision (or a sequence of decisions)."""

    def __init__(self, *decisions) -> None:
        self._decisions = list(decisions)
        self.requests: list = []

    def classify(self, request):
        self.requests.append(request)
        return self._decisions.pop(0) if len(self._decisions) > 1 else self._decisions[0]


def tool_call(name: str, args: dict | None = None, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


class BagOfWordsEmbedder:
    """Hashes words into a fixed-size vector. Similar wording gives similar vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * DIMENSIONS
            for word in re.findall(r"[a-z]+", text.lower()):
                vec[zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

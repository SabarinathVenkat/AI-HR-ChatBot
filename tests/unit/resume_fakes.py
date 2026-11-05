"""A fake chat model for the resume tests: returns what it is told, records how it was asked."""
from langchain_core.messages import AIMessage

from app.rmg.resume.extract import LLMResumeExtractor


class FakeStructured:
    def __init__(self, reply):
        self.reply, self.messages = reply, None

    def invoke(self, messages):
        self.messages = messages
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class FakeModel:
    def __init__(self, parsed=None, stop_reason="end_turn", parsing_error=None, error=None):
        reply = error or {"raw": AIMessage(content="", response_metadata={"stop_reason": stop_reason}),
                          "parsed": parsed, "parsing_error": parsing_error}
        self.structured, self.kwargs, self.schema = FakeStructured(reply), None, None

    def with_structured_output(self, schema, **kwargs):
        self.schema, self.kwargs = schema, kwargs
        return self.structured


def extractor_for(model, extractor_class=LLMResumeExtractor):
    budgets = []

    def factory(max_tokens):
        budgets.append(max_tokens)
        return model

    return extractor_class(factory), budgets

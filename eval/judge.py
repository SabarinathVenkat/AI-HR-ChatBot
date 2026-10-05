"""A model-based grader for the few checks where wording matters (tone of a refusal, quality of a plan).

Everything numeric or structural is checked deterministically elsewhere. The judge sees only the
rubric, the question and the reply, and is told to be strict. A judge failure is a failed check,
never a silent pass, and its reason names the cause.
"""
import logging
import time

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

PROMPT = """You are grading a reply from an HR assistant against a rubric. Be strict: pass only if
the rubric is fully met. Judge only what is written in the reply.

RUBRIC:
{rubric}

QUESTION ASKED:
{question}

REPLY:
{answer}

Give your verdict."""

BACKOFF_SECONDS = (1, 3)
JUDGE_MAX_TOKENS = 4000


class Verdict(BaseModel):
    passed: bool = Field(description="True only if the reply fully meets the rubric.")
    reason: str = Field(description="One short sentence explaining the verdict.")


def make_judge(model_name: str, structured=None, sleep=time.sleep):
    if structured is None:
        from langchain_anthropic import ChatAnthropic

        # Sonnet 5.5 reasons before answering and reasoning tokens count against max_tokens. With a
        # small budget a long answer used it all on thinking and no verdict was emitted.
        structured = ChatAnthropic(model=model_name, max_tokens=JUDGE_MAX_TOKENS).with_structured_output(
            Verdict, method="json_schema"
        )

    def judge(rubric: str, question: str, answer: str) -> tuple[bool, str]:
        # Substitution is done by concatenation-safe replace, so braces in the reply are harmless.
        prompt = (
            PROMPT.replace("{rubric}", rubric).replace("{question}", question).replace("{answer}", answer)
        )
        last_error: Exception | None = None
        for attempt in range(len(BACKOFF_SECONDS) + 1):
            try:
                verdict = structured.invoke(prompt)
                return verdict.passed, verdict.reason
            except Exception as exc:
                last_error = exc
                log.warning("judge attempt %d failed: %s", attempt + 1, type(exc).__name__)
                if attempt < len(BACKOFF_SECONDS):
                    sleep(BACKOFF_SECONDS[attempt])
        detail = " ".join(str(last_error).split())[:200]
        return False, f"judge error: {type(last_error).__name__}: {detail}"

    return judge

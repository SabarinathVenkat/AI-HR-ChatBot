"""Input guardrail: size limit and prompt-injection flagging. Flagging never blocks by itself."""
import re
from dataclasses import dataclass

MAX_MESSAGE_CHARS = 4000
TOO_LONG = "That message is too long for me to handle. Please shorten it and try again."

INJECTION_PATTERNS = [
    r"ignore (?:all |any |your |the )?(?:previous|prior|above|earlier) (?:instructions|rules|prompts?)",
    r"disregard (?:all |any |your |the )?(?:previous|prior|above|earlier)? ?(?:instructions|rules)",
    r"(?:reveal|show|print|repeat|output) (?:me )?(?:your|the) (?:system )?(?:prompt|instructions)",
    r"you are now\b",
    r"developer mode",
    r"jailbreak",
    r"pretend (?:to be|you are)",
    r"act as (?:if you (?:are|were)|an?|the) ",
    r"(?:override|bypass) (?:your |the )?(?:rules|safety|restrictions|guardrails)",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reply: str | None = None
    flags: tuple[str, ...] = ()


def check_input(message: str) -> GuardrailResult:
    if not message.strip():
        return GuardrailResult(False, "Please type a question and I'll do my best to help.")
    if len(message) > MAX_MESSAGE_CHARS:
        return GuardrailResult(False, TOO_LONG, ("too_long",))
    flags = ("possible_prompt_injection",) if _INJECTION.search(message) else ()
    return GuardrailResult(True, None, flags)

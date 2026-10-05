"""Answer verifier. Deterministic checks that a draft answer is backed by this turn's evidence.

Every number and date in the draft must appear in the tool output (or the user's own message) of
the current turn, every policy citation must have been retrieved, a policy answer must cite, and
no other employee's name may appear. Numbers written as words ("sixty") are not checked.
"""
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

MONTHS = "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
MONTH_NUMBER = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}

CITATION = re.compile(r"POL-\d{2}\s§\d+(?:\.\d+)*")
BARE_SECTION = re.compile(r"§\s?(\d+(?:\.\d+)*)")  # "§2.3" written after a full citation
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTHS})\b\.?")
MONTH_DAY = re.compile(rf"\b({MONTHS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b")
NUMBER = re.compile(r"(?<![A-Za-z0-9_.\-])\d+(?:,\d{3})*(?:\.\d+)?")
DRAFT_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*]\s+)?\d+[.)]\s+")
EVIDENCE_CLAUSE_MARKER = re.compile(r"(?m)^\s*#*\s*\d+(?:\.\d+)+\s+|^\s*#*\s*\d+\.\s+")


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict
    result: dict


@dataclass(frozen=True)
class Evidence:
    calls: tuple[ToolCall, ...]
    user_message: str
    today: date
    other_names: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Problem:
    code: str
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    problems: tuple[Problem, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _month_number(name: str) -> int:
    return MONTH_NUMBER[name[:3]]


def _walk(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        yield "number", len(value)  # how many items a tool returned may be stated
        for item in value:
            yield from _walk(item)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, (int, float)):
        yield "number", value
    elif isinstance(value, str):
        yield "text", value


def _numbers_in(text: str) -> set[Decimal]:
    """Numbers that are figures: not citations, dates or list/clause numbering."""
    text = CITATION.sub(" ", text)
    text = BARE_SECTION.sub(" ", text)
    text = ISO_DATE.sub(" ", text)
    text = DAY_MONTH.sub(" ", text)
    text = MONTH_DAY.sub(" ", text)
    return {Decimal(m.replace(",", "")).normalize() for m in NUMBER.findall(text)}


def _month_days_in(text: str) -> set[tuple[int, int]]:
    found = {(int(m.group(2)), int(m.group(3))) for m in ISO_DATE.finditer(text)}
    found |= {(_month_number(m.group(2)), int(m.group(1))) for m in DAY_MONTH.finditer(text)}
    found |= {(_month_number(m.group(1)), int(m.group(2))) for m in MONTH_DAY.finditer(text)}
    return found


@dataclass(frozen=True)
class _EvidenceIndex:
    numbers: frozenset[Decimal]
    month_days: frozenset[tuple[int, int]]
    citations: frozenset[str]
    text_lower: str


def _index(evidence: Evidence) -> _EvidenceIndex:
    numbers: set[Decimal] = set()
    month_days: set[tuple[int, int]] = {(evidence.today.month, evidence.today.day)}
    citations: set[str] = set()
    texts: list[str] = [evidence.user_message]
    for call in evidence.calls:
        for payload in (call.arguments, call.result):
            for kind, value in _walk(payload):
                if kind == "number":
                    numbers.add(Decimal(str(value)).normalize())
                else:
                    texts.append(value)
    for text in texts:
        cleaned = EVIDENCE_CLAUSE_MARKER.sub(" ", text)
        numbers |= _numbers_in(cleaned)
        month_days |= _month_days_in(cleaned)
        citations |= set(CITATION.findall(text))
    return _EvidenceIndex(
        frozenset(numbers), frozenset(month_days), frozenset(citations), "\n".join(texts).lower()
    )


def _policy_answer_needs_citation(evidence: Evidence) -> bool:
    return any(
        call.name == "search_policy" and call.result.get("confident") and call.result.get("results")
        for call in evidence.calls
    )


# Matches the address but not a full stop that follows it, so the sentence after it still counts.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
BRACKETED = re.compile(r"\[[^\]]*\]")


def _sentence_count(text: str) -> int:
    """Rough count: citations, emails and decimal points do not end a sentence."""
    text = BRACKETED.sub(" ", text)
    text = EMAIL.sub(" ", text)
    pieces = re.split(r"(?<=[.!?])\s+", text.strip())
    return sum(1 for piece in pieces if re.search(r"[A-Za-z]", piece))


def verify_answer(
    draft: str, evidence: Evidence, max_sentences: int | None = None
) -> VerificationResult:
    if not draft.strip():
        # A blank draft has no figures, dates or citations to fail on, so without this check it would
        # pass as "verified" and the employee would be shown nothing. It goes to a rewrite or the fallback.
        return VerificationResult((Problem("empty_answer", "the draft is empty"),))

    index = _index(evidence)
    problems: list[Problem] = []

    if max_sentences is not None:
        count = _sentence_count(draft)
        if count > max_sentences:
            problems.append(Problem("too_long", f"{count} sentences; the limit is {max_sentences}"))

    cited = set(CITATION.findall(draft))
    for citation in sorted(cited - index.citations):
        problems.append(Problem("unknown_citation", f"{citation} was not retrieved this turn"))
    if _policy_answer_needs_citation(evidence) and not cited:
        problems.append(Problem("missing_citation", "a policy answer must cite its section"))
    bare_only = BARE_SECTION.findall(CITATION.sub(" ", draft))
    for ref in sorted(set(bare_only)):
        if not any(c.endswith(f"§{ref}") for c in index.citations):
            problems.append(Problem("unknown_citation", f"§{ref} was not retrieved this turn"))

    for match in ISO_DATE.finditer(draft):
        if (int(match.group(2)), int(match.group(3))) not in index.month_days:
            problems.append(Problem("date_not_in_evidence", match.group(0)))
    natural = [
        (m.group(0).strip(" ."), _month_number(m.group(2)), int(m.group(1)))
        for m in DAY_MONTH.finditer(draft)
    ] + [
        (m.group(0).strip(" ."), _month_number(m.group(1)), int(m.group(2)))
        for m in MONTH_DAY.finditer(draft)
    ]
    for label, month, day in natural:
        if (month, day) not in index.month_days:
            problems.append(Problem("date_not_in_evidence", label))

    body = DRAFT_LIST_MARKER.sub("", draft)
    for number in sorted(_numbers_in(body) - index.numbers):
        problems.append(Problem("number_not_in_evidence", f"{number:f}"))

    lowered = draft.lower()
    for name in sorted(evidence.other_names):
        if name.lower() in lowered and name.lower() not in index.text_lower:
            problems.append(Problem("other_employee", name))

    return VerificationResult(tuple(problems))

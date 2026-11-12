"""Facts about a resume that code computes, so a model never does arithmetic or guesses a date.

Dates are read strictly: anything not understood is None, and a job whose dates cannot be read is reported as
skipped instead of being estimated. "Today" is passed in so results are deterministic and testable.
"""
import re
from dataclasses import dataclass
from datetime import date

from app.rmg.resume.model import Job, Resume, SkillGroup

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
          "december"]
STILL_WORKING = {"present", "current", "currently", "now", "ongoing", "till date", "to date", "till now", "today"}

_NAMED = re.compile(r"^([a-z]{3,9})\.?\s*(?:(\d{4})|'\s*(\d{2}))$")
_DAY_FIRST = re.compile(r"^(\d{1,2})\s*[/-]\s*(\d{4})$")
_YEAR_FIRST = re.compile(r"^(\d{4})\s*[/-]\s*(\d{1,2})$")
_YEAR = re.compile(r"^\d{4}$")


def _month_number(word: str) -> int | None:
    for number, name in enumerate(MONTHS, 1):
        if name.startswith(word):  # "mar", "march", "sept"
            return number
    return None


def parse_month(text: str | None, today: date, *, as_end: bool = False) -> tuple[int, int] | None:
    """(year, month), or None when the text is not understood. A bare year is January, or December if as_end."""
    value = " ".join((text or "").lower().split())
    if not value:
        return None
    if value in STILL_WORKING:
        return today.year, today.month
    year = month = None
    if m := _NAMED.match(value):
        month = _month_number(m.group(1))
        year = int(m.group(2)) if m.group(2) else 2000 + int(m.group(3))
    elif m := _DAY_FIRST.match(value):
        month, year = int(m.group(1)), int(m.group(2))
    elif m := _YEAR_FIRST.match(value):
        year, month = int(m.group(1)), int(m.group(2))
    elif _YEAR.match(value):
        year, month = int(value), 12 if as_end else 1
    if year is None or month is None or not 1 <= month <= 12 or not 1950 <= year <= today.year + 10:
        return None
    return year, month


@dataclass(frozen=True)
class Experience:
    months: int
    skipped: tuple[str, ...]  # companies whose dates could not be used

    @property
    def years(self) -> int:
        return self.months // 12

    @property
    def extra_months(self) -> int:
        return self.months % 12

    def describe(self) -> str:
        parts = [f"{n} {word}{'s' if n != 1 else ''}" for n, word in ((self.years, "year"), (self.extra_months, "month")) if n]
        return " ".join(parts) or "less than a month"


def _index(year_month: tuple[int, int]) -> int:
    return year_month[0] * 12 + year_month[1] - 1


def experience(jobs: list[Job], today: date) -> Experience:
    """Total months worked. Both end months count, overlapping jobs count once, gaps do not count."""
    now = _index((today.year, today.month))
    covered: set[int] = set()
    skipped: list[str] = []
    for job in jobs:
        start = parse_month(job.start, today)
        end = parse_month(job.end, today, as_end=True) if job.end else (today.year, today.month)  # no end: current
        if start is None or end is None or _index(start) > now or _index(end) < _index(start):
            skipped.append(job.company or job.title or "an unnamed job")
            continue
        covered.update(range(_index(start), min(_index(end), now) + 1))
    return Experience(months=len(covered), skipped=tuple(skipped))


def _key(text: str) -> str:
    return " ".join(text.casefold().split())


def dedupe_skills(resume: Resume) -> Resume:
    """Each skill once, in the first group that lists it (ignoring case and spacing). Empty groups are dropped."""
    seen: set[str] = set()
    groups: list[SkillGroup] = []
    for group in resume.skill_groups:
        kept = []
        for item in group.items:
            if (key := _key(item.text)) not in seen:
                seen.add(key)
                kept.append(item)
        if kept:
            groups.append(group.model_copy(update={"items": kept}))
    return resume.model_copy(update={"skill_groups": groups})

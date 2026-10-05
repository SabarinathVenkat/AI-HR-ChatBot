"""Working-day counting. Pure logic: no I/O, no clock reads.

Days are counted internally as integer half-days so the arithmetic is exact.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

SATURDAY = 5

StartHalf = Literal["full", "second"]
EndHalf = Literal["full", "first"]


@dataclass(frozen=True)
class Exclusion:
    date: date
    reason: str


@dataclass(frozen=True)
class WorkingDays:
    days: float
    excluded: tuple[Exclusion, ...] = ()


def count_working_days(
    start: date,
    end: date,
    holidays: Mapping[date, str] | None = None,
    start_half: StartHalf = "full",
    end_half: EndHalf = "full",
) -> WorkingDays:
    if end < start:
        raise ValueError("end date is before start date")
    holidays = holidays or {}
    half_days = 0
    excluded: list[Exclusion] = []
    current = start
    while current <= end:
        if current.weekday() >= SATURDAY:
            excluded.append(Exclusion(current, "weekend"))
        elif current in holidays:
            excluded.append(Exclusion(current, f"holiday: {holidays[current]}"))
        else:
            half_days += _half_days_taken(current, start, end, start_half, end_half)
        current += timedelta(days=1)
    return WorkingDays(days=half_days / 2, excluded=tuple(excluded))


def _is_day_off(day: date, holidays: Mapping[date, str]) -> bool:
    return day.weekday() >= SATURDAY or day in holidays


def break_span(start: date, end: date, holidays: Mapping[date, str]) -> tuple[date, date]:
    """The whole stretch away from work: the leave range plus adjoining weekends and holidays."""
    first, last = start, end
    while _is_day_off(first - timedelta(days=1), holidays):
        first -= timedelta(days=1)
    while _is_day_off(last + timedelta(days=1), holidays):
        last += timedelta(days=1)
    return first, last


def _half_days_taken(
    day: date, start: date, end: date, start_half: StartHalf, end_half: EndHalf
) -> int:
    partial_start = day == start and start_half == "second"
    partial_end = day == end and end_half == "first"
    return 1 if partial_start or partial_end else 2

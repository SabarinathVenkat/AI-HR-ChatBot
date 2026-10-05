"""Working-day counting, per POL-02 section 5 (leave counted in working days).

Reference calendar: 2026-03-02 is a Monday.
"""
from datetime import date, timedelta

import pytest
from hypothesis import given, strategies as st

from app.domain.calendar import count_working_days

MON = date(2026, 3, 2)
WED = date(2026, 3, 4)
FRI = date(2026, 3, 6)
SAT = date(2026, 3, 7)
SUN = date(2026, 3, 8)
NEXT_MON = date(2026, 3, 9)


def test_monday_to_friday_without_holidays_counts_five_days():
    result = count_working_days(MON, FRI)

    assert result.days == 5


def test_friday_to_following_monday_counts_two_days():
    # POL-02 5.5: the weekend in between is not counted.
    result = count_working_days(FRI, NEXT_MON)

    assert result.days == 2
    assert [e.date for e in result.excluded] == [SAT, SUN]
    assert {e.reason for e in result.excluded} == {"weekend"}


def test_holiday_inside_the_range_is_not_counted():
    # POL-02 5.4: Monday to Friday with a holiday on Wednesday counts 4.
    result = count_working_days(MON, FRI, holidays={WED: "Test Holiday"})

    assert result.days == 4
    assert [(e.date, e.reason) for e in result.excluded] == [(WED, "holiday: Test Holiday")]


def test_holiday_on_a_weekend_is_reported_once_as_weekend():
    result = count_working_days(FRI, NEXT_MON, holidays={SAT: "Weekend Holiday"})

    assert result.days == 2
    assert [(e.date, e.reason) for e in result.excluded] == [(SAT, "weekend"), (SUN, "weekend")]


def test_single_half_day_counts_half():
    assert count_working_days(MON, MON, start_half="second").days == 0.5
    assert count_working_days(MON, MON, end_half="first").days == 0.5


def test_half_day_at_the_start_of_a_range_counts_half_for_that_day():
    # Monday afternoon only, then Tuesday and Wednesday in full.
    assert count_working_days(MON, WED, start_half="second").days == 2.5


def test_half_day_at_the_end_of_a_range_counts_half_for_that_day():
    assert count_working_days(MON, WED, end_half="first").days == 2.5


def test_half_days_at_both_ends():
    assert count_working_days(MON, WED, start_half="second", end_half="first").days == 2


def test_half_day_on_a_non_working_boundary_day_changes_nothing():
    # Saturday start with "second half" must not subtract anything: Sat is already excluded.
    assert count_working_days(SAT, NEXT_MON).days == 1
    assert count_working_days(SAT, NEXT_MON, start_half="second").days == 1


def test_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        count_working_days(FRI, MON)


def test_range_across_the_year_boundary():
    # Tue 2025-12-30 to Mon 2026-01-05, with 2026-01-01 (Thursday) a holiday.
    # Working days: Dec 30, Dec 31, Jan 2, Jan 5 = 4.
    result = count_working_days(
        date(2025, 12, 30), date(2026, 1, 5), holidays={date(2026, 1, 1): "New Year"}
    )

    assert result.days == 4


def test_range_including_a_leap_day():
    # 2028 is a leap year. Mon 2028-02-28 to Wed 2028-03-01 includes Tue 2028-02-29.
    assert count_working_days(date(2028, 2, 28), date(2028, 3, 1)).days == 3


@given(
    start=st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31)),
    length=st.integers(min_value=0, max_value=120),
)
def test_count_is_bounded_by_calendar_days(start, length):
    end = start + timedelta(days=length)

    days = count_working_days(start, end).days

    assert 0 <= days <= length + 1


@given(
    start=st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31)),
    first=st.integers(min_value=0, max_value=60),
    second=st.integers(min_value=0, max_value=60),
)
def test_adjacent_ranges_add_up_to_the_whole_range(start, first, second):
    mid = start + timedelta(days=first)
    end = mid + timedelta(days=1 + second)
    holidays = {start + timedelta(days=3): "H"}

    whole = count_working_days(start, end, holidays).days
    parts = (
        count_working_days(start, mid, holidays).days
        + count_working_days(mid + timedelta(days=1), end, holidays).days
    )

    assert whole == parts


def test_weekend_only_range_counts_zero_days():
    result = count_working_days(SAT, SUN)

    assert result.days == 0

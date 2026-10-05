"""Leave accrual, pro-rating and carry-forward, per POL-02 sections 3 and 7."""
from datetime import date

from app.domain.accrual import (
    accrued_annual_leave,
    cap_accumulated_annual_leave,
    carry_forward_annual_leave,
    prorated_upfront_leave,
)

LONG_SERVING = date(2020, 6, 1)


def test_long_serving_employee_accrues_one_and_a_half_days_per_completed_month():
    # Jan, Feb, Mar all completed by 31 March.
    assert accrued_annual_leave(LONG_SERVING, as_of=date(2026, 3, 31)) == 4.5


def test_a_month_is_not_credited_until_it_is_complete():
    assert accrued_annual_leave(LONG_SERVING, as_of=date(2026, 3, 30)) == 3.0


def test_nothing_accrued_before_the_first_month_ends():
    assert accrued_annual_leave(LONG_SERVING, as_of=date(2026, 1, 30)) == 0


def test_full_year_accrues_eighteen_days():
    assert accrued_annual_leave(LONG_SERVING, as_of=date(2026, 12, 31)) == 18.0


def test_joiner_on_or_before_the_15th_gets_the_joining_month():
    # Joined 15 Mar: March counts. As of 31 Mar -> 1 month.
    assert accrued_annual_leave(date(2026, 3, 15), as_of=date(2026, 3, 31)) == 1.5


def test_joiner_after_the_15th_starts_accruing_the_next_month():
    assert accrued_annual_leave(date(2026, 3, 16), as_of=date(2026, 3, 31)) == 0
    assert accrued_annual_leave(date(2026, 3, 16), as_of=date(2026, 4, 30)) == 1.5


def test_joiner_in_the_year_accrues_only_from_the_joining_month():
    # Joined 1 Jul 2026, as of 31 Dec: Jul..Dec = 6 months = 9 days.
    assert accrued_annual_leave(date(2026, 7, 1), as_of=date(2026, 12, 31)) == 9.0


def test_nothing_accrued_before_joining():
    assert accrued_annual_leave(date(2026, 9, 1), as_of=date(2026, 3, 31)) == 0


def test_casual_leave_is_full_for_someone_who_joined_in_an_earlier_year():
    assert prorated_upfront_leave(6, date(2025, 12, 1), year=2026) == 6


def test_casual_leave_for_a_mid_year_joiner_is_prorated_by_remaining_months():
    # Joined 10 Jul: July counts (<= 15th). Jul..Dec = 6 months -> 6 * 6/12 = 3.
    assert prorated_upfront_leave(6, date(2026, 7, 10), year=2026) == 3.0


def test_casual_leave_for_a_joiner_after_the_15th_excludes_the_joining_month():
    # Joined 20 Jul: Aug..Dec = 5 months -> 6 * 5/12 = 2.5.
    assert prorated_upfront_leave(6, date(2026, 7, 20), year=2026) == 2.5


def test_prorated_leave_rounds_up_to_the_nearest_half_day():
    # Sick leave 8, joined 20 Jul: 8 * 5/12 = 3.33 -> 3.5.
    assert prorated_upfront_leave(8, date(2026, 7, 20), year=2026) == 3.5


def test_no_upfront_leave_for_a_joiner_in_a_later_year():
    assert prorated_upfront_leave(6, date(2027, 1, 5), year=2026) == 0


def test_unused_annual_leave_carries_forward_up_to_ten_days():
    assert carry_forward_annual_leave(unused=14) == 10
    assert carry_forward_annual_leave(unused=10) == 10
    assert carry_forward_annual_leave(unused=3.5) == 3.5
    assert carry_forward_annual_leave(unused=0) == 0


def test_accumulated_annual_leave_is_capped_at_thirty_days():
    assert cap_accumulated_annual_leave(balance=34) == 30
    assert cap_accumulated_annual_leave(balance=30) == 30
    assert cap_accumulated_annual_leave(balance=12.5) == 12.5

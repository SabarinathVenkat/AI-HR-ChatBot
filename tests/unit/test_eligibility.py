"""Leave eligibility, per POL-02 section 4 and FSD rules R1-R10.

Everything goes through the public check_eligibility seam. Reference calendar:
2026-03-02 is a Monday. "Today" is always passed in.
"""
from datetime import date

from app.domain.eligibility import (
    EmployeeContext,
    ExistingLeave,
    LeaveRequest,
    check_eligibility,
)

TODAY = date(2026, 2, 16)  # Monday, 2 weeks before the reference week
MON = date(2026, 3, 2)
TUE = date(2026, 3, 3)
WED = date(2026, 3, 4)
THU = date(2026, 3, 5)
FRI = date(2026, 3, 6)


def confirmed(balance: float = 10) -> EmployeeContext:
    return EmployeeContext(status="confirmed", available_balance=balance)


def probation(balance: float = 3) -> EmployeeContext:
    return EmployeeContext(status="probation", available_balance=balance)


def request(leave_type="AL", start=MON, end=FRI, **kwargs) -> LeaveRequest:
    return LeaveRequest(leave_type=leave_type, start=start, end=end, **kwargs)


def check(req, employee=None, today=TODAY, holidays=None, existing=()):
    return check_eligibility(
        req, employee or confirmed(), today=today, holidays=holidays or {}, existing=existing
    )


def failed_rules(result) -> set[str]:
    return {r.rule_id for r in result.rules if not r.passed}


def blocking_rules(result) -> set[str]:
    return {r.rule_id for r in result.rules if not r.passed and r.blocking}


def test_five_days_with_enough_balance_is_eligible():
    result = check(request(), confirmed(balance=10))

    assert result.eligible
    assert result.days_counted == 5
    assert result.balance_after == 5
    assert failed_rules(result) == set()


def test_holiday_in_the_range_reduces_the_days_counted():
    result = check(request(), confirmed(balance=10), holidays={WED: "Test Holiday"})

    assert result.days_counted == 4
    assert result.balance_after == 6


def test_end_date_before_start_date_is_blocked_by_r1():
    result = check(request(start=FRI, end=MON))

    assert not result.eligible
    assert "R1" in blocking_rules(result)


def test_start_in_a_past_leave_year_is_blocked_by_r1():
    result = check(request(start=date(2025, 12, 30), end=date(2025, 12, 31)))

    assert "R1" in blocking_rules(result)


def test_past_dated_annual_leave_is_blocked_by_r1():
    yesterday = date(2026, 2, 13)  # Friday before TODAY (Monday)
    result = check(request(start=yesterday, end=yesterday))

    assert "R1" in blocking_rules(result)


def test_past_dated_sick_leave_is_allowed_up_to_seven_days_back():
    seven_back = date(2026, 2, 9)
    result = check(request("SL", start=seven_back, end=seven_back))

    assert "R1" not in failed_rules(result)


def test_past_dated_sick_leave_more_than_seven_days_back_is_blocked():
    eight_back = date(2026, 2, 8)
    result = check(request("SL", start=eight_back, end=date(2026, 2, 9)))

    assert "R1" in blocking_rules(result)


def test_a_range_with_no_working_days_is_blocked_by_r2():
    result = check(request(start=date(2026, 3, 7), end=date(2026, 3, 8)))  # Sat-Sun

    assert not result.eligible
    assert "R2" in blocking_rules(result)


def test_unknown_leave_type_is_blocked_by_r3():
    result = check(request("XX"))

    assert "R3" in blocking_rules(result)


def test_paternity_leave_needs_a_confirmed_employee():
    on_probation = check(request("PL"), probation(balance=10))
    confirmed_employee = check(request("PL"), confirmed(balance=10))

    assert "R3" in blocking_rules(on_probation)
    assert "R3" not in failed_rules(confirmed_employee)


def test_probationer_cannot_take_more_than_the_accrued_balance():
    # E4: 3 days accrued, asks for 5 -> blocked by R4.
    result = check(request(), probation(balance=3))

    assert not result.eligible
    assert "R4" in blocking_rules(result)


def test_probationer_with_exactly_enough_balance_is_allowed():
    result = check(request(), probation(balance=5))

    assert "R4" not in failed_rules(result)
    assert result.eligible


def test_probationer_one_day_short_is_blocked():
    result = check(request(), probation(balance=4))

    assert "R4" in blocking_rules(result)


def test_confirmed_employee_short_of_balance_gets_a_loss_of_pay_warning_not_a_block():
    result = check(request(), confirmed(balance=3))

    assert result.eligible
    assert "R5" in failed_rules(result)
    assert "R5" not in blocking_rules(result)
    assert result.lop_days == 2
    assert result.balance_after == 0


def test_enough_balance_has_no_loss_of_pay():
    result = check(request(), confirmed(balance=5))

    assert "R5" not in failed_rules(result)
    assert result.lop_days == 0


def warnings(result) -> set[str]:
    return {r.rule_id for r in result.rules if not r.passed and not r.blocking}


def test_short_annual_leave_needs_one_working_days_notice():
    tomorrow = date(2026, 2, 17)
    same_day = check(request(start=TODAY, end=TODAY), confirmed(30))
    next_day = check(request(start=tomorrow, end=tomorrow), confirmed(30))

    assert "R6" in warnings(same_day)
    assert "R6" not in failed_rules(next_day)


def test_three_to_five_days_of_annual_leave_need_five_working_days_notice():
    # E5: 5 working days notice is Tue..Mon, so a Monday 23 Feb start has exactly 5.
    five_notice = check(request(start=date(2026, 2, 23), end=date(2026, 2, 26)), confirmed(30))
    four_notice = check(request(start=date(2026, 2, 20), end=date(2026, 2, 24)), confirmed(30))

    assert "R6" not in failed_rules(five_notice)
    assert "R6" in warnings(four_notice)
    assert four_notice.eligible  # a warning does not block


def test_more_than_five_days_of_annual_leave_need_ten_working_days_notice():
    ten_notice = check(request(start=MON, end=date(2026, 3, 9)), confirmed(30))  # 6 days
    eight_notice = check(request(start=date(2026, 2, 27), end=date(2026, 3, 6)), confirmed(30))

    assert "R6" not in failed_rules(ten_notice)
    assert "R6" in warnings(eight_notice)


def test_holidays_do_not_count_towards_notice():
    # Without the holiday this would be exactly 5 working days notice.
    result = check(
        request(start=date(2026, 2, 23), end=date(2026, 2, 26)),
        confirmed(30),
        holidays={date(2026, 2, 18): "Test Holiday"},
    )

    assert "R6" in warnings(result)


def test_casual_and_sick_leave_need_no_notice():
    casual = check(request("CL", start=TODAY, end=TODAY), confirmed(6))
    sick = check(request("SL", start=TODAY, end=TODAY), confirmed(8))

    assert "R6" not in failed_rules(casual)
    assert "R6" not in failed_rules(sick)


def test_annual_leave_of_fifteen_calendar_days_is_allowed_but_sixteen_is_blocked():
    fifteen = check(request(start=MON, end=date(2026, 3, 16)), confirmed(30))
    sixteen = check(request(start=MON, end=date(2026, 3, 17)), confirmed(30))

    assert "R7" not in failed_rules(fifteen)
    assert "R7" in blocking_rules(sixteen)


def test_sick_leave_of_more_than_two_working_days_needs_a_certificate():
    two_days = check(request("SL", start=date(2026, 2, 17), end=date(2026, 2, 18)), confirmed(8))
    three_days = check(request("SL", start=date(2026, 2, 17), end=date(2026, 2, 19)), confirmed(8))

    assert "R9" not in failed_rules(two_days)
    assert "R9" in warnings(three_days)
    assert three_days.eligible


def existing_al(start, end):
    return ExistingLeave("AL", start, end)


def test_overlap_with_an_existing_request_is_blocked_by_r10():
    result = check(request(start=WED, end=FRI), existing=[existing_al(TUE, WED)])

    assert not result.eligible
    assert "R10" in blocking_rules(result)


def test_adjacent_but_not_overlapping_request_is_allowed():
    result = check(request(start=THU, end=FRI), existing=[existing_al(MON, WED)])

    assert "R10" not in failed_rules(result)


def test_casual_leave_next_to_annual_leave_may_total_three_days():
    # AL on Monday (1 day) + CL Tuesday-Wednesday (2 days) = 3 consecutive days.
    result = check(request("CL", start=TUE, end=WED), confirmed(6), existing=[existing_al(MON, MON)])

    assert "R8" not in failed_rules(result)


def test_casual_leave_next_to_annual_leave_beyond_three_days_is_blocked():
    # AL Monday + CL Tuesday-Thursday = 4 consecutive days.
    result = check(request("CL", start=TUE, end=THU), confirmed(6), existing=[existing_al(MON, MON)])

    assert "R8" in blocking_rules(result)


def test_the_three_day_limit_applies_when_annual_leave_is_requested_next_to_casual_leave():
    existing_cl = ExistingLeave("CL", MON, WED)
    result = check(request("AL", start=THU, end=THU), confirmed(30), existing=[existing_cl])

    assert "R8" in blocking_rules(result)


def test_a_weekend_between_two_leaves_still_counts_as_consecutive():
    friday_al = existing_al(FRI, FRI)
    next_mon, next_wed = date(2026, 3, 9), date(2026, 3, 11)

    three = check(request("CL", start=next_mon, end=date(2026, 3, 10)), confirmed(6), existing=[friday_al])
    four = check(request("CL", start=next_mon, end=next_wed), confirmed(6), existing=[friday_al])

    assert "R8" not in failed_rules(three)
    assert "R8" in blocking_rules(four)


def test_a_working_day_gap_breaks_the_consecutive_run():
    result = check(request("CL", start=WED, end=FRI), confirmed(6), existing=[existing_al(MON, MON)])

    assert "R8" not in failed_rules(result)


def test_two_annual_leaves_next_to_each_other_are_not_subject_to_r8():
    result = check(request("AL", start=THU, end=FRI), confirmed(30), existing=[existing_al(MON, WED)])

    assert "R8" not in failed_rules(result)

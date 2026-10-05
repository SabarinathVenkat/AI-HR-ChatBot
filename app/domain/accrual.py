"""Leave accrual rules (POL-02 section 3). Pure logic: dates are always passed in."""
import calendar
import math
from datetime import date
from fractions import Fraction

ANNUAL_LEAVE_PER_MONTH = 1.5
JOINING_MONTH_CUTOFF_DAY = 15


def _first_credited_month(join_date: date, year: int) -> int:
    """First month of `year` that earns accrual for this employee (1-12; 13 = none)."""
    if join_date.year < year:
        return 1
    if join_date.year > year:
        return 13
    if join_date.day <= JOINING_MONTH_CUTOFF_DAY:
        return join_date.month
    return join_date.month + 1


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


CARRY_FORWARD_CAP = 10
ACCUMULATION_CAP = 30


def prorated_upfront_leave(entitlement: int, join_date: date, year: int) -> float:
    """CL/SL credited on 1 January, pro-rated for joiners, rounded up to 0.5 (POL-02 3.3)."""
    remaining_months = max(0, 13 - _first_credited_month(join_date, year))
    exact_half_days = Fraction(entitlement * remaining_months * 2, 12)
    return math.ceil(exact_half_days) / 2


def carry_forward_annual_leave(unused: float) -> float:
    """Unused annual leave that carries into the next year (POL-02 7.1)."""
    return min(unused, CARRY_FORWARD_CAP)


def cap_accumulated_annual_leave(balance: float) -> float:
    """Accumulated annual leave including carry forward is capped (POL-02 7.3)."""
    return min(balance, ACCUMULATION_CAP)


def accrued_annual_leave(join_date: date, as_of: date) -> float:
    """Annual leave accrued in the leave year containing `as_of` (POL-02 3.1, 3.2)."""
    year = as_of.year
    first = _first_credited_month(join_date, year)
    completed = sum(1 for month in range(first, 13) if _month_end(year, month) <= as_of)
    return completed * ANNUAL_LEAVE_PER_MONTH

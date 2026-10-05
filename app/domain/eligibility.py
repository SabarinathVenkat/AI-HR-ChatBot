"""Leave eligibility rules R1-R10 (POL-02 section 4, FSD 5.4). Pure logic: no I/O, no clock."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.domain.calendar import EndHalf, StartHalf, count_working_days


@dataclass(frozen=True)
class LeaveRequest:
    leave_type: str
    start: date
    end: date
    start_half: StartHalf = "full"
    end_half: EndHalf = "full"


@dataclass(frozen=True)
class EmployeeContext:
    status: Literal["probation", "confirmed"]
    available_balance: float


@dataclass(frozen=True)
class ExistingLeave:
    leave_type: str
    start: date
    end: date


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    blocking: bool
    message: str
    policy_ref: str


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    days_counted: float
    balance_after: float
    lop_days: float
    rules: tuple[RuleResult, ...]


SICK_LEAVE_BACKDATE_LIMIT_DAYS = 7
EVENT_TYPES_NEEDING_CONFIRMATION = frozenset({"PL", "MRL"})
KNOWN_LEAVE_TYPES = frozenset({"AL", "CL", "SL", "ML", "PL", "BL", "MRL", "CO", "LOP"})


def _rule(rule_id: str, passed: bool, message: str, policy_ref: str, blocking: bool = True):
    return RuleResult(rule_id, passed, blocking, message, policy_ref)


def _r1_date_range(request: LeaveRequest, today: date) -> RuleResult:
    ref = "POL-02 §4"
    if request.end < request.start:
        return _rule("R1", False, "The end date is before the start date.", ref)
    if request.start.year < today.year:
        return _rule("R1", False, "Leave cannot start in a previous leave year.", ref)
    if request.start < today:
        days_back = (today - request.start).days
        if request.leave_type != "SL":
            return _rule("R1", False, "Only sick leave can be applied for past dates.", ref)
        if days_back > SICK_LEAVE_BACKDATE_LIMIT_DAYS:
            return _rule("R1", False, "Sick leave can be backdated by 7 days at most.", ref)
    return _rule("R1", True, "The dates are valid.", ref)


def _r2_days_counted(days_counted: float) -> RuleResult:
    ref = "POL-02 §5"
    if days_counted < 0.5:
        return _rule("R2", False, "The range has no working days (weekends and holidays).", ref)
    return _rule("R2", True, f"{days_counted:g} working day(s) counted.", ref)


def _r3_leave_type(request: LeaveRequest, employee: EmployeeContext) -> RuleResult:
    if request.leave_type not in KNOWN_LEAVE_TYPES:
        return _rule("R3", False, f"Unknown leave type {request.leave_type}.", "POL-02 §2")
    needs_confirmation = request.leave_type in EVENT_TYPES_NEEDING_CONFIRMATION
    if needs_confirmation and employee.status != "confirmed":
        return _rule(
            "R3", False, f"{request.leave_type} is available after confirmation.", "POL-02 §4.1"
        )
    return _rule("R3", True, "The leave type is available.", "POL-02 §2")


def _r4_probation(employee: EmployeeContext, days_counted: float) -> RuleResult:
    ref = "POL-02 §4.1"
    if employee.status == "probation" and days_counted > employee.available_balance:
        return _rule(
            "R4",
            False,
            f"During probation only accrued leave can be used: {employee.available_balance:g} "
            f"day(s) available, {days_counted:g} requested.",
            ref,
        )
    return _rule("R4", True, "The probation rules are met.", ref)


def _r5_balance(employee: EmployeeContext, days_counted: float) -> RuleResult:
    ref = "POL-02 §4.7"
    shortfall = days_counted - employee.available_balance
    if shortfall > 0:
        return _rule(
            "R5",
            False,
            f"{shortfall:g} day(s) exceed the balance and would be loss of pay.",
            ref,
            blocking=False,
        )
    return _rule("R5", True, "The balance covers the request.", ref)


MAX_CONSECUTIVE_ANNUAL_LEAVE_DAYS = 15
SICK_CERTIFICATE_THRESHOLD_DAYS = 2


def _required_notice_days(days_counted: float) -> int:
    if days_counted <= 2:
        return 1
    if days_counted <= 5:
        return 5
    return 10


def _r6_notice(
    request: LeaveRequest, days_counted: float, today: date, holidays: Mapping[date, str]
) -> RuleResult:
    ref = "POL-02 §4.2"
    if request.leave_type != "AL":
        return _rule("R6", True, "No notice period applies to this leave type.", ref)
    required = _required_notice_days(days_counted)
    if request.start > today:
        given = count_working_days(today + timedelta(days=1), request.start, holidays).days
    else:
        given = 0
    if given < required:
        return _rule(
            "R6",
            False,
            f"Annual leave of this length needs {required} working day(s) notice; "
            f"{given:g} given.",
            ref,
            blocking=False,
        )
    return _rule("R6", True, "The notice period is met.", ref)


def _r7_consecutive(request: LeaveRequest) -> RuleResult:
    ref = "POL-02 §4.3"
    calendar_days = (request.end - request.start).days + 1
    if request.leave_type == "AL" and calendar_days > MAX_CONSECUTIVE_ANNUAL_LEAVE_DAYS:
        return _rule(
            "R7",
            False,
            f"Annual leave is limited to {MAX_CONSECUTIVE_ANNUAL_LEAVE_DAYS} consecutive days "
            "without department head approval.",
            ref,
        )
    return _rule("R7", True, "The consecutive-days limit is met.", ref)


def _r9_sick_certificate(request: LeaveRequest, days_counted: float) -> RuleResult:
    ref = "POL-02 §4.4"
    if request.leave_type == "SL" and days_counted > SICK_CERTIFICATE_THRESHOLD_DAYS:
        return _rule(
            "R9",
            False,
            "A medical certificate is needed within 3 working days of returning.",
            ref,
            blocking=False,
        )
    return _rule("R9", True, "No medical certificate is needed.", ref)


MAX_CASUAL_WITH_ANNUAL_DAYS = 3


def _is_working_day(day: date, holidays: Mapping[date, str]) -> bool:
    return day.weekday() < 5 and day not in holidays


def _touching(
    a: tuple[date, date], b: tuple[date, date], holidays: Mapping[date, str]
) -> bool:
    """True when two leave ranges overlap or no working day lies between them."""
    (_, first_end), (second_start, _) = sorted([a, b])
    if second_start <= first_end:
        return True
    gap = (first_end + timedelta(days=d) for d in range(1, (second_start - first_end).days))
    return not any(_is_working_day(day, holidays) for day in gap)


def _r8_casual_with_annual(
    request: LeaveRequest, days_counted: float, existing: Sequence[ExistingLeave],
    holidays: Mapping[date, str],
) -> RuleResult:
    ref = "POL-02 §4.5"
    ok = _rule("R8", True, "Casual and annual leave are not combined beyond 3 days.", ref)
    if request.leave_type not in ("AL", "CL"):
        return ok
    block = [(request.leave_type, request.start, request.end, days_counted)]
    candidates = [
        (e.leave_type, e.start, e.end, count_working_days(e.start, e.end, holidays).days)
        for e in existing
        if e.leave_type in ("AL", "CL")
    ]
    grew = True
    while grew:
        grew = False
        for item in list(candidates):
            _, start, end, _ = item
            if any(_touching((start, end), (b[1], b[2]), holidays) for b in block):
                block.append(item)
                candidates.remove(item)
                grew = True
    types = {leave_type for leave_type, *_ in block}
    total = sum(days for *_, days in block)
    if types == {"AL", "CL"} and total > MAX_CASUAL_WITH_ANNUAL_DAYS:
        return _rule(
            "R8",
            False,
            f"Casual leave combined with annual leave is limited to "
            f"{MAX_CASUAL_WITH_ANNUAL_DAYS} consecutive days; this would be {total:g}.",
            ref,
        )
    return ok


def _r10_overlap(request: LeaveRequest, existing: Sequence[ExistingLeave]) -> RuleResult:
    ref = "POL-02 §4.6"
    for other in existing:
        if request.start <= other.end and other.start <= request.end:
            return _rule(
                "R10",
                False,
                f"The dates overlap an existing {other.leave_type} request "
                f"({other.start} to {other.end}).",
                ref,
            )
    return _rule("R10", True, "No overlap with existing requests.", ref)


def check_eligibility(
    request: LeaveRequest,
    employee: EmployeeContext,
    today: date,
    holidays: Mapping[date, str],
    existing: Sequence[ExistingLeave] = (),
) -> EligibilityResult:
    if request.end < request.start:
        days_counted = 0.0
    else:
        days_counted = count_working_days(
            request.start, request.end, holidays, request.start_half, request.end_half
        ).days
    rules: list[RuleResult] = [
        _r1_date_range(request, today),
        _r2_days_counted(days_counted),
        _r3_leave_type(request, employee),
        _r4_probation(employee, days_counted),
        _r5_balance(employee, days_counted),
        _r6_notice(request, days_counted, today, holidays),
        _r7_consecutive(request),
        _r8_casual_with_annual(request, days_counted, existing, holidays),
        _r9_sick_certificate(request, days_counted),
        _r10_overlap(request, existing),
    ]
    lop_days = max(0.0, days_counted - employee.available_balance)
    return EligibilityResult(
        eligible=all(r.passed or not r.blocking for r in rules),
        days_counted=days_counted,
        balance_after=max(0.0, employee.available_balance - days_counted),
        lop_days=lop_days,
        rules=tuple(rules),
    )

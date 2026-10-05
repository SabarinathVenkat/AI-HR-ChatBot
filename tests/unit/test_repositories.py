"""Repository behavior over the seeded demo database (see app/db/seed.py).

Seeded cast (ids): 1 Meera Nair (hr_admin), 2 Arjun Rao and 3 Kavya Iyer (managers, report to 1),
4 Ravi Kumar, 5 Divya Menon, 6 Sanjay Patel (probation) report to 2; 7 Priya Shankar,
8 Karthik Raja (probation), 9 Ananya Das report to 3; 10 Vikram Singh (manager, no reports).
"""
from datetime import date

from app.db import repositories as repo


def test_get_employee_returns_profile_fields(db):
    employee = repo.get_employee(db, 4)

    assert employee.name == "Ravi Kumar"
    assert employee.role == "employee"
    assert employee.status == "confirmed"
    assert employee.manager_id == 2


def test_get_employee_returns_none_for_an_unknown_id(db):
    assert repo.get_employee(db, 999) is None


def test_get_employee_by_email_is_case_insensitive(db):
    assert repo.get_employee_by_email(db, "RAVI.KUMAR@example-ideas2it.invalid").id == 4


def balances(db, employee_id):
    return {b.leave_type: b for b in repo.get_leave_balances(db, employee_id, year=2026)}


def test_long_serving_employee_balances_follow_accrual_and_usage(db):
    # Ravi: AL 9 months x 1.5 = 13.5 accrued + 3 carried - 4.5 used = 12.
    b = balances(db, 4)

    assert b["AL"].available == 12
    assert b["CL"].available == 4  # 6 - 2 used
    assert b["SL"].available == 7  # 8 - 1 used


def test_carry_forward_is_included_in_the_available_balance(db):
    # Ananya: 13.5 accrued + 10 carried - 2 used.
    assert balances(db, 9)["AL"].available == 21.5


def test_probationer_balances_are_prorated_from_the_joining_month(db):
    # Sanjay joined 8 Jun (on or before the 15th): AL Jun-Sep = 4 months = 6.
    # CL 6 x 7/12 = 3.5; SL 8 x 7/12 = 4.67 rounded up to 5.
    b = balances(db, 6)

    assert (b["AL"].available, b["CL"].available, b["SL"].available) == (6, 3.5, 5)


def test_new_joiner_after_the_15th_has_no_annual_leave_yet(db):
    # Karthik joined 21 Sep: accrual starts in October, none complete on 2 Oct.
    b = balances(db, 8)

    assert (b["AL"].available, b["CL"].available, b["SL"].available) == (0, 1.5, 2)


def test_pending_requests_are_reported_separately(db):
    # Divya has a pending 3-day annual leave request.
    b = balances(db, 5)["AL"]

    assert b.available == 7.5  # 13.5 accrued - 6 used
    assert b.pending == 3


def test_holidays_for_a_year_are_returned_by_date(db):
    holidays = repo.get_holidays(db, 2026)

    assert len(holidays) == 12
    assert holidays[date(2026, 1, 26)] == "Republic Day"
    assert repo.get_holidays(db, 2027) == {}


def test_own_requests_never_include_other_employees(db):
    mine = repo.list_own_requests(db, employee_id=5)

    assert [(r.leave_type, r.status, r.days_counted) for r in mine] == [("AL", "pending", 3)]


def test_own_requests_can_be_filtered_by_status(db):
    assert repo.list_own_requests(db, 4, status="pending") == []
    assert len(repo.list_own_requests(db, 4, status="approved")) == 1


def test_manager_sees_requests_of_direct_reports_only(db):
    team = repo.list_team_requests(db, manager_id=2)

    # Arjun manages Ravi (4), Divya (5), Sanjay (6). Priya (7) reports to Kavya.
    assert {r.employee_id for r in team} == {4, 5, 6}


def test_manager_pending_approvals_are_filtered_by_status(db):
    pending = repo.list_team_requests(db, manager_id=2, status="pending")

    assert {r.employee_id for r in pending} == {5, 6}


def test_a_manager_with_no_reports_sees_nothing(db):
    assert repo.list_team_requests(db, manager_id=10) == []


def test_a_non_manager_id_sees_nothing_as_a_manager(db):
    assert repo.list_team_requests(db, manager_id=4) == []


def test_team_member_lookup_only_succeeds_for_direct_reports(db):
    assert repo.get_team_member(db, manager_id=2, employee_id=4).name == "Ravi Kumar"
    assert repo.get_team_member(db, manager_id=2, employee_id=7) is None  # other team
    assert repo.get_team_member(db, manager_id=3, employee_id=4) is None
    assert repo.get_team_member(db, manager_id=2, employee_id=2) is None  # not their own report


def test_active_leave_for_overlap_checks_covers_pending_and_approved_only(db):
    active = repo.list_active_leave(db, employee_id=4)

    assert [(a.leave_type, a.start, a.end) for a in active] == [
        ("AL", date(2026, 12, 21), date(2026, 12, 23))
    ]

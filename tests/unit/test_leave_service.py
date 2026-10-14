"""The leave request workflow: prepare a draft, confirm it, cancel it, cancel a request.

Seeded cast: see tests/unit/test_repositories.py. Today is 2026-10-02. Ravi (4) has 12 annual days
available and an approved request on 2026-12-21..23 (request id 2).
"""
from datetime import date, datetime, timedelta, timezone


from app.services import leave as svc
from app.tools.context import ToolContext

TODAY = date(2026, 10, 2)
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


def ctx_for(db, employee_id=4, role="employee") -> ToolContext:
    return ToolContext(conn=db, employee_id=employee_id, role=role, trace_id="t-1", today=TODAY)


def prepare(db, employee_id=4, leave_type="AL", start=date(2026, 11, 2), end=date(2026, 11, 6), now=NOW):
    return svc.prepare_request(ctx_for(db, employee_id), leave_type, start, end, now=now)


def request_count(db, employee_id=4) -> int:
    return db.execute("SELECT count(*) FROM leave_requests WHERE employee_id = ?", (employee_id,)).fetchone()[0]


def test_an_eligible_request_becomes_a_draft_awaiting_confirmation(db):
    result = prepare(db)

    assert result.eligible and result.draft_id
    assert (result.days_counted, result.balance_after, result.lop_days) == (5, 7, 0)
    assert request_count(db) == 1  # preparing does not submit: only the seeded approved request


def test_a_blocked_request_creates_no_draft_and_explains_why(db):
    result = prepare(db, employee_id=6, start=date(2026, 11, 2), end=date(2026, 11, 13))  # probation

    assert not result.eligible
    assert result.draft_id is None
    assert any(r.rule_id == "R4" and not r.passed for r in result.rules)
    assert db.execute("SELECT count(*) FROM leave_drafts").fetchone()[0] == 0


def test_a_new_draft_replaces_the_previous_open_one(db):
    first = prepare(db)
    second = prepare(db, start=date(2026, 11, 9), end=date(2026, 11, 10))

    assert svc.confirm_draft(ctx_for(db), first.draft_id, now=NOW).outcome == "not_found"
    assert svc.confirm_draft(ctx_for(db), second.draft_id, now=NOW).outcome == "ok"


def test_confirming_a_draft_submits_a_pending_request(db):
    draft = prepare(db)

    result = svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW)

    assert result.outcome == "ok" and result.request_id
    row = db.execute("SELECT * FROM leave_requests WHERE id = ?", (result.request_id,)).fetchone()
    assert (row["employee_id"], row["leave_type"], row["status"], row["days_counted"]) == (4, "AL", "pending", 5)
    assert (row["start_date"], row["end_date"]) == ("2026-11-02", "2026-11-06")


def test_confirming_twice_returns_the_same_request_and_creates_only_one(db):
    draft = prepare(db)

    first = svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW)
    second = svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW)

    assert second.outcome == "already_submitted"
    assert second.request_id == first.request_id
    assert request_count(db) == 2  # the seeded approved request plus one new


def test_a_draft_expires_after_thirty_minutes(db):
    draft = prepare(db)

    result = svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW + timedelta(minutes=31))

    assert result.outcome == "expired"
    assert request_count(db) == 1


def test_a_draft_is_still_valid_just_before_it_expires(db):
    draft = prepare(db)

    assert svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW + timedelta(minutes=29)).outcome == "ok"


def test_nobody_can_confirm_someone_elses_draft(db):
    draft = prepare(db, employee_id=4)

    result = svc.confirm_draft(ctx_for(db, 5), draft.draft_id, now=NOW)

    assert result.outcome == "not_found"
    assert request_count(db, 5) == 1  # only Divya's seeded request


def test_confirmation_rechecks_eligibility_against_current_data(db):
    draft = prepare(db)
    # Meanwhile an overlapping request is submitted another way.
    db.execute(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days_counted,"
        " status, created_at) VALUES (4, 'AL', '2026-11-04', '2026-11-04', 1, 'pending', '2026-10-02T09:01:00')"
    )
    db.commit()

    result = svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW)

    assert result.outcome == "no_longer_eligible"
    assert any(r.rule_id == "R10" and not r.passed for r in result.rules)
    assert request_count(db) == 2  # seeded approved + the interloper, nothing new


def test_cancelling_a_draft_prevents_confirmation(db):
    draft = prepare(db)

    assert svc.cancel_draft(ctx_for(db), draft.draft_id) is True
    assert svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW).outcome == "not_found"


def test_cancelling_someone_elses_draft_does_nothing(db):
    draft = prepare(db, employee_id=4)

    assert svc.cancel_draft(ctx_for(db, 5), draft.draft_id) is False
    assert svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW).outcome == "ok"


def test_submitting_and_cancelling_are_audited(db):
    draft = prepare(db)
    svc.confirm_draft(ctx_for(db), draft.draft_id, now=NOW)

    actions = [r["action"] for r in db.execute("SELECT action FROM audit_log ORDER BY id")]
    assert "leave_submitted" in actions


def test_an_employee_can_cancel_their_own_pending_request(db):
    # Divya's seeded request 1 is pending.
    result = svc.cancel_request(ctx_for(db, 5), 1)

    assert result == "ok"
    assert db.execute("SELECT status FROM leave_requests WHERE id = 1").fetchone()[0] == "cancelled"


def test_cancelling_an_approved_future_request_gives_the_days_back(db):
    # Ravi's approved 3 days (21-23 Dec) are counted as used: 4.5 used.
    before = db.execute("SELECT used FROM leave_balances WHERE employee_id = 4 AND leave_type = 'AL'").fetchone()[0]

    assert svc.cancel_request(ctx_for(db, 4), 2) == "ok"

    after = db.execute("SELECT used FROM leave_balances WHERE employee_id = 4 AND leave_type = 'AL'").fetchone()[0]
    assert (before, after) == (4.5, 1.5)


def test_an_approved_request_that_has_started_cannot_be_cancelled(db):
    db.execute("UPDATE leave_requests SET start_date = '2026-10-01', end_date = '2026-10-03' WHERE id = 2")
    db.commit()

    assert svc.cancel_request(ctx_for(db, 4), 2) == "not_cancellable"


def test_nobody_can_cancel_someone_elses_request(db):
    assert svc.cancel_request(ctx_for(db, 4), 1) == "not_found"  # request 1 is Divya's


def test_an_already_cancelled_request_cannot_be_cancelled_again(db):
    svc.cancel_request(ctx_for(db, 5), 1)

    assert svc.cancel_request(ctx_for(db, 5), 1) == "not_cancellable"


def test_the_model_has_no_tool_that_submits_leave(db):
    from app.tools.registry import tools_for_role

    names = {t.name for t in tools_for_role("employee")} | {t.name for t in tools_for_role("manager")}

    assert {"prepare_leave_request", "prepare_cancel_request"} <= names
    # The model may only prepare drafts. Anything that submits, confirms or cancels is out of its reach.
    acting = {n for n in names if "submit" in n or "confirm" in n or "cancel" in n}
    assert all(n.startswith("prepare_") for n in acting)


# --- Cancelling a request through a draft (chat): prepare, then confirm ------------------------

def used_al(db, employee_id=4) -> float:
    return db.execute(
        "SELECT used FROM leave_balances WHERE employee_id = ? AND leave_type = 'AL'", (employee_id,)
    ).fetchone()[0]


def request_status(db, request_id) -> str:
    return db.execute("SELECT status FROM leave_requests WHERE id = ?", (request_id,)).fetchone()[0]


def test_preparing_a_cancellation_stores_a_draft_and_cancels_nothing(db):
    result = svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    assert result.outcome == "ok" and result.draft_id
    assert (result.leave_type, result.start, result.end, result.days) == (
        "AL", date(2026, 12, 21), date(2026, 12, 23), 3)
    assert request_status(db, 2) == "approved"
    assert used_al(db) == 4.5


def test_confirming_a_cancellation_cancels_the_request_and_gives_the_days_back(db):
    draft = svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    assert svc.confirm_cancel_draft(ctx_for(db), draft.draft_id, now=NOW) == "ok"

    assert request_status(db, 2) == "cancelled"
    assert used_al(db) == 1.5


def test_a_pending_request_can_be_cancelled_through_a_draft(db):
    draft = svc.prepare_cancel(ctx_for(db, 5), 1, now=NOW)  # the seeded pending request of employee 5

    assert svc.confirm_cancel_draft(ctx_for(db, 5), draft.draft_id, now=NOW) == "ok"
    assert request_status(db, 1) == "cancelled"


def test_someone_elses_request_cannot_be_prepared_for_cancellation(db):
    result = svc.prepare_cancel(ctx_for(db, 5), 2, now=NOW)  # request 2 belongs to employee 4

    assert result.outcome == "not_found" and result.draft_id is None
    assert db.execute("SELECT count(*) FROM cancel_drafts").fetchone()[0] == 0


def test_a_request_that_has_started_cannot_be_prepared_for_cancellation(db):
    db.execute("UPDATE leave_requests SET start_date = '2026-10-01', end_date = '2026-10-03' WHERE id = 2")
    db.commit()

    result = svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    assert result.outcome == "not_cancellable" and result.draft_id is None


def test_an_already_cancelled_request_cannot_be_prepared_again(db):
    svc.cancel_request(ctx_for(db), 2)

    assert svc.prepare_cancel(ctx_for(db), 2, now=NOW).outcome == "not_cancellable"


def test_an_unknown_request_id_is_not_found(db):
    assert svc.prepare_cancel(ctx_for(db), 999, now=NOW).outcome == "not_found"


def test_a_cancellation_draft_expires(db):
    draft = svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    later = NOW + svc.DRAFT_LIFETIME + timedelta(seconds=1)

    assert svc.confirm_cancel_draft(ctx_for(db), draft.draft_id, now=later) == "expired"
    assert request_status(db, 2) == "approved"


def test_confirming_rechecks_that_the_request_can_still_be_cancelled(db):
    draft = svc.prepare_cancel(ctx_for(db), 2, now=NOW)
    svc.cancel_request(ctx_for(db), 2)  # cancelled in the meantime, e.g. with the Cancel button
    used_after_first_cancel = used_al(db)

    assert svc.confirm_cancel_draft(ctx_for(db), draft.draft_id, now=NOW) == "not_cancellable"
    assert used_al(db) == used_after_first_cancel  # the days are not given back twice


def test_someone_elses_cancellation_draft_cannot_be_confirmed(db):
    draft = svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    assert svc.confirm_cancel_draft(ctx_for(db, 5), draft.draft_id, now=NOW) == "not_found"
    assert request_status(db, 2) == "approved"


def test_a_cancellation_draft_can_only_be_confirmed_once(db):
    draft = svc.prepare_cancel(ctx_for(db), 2, now=NOW)
    svc.confirm_cancel_draft(ctx_for(db), draft.draft_id, now=NOW)

    assert svc.confirm_cancel_draft(ctx_for(db), draft.draft_id, now=NOW) == "not_found"
    assert used_al(db) == 1.5


def test_a_declined_cancellation_draft_cancels_nothing(db):
    draft = svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    assert svc.cancel_cancel_draft(ctx_for(db), draft.draft_id) is True
    assert svc.confirm_cancel_draft(ctx_for(db), draft.draft_id, now=NOW) == "not_found"
    assert request_status(db, 2) == "approved"


def test_a_new_leave_draft_replaces_an_open_cancellation_draft(db):
    cancel = svc.prepare_cancel(ctx_for(db), 2, now=NOW)
    leave = prepare(db)

    assert svc.confirm_cancel_draft(ctx_for(db), cancel.draft_id, now=NOW) == "not_found"
    assert svc.confirm_draft(ctx_for(db), leave.draft_id, now=NOW).outcome == "ok"


def test_a_new_cancellation_draft_replaces_an_open_leave_draft(db):
    leave = prepare(db)
    cancel = svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    assert svc.confirm_draft(ctx_for(db), leave.draft_id, now=NOW).outcome == "not_found"
    assert svc.confirm_cancel_draft(ctx_for(db), cancel.draft_id, now=NOW) == "ok"


def test_a_new_cancellation_draft_replaces_the_previous_one(db):
    first = svc.prepare_cancel(ctx_for(db), 2, now=NOW)
    svc.prepare_cancel(ctx_for(db), 2, now=NOW)

    assert svc.confirm_cancel_draft(ctx_for(db), first.draft_id, now=NOW) == "not_found"


def test_a_confirmed_cancellation_is_audited(db):
    draft = svc.prepare_cancel(ctx_for(db), 2, now=NOW)
    svc.confirm_cancel_draft(ctx_for(db), draft.draft_id, now=NOW)

    actions = [r["action"] for r in db.execute("SELECT action FROM audit_log ORDER BY id")]
    assert "leave_cancelled" in actions

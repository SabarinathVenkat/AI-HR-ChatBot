"""Leave endpoints, role gating and manager decisions.

Seeded request ids: 1 Divya AL pending (3 days), 2 Ravi AL approved, 3 Priya CL approved,
4 Sanjay CL pending. Managers: Arjun (2) manages Ravi, Divya, Sanjay; Kavya (3) manages Priya.
"""
from tests.integration.conftest import auth_headers


def test_health_is_public(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_leave_balance_returns_the_callers_balances(client):
    response = client.get("/leave/balance", headers=auth_headers(client, "Ravi Kumar"))

    balances = {b["leave_type"]: b for b in response.json()["balances"]}
    assert balances["AL"]["available"] == 12


def test_leave_balance_requires_authentication(client):
    assert client.get("/leave/balance").status_code == 401


def test_own_requests_are_listed(client):
    response = client.get("/leave/requests", headers=auth_headers(client, "Divya Menon"))

    assert [(r["id"], r["status"]) for r in response.json()["requests"]] == [(1, "pending")]


def test_team_scope_is_refused_for_employees(client):
    response = client.get(
        "/leave/requests", params={"scope": "team"}, headers=auth_headers(client, "Ravi Kumar")
    )

    assert response.status_code == 403


def test_managers_can_list_their_teams_requests(client):
    response = client.get(
        "/leave/requests", params={"scope": "team"}, headers=auth_headers(client, "Arjun Rao")
    )

    assert {r["id"] for r in response.json()["requests"]} == {1, 2, 4}


def approve(client, who, request_id, decision="approve", note=None):
    body = {"decision": decision}
    if note:
        body["note"] = note
    return client.post(
        f"/leave/requests/{request_id}/decision", json=body, headers=auth_headers(client, who)
    )


def test_a_manager_approves_a_direct_reports_pending_request(client):
    response = approve(client, "Arjun Rao", 1)

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    balance = client.get("/leave/balance", headers=auth_headers(client, "Divya Menon")).json()
    al = {b["leave_type"]: b for b in balance["balances"]}["AL"]
    assert (al["used"], al["pending"], al["available"]) == (9, 0, 4.5)


def test_rejecting_a_request_keeps_the_balance_and_stores_the_note(client, api_db):
    response = approve(client, "Arjun Rao", 1, decision="reject", note="Release week")

    assert response.json()["status"] == "rejected"
    row = api_db.execute("SELECT decided_by, decision_note FROM leave_requests WHERE id = 1").fetchone()
    assert (row["decided_by"], row["decision_note"]) == (2, "Release week")
    al = {
        b["leave_type"]: b
        for b in client.get("/leave/balance", headers=auth_headers(client, "Divya Menon")).json()["balances"]
    }["AL"]
    assert (al["used"], al["pending"], al["available"]) == (6, 0, 7.5)


def test_a_manager_cannot_decide_another_teams_request(client):
    # Request 3 belongs to Priya, who reports to Kavya. The response must not reveal it exists.
    assert approve(client, "Arjun Rao", 3).status_code == 404


def test_employees_cannot_decide_requests(client):
    assert approve(client, "Ravi Kumar", 1).status_code == 403


def test_a_request_that_is_not_pending_cannot_be_decided_again(client):
    assert approve(client, "Arjun Rao", 1).status_code == 200

    assert approve(client, "Arjun Rao", 1).status_code == 409
    assert approve(client, "Arjun Rao", 2).status_code == 409  # already approved in the seed


def test_an_unknown_request_returns_404(client):
    assert approve(client, "Arjun Rao", 999).status_code == 404


def test_an_invalid_decision_value_is_rejected(client):
    assert approve(client, "Arjun Rao", 1, decision="maybe").status_code == 422


def test_decisions_are_audited(client, api_db):
    approve(client, "Arjun Rao", 1, note="OK")

    row = api_db.execute("SELECT actor_id, action FROM audit_log WHERE action = 'leave_decision'").fetchone()
    assert (row["actor_id"], row["action"]) == (2, "leave_decision")


# --- confirming drafts and cancelling ---------------------------------------------------------

from datetime import date  # noqa: E402

from app.services import leave as leave_service  # noqa: E402
from app.tools.context import ToolContext  # noqa: E402


def make_draft(api_db, clock, employee_id=4, start=date(2026, 11, 2), end=date(2026, 11, 6)):
    ctx = ToolContext(conn=api_db, employee_id=employee_id, role="employee", trace_id="t",
                      today=clock.current.date())
    return leave_service.prepare_request(ctx, "AL", start, end, now=clock.current).draft_id


def confirm(client, who, draft_id):
    return client.post(f"/leave/drafts/{draft_id}/confirm", headers=auth_headers(client, who))


def test_confirming_a_draft_submits_a_request_the_manager_can_see(client, api_db, clock):
    draft_id = make_draft(api_db, clock)

    response = confirm(client, "Ravi Kumar", draft_id)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    mine = client.get("/leave/requests", headers=auth_headers(client, "Ravi Kumar")).json()["requests"]
    assert body["request_id"] in {r["id"] for r in mine}
    team = client.get("/leave/requests", params={"scope": "team"}, headers=auth_headers(client, "Arjun Rao"))
    assert body["request_id"] in {r["id"] for r in team.json()["requests"]}


def test_confirming_twice_is_safe(client, api_db, clock):
    draft_id = make_draft(api_db, clock)

    first = confirm(client, "Ravi Kumar", draft_id).json()
    second = confirm(client, "Ravi Kumar", draft_id)

    assert second.status_code == 200
    assert second.json() == {"status": "already_submitted", "request_id": first["request_id"]}


def test_confirming_requires_authentication(client, api_db, clock):
    draft_id = make_draft(api_db, clock)

    assert client.post(f"/leave/drafts/{draft_id}/confirm").status_code == 401


def test_someone_elses_draft_looks_like_it_does_not_exist(client, api_db, clock):
    draft_id = make_draft(api_db, clock, employee_id=4)

    assert confirm(client, "Divya Menon", draft_id).status_code == 404


def test_an_expired_draft_cannot_be_confirmed(client, api_db, clock):
    draft_id = make_draft(api_db, clock)
    headers = auth_headers(client, "Ravi Kumar")
    clock.advance(minutes=31)

    response = client.post(f"/leave/drafts/{draft_id}/confirm", headers=headers)

    assert response.status_code == 410


def test_a_draft_that_is_no_longer_allowed_returns_the_reasons(client, api_db, clock):
    draft_id = make_draft(api_db, clock)
    api_db.execute(
        "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, days_counted,"
        " status, created_at) VALUES (4, 'AL', '2026-11-04', '2026-11-04', 1, 'pending', '2026-10-02T09:01:00')"
    )
    api_db.commit()

    response = confirm(client, "Ravi Kumar", draft_id)

    assert response.status_code == 409
    assert any(r["rule_id"] == "R10" and not r["passed"] for r in response.json()["rules"])


def test_cancelling_a_draft_prevents_confirmation(client, api_db, clock):
    draft_id = make_draft(api_db, clock)
    headers = auth_headers(client, "Ravi Kumar")

    cancelled = client.post(f"/leave/drafts/{draft_id}/cancel", headers=headers)
    confirmed = client.post(f"/leave/drafts/{draft_id}/confirm", headers=headers)

    assert cancelled.status_code == 200
    assert confirmed.status_code == 404


def test_an_employee_cancels_their_own_pending_request(client):
    response = client.post("/leave/requests/1/cancel", headers=auth_headers(client, "Divya Menon"))

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancelling_someone_elses_request_is_a_404(client):
    assert client.post("/leave/requests/1/cancel", headers=auth_headers(client, "Ravi Kumar")).status_code == 404


def test_cancelling_an_approved_upcoming_request_restores_the_balance(client):
    headers = auth_headers(client, "Ravi Kumar")

    assert client.post("/leave/requests/2/cancel", headers=headers).status_code == 200

    al = {b["leave_type"]: b for b in client.get("/leave/balance", headers=headers).json()["balances"]}["AL"]
    assert al["available"] == 15  # 12 plus the 3 days given back


def test_a_request_cannot_be_cancelled_twice(client):
    headers = auth_headers(client, "Divya Menon")
    client.post("/leave/requests/1/cancel", headers=headers)

    assert client.post("/leave/requests/1/cancel", headers=headers).status_code == 409


def test_the_whole_journey_from_draft_to_an_approved_balance(client, api_db, clock):
    draft_id = make_draft(api_db, clock)
    request_id = confirm(client, "Ravi Kumar", draft_id).json()["request_id"]

    approved = approve(client, "Arjun Rao", request_id)

    assert approved.status_code == 200
    al = {b["leave_type"]: b for b in client.get("/leave/balance", headers=auth_headers(client, "Ravi Kumar")).json()["balances"]}["AL"]
    assert (al["used"], al["pending"], al["available"]) == (9.5, 0, 7)

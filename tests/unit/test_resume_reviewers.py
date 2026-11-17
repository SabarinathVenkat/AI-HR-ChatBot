"""Who reviews a submitted resume: the Competency Lead and RMG both can, and RMG alone when the associate has no lead."""
import pytest

from app.rmg.resume.people import assign_role
from app.rmg.resume.service import ServiceError
from tests.unit.test_resume_service import (  # noqa: F401  (fixtures and helpers)
    HEAD, LEAD, RAVI, SANJAY, STAFF, built, ready, submitted, world,
)


def messages(world_, who):
    return [n["message"] for n in world_.as_(who).notifications()]


def without_lead(world_):
    """Ravi's request is reviewed by RMG: he has no Competency Lead."""
    world_.db.execute("UPDATE resume_requests SET lead_id = NULL WHERE id = ?", (world_.request_id,))
    world_.db.commit()


# --- both can approve --------------------------------------------------------------------------------------------------

def test_submitting_puts_the_resume_in_front_of_the_lead_and_the_whole_rmg_team(ready):  # noqa: F811
    submitted(ready)

    assert any("waiting for your review" in m for m in messages(ready, LEAD))
    for member in (STAFF, HEAD):
        assert any("waiting for review" in m for m in messages(ready, member)), member


def test_rmg_staff_can_approve_and_so_can_the_head(ready):  # noqa: F811
    submitted(ready)
    assert ready.as_(STAFF).decide(ready.request_id, "approve", "Fine by RMG")["status"] == "approved"

    ready.as_(RAVI).reopen(ready.request_id)
    ready.as_(RAVI).submit(ready.request_id)
    assert ready.as_(HEAD).decide(ready.request_id, "approve")["status"] == "approved"


def test_the_lead_can_still_approve(ready):  # noqa: F811
    submitted(ready)

    assert ready.as_(LEAD).decide(ready.request_id, "approve")["status"] == "approved"


def test_the_decision_remembers_who_made_it(ready):  # noqa: F811
    submitted(ready)

    ready.as_(STAFF).decide(ready.request_id, "approve")

    row = ready.db.execute("SELECT decided_by FROM resume_requests WHERE id = ?", (ready.request_id,)).fetchone()
    assert row["decided_by"] == ready.id_of(STAFF)


def test_another_lead_and_the_associate_still_cannot_decide(ready):  # noqa: F811
    assign_role(ready.db, ready.id_of("Arjun Rao"), "competency_lead")
    submitted(ready)

    for outsider in ("Arjun Rao", RAVI):
        with pytest.raises(ServiceError) as e:
            ready.as_(outsider).decide(ready.request_id, "approve")
        assert e.value.status in (403, 404)


def test_nobody_decides_before_it_is_submitted(ready):  # noqa: F811
    built(ready)

    with pytest.raises(ServiceError) as e:
        ready.as_(STAFF).decide(ready.request_id, "approve")
    assert e.value.code == "wrong_status"


def test_when_rmg_decides_the_lead_hears_about_it_and_so_does_the_associate(ready):  # noqa: F811
    submitted(ready)

    ready.as_(STAFF).decide(ready.request_id, "send_back", "Add the Kafka project")

    assert any("sent back" in m for m in messages(ready, RAVI))
    assert any("sent back" in m and "Shadrach" in m for m in messages(ready, LEAD))


def test_the_screen_is_told_rmg_may_decide_on_a_submitted_resume(ready):  # noqa: F811
    submitted(ready)

    assert ready.as_(STAFF).detail(ready.request_id)["can"]["decide"] is True
    assert ready.as_(LEAD).detail(ready.request_id)["can"]["decide"] is True
    assert ready.as_(RAVI).detail(ready.request_id)["can"]["decide"] is False


# --- no lead: RMG reviews ------------------------------------------------------------------------------------------------

def test_a_request_with_no_lead_goes_to_rmg_alone(ready):  # noqa: F811
    without_lead(ready)

    submitted(ready)

    assert any("waiting for review" in m for m in messages(ready, STAFF))
    assert messages(ready, LEAD) == [] or all("waiting for your review" not in m for m in messages(ready, LEAD))
    assert ready.as_(HEAD).decide(ready.request_id, "approve")["status"] == "approved"


def test_a_request_with_no_lead_says_rmg_reviews_it(ready):  # noqa: F811
    without_lead(ready)

    detail = ready.as_(RAVI).detail(ready.request_id)

    assert detail["lead"] == {"id": None, "name": "RMG team"} and detail["review_by"] == "RMG"
    assert ready.as_(RAVI).summaries("mine")[0]["lead"] == "RMG team"


def test_a_request_with_a_lead_says_the_lead_reviews_it(ready):  # noqa: F811
    detail = ready.as_(RAVI).detail(ready.request_id)

    assert detail["lead"]["name"] == LEAD and detail["review_by"] == "Competency Lead"


# --- the review queue --------------------------------------------------------------------------------------------------------------

def test_rmg_sees_every_submitted_resume_in_its_review_queue_and_nothing_still_being_written(ready):  # noqa: F811
    assert ready.as_(STAFF).summaries("review") == []  # tagged but not submitted
    submitted(ready)

    queue = ready.as_(STAFF).summaries("review")

    assert [r["status"] for r in queue] == ["submitted"] and queue[0]["associate"] == RAVI


def test_the_lead_sees_their_own_associates_in_the_review_queue(ready):  # noqa: F811
    submitted(ready)

    assert [r["associate"] for r in ready.as_(LEAD).summaries("review")] == [RAVI]


def test_a_lead_who_is_not_the_leads_associates_manager_does_not_see_the_request(ready):  # noqa: F811
    assign_role(ready.db, ready.id_of("Arjun Rao"), "competency_lead")
    submitted(ready)

    assert ready.as_("Arjun Rao").summaries("review") == []


def test_an_associate_cannot_open_the_review_queue(ready):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        ready.as_(SANJAY).summaries("review")
    assert e.value.status == 403

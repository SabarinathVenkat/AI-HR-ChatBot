"""A reviewer (the Competency Lead or RMG) can change a submitted resume, add a skill, and send it back with a note.

What a reviewer adds is marked with their name, so the associate can see what changed and who changed it.
"""
import io

import pytest
from docx import Document

from app.rmg.resume.chat import EditCommand
from app.rmg.resume.service import ServiceError
from app.rmg.resume.template import W, paragraph_text
from tests.unit.test_resume_service import LEAD, RAVI, STAFF, built, ready, submitted, world  # noqa: F401  (fixtures and helpers)


def resume_of(world_, who):
    return world_.as_(who).detail(world_.request_id)["resume"]


def all_lines(resume: dict) -> list[dict]:
    lines = [resume[k] for k in ("role_title", "summary") if resume.get(k)]
    lines += [i for g in resume["skill_groups"] for i in g["items"]]
    lines += resume["highlights"] + resume["certifications"]
    for p in resume["projects"]:
        lines += [x for x in [p.get("dates"), p.get("description")] if x] + p["bullets"]
    return lines


def line_with(resume: dict, text: str) -> dict:
    return next(i for i in all_lines(resume) if i["text"] == text)


def edit_highlight(world_, who, text="Built event-driven systems for large banks."):
    return world_.as_(who).edit(world_.request_id, EditCommand(action="set_text", path="highlights.0", text=text))


# --- who may edit ------------------------------------------------------------------------------------------------------

def test_the_lead_and_rmg_can_edit_a_resume_that_is_waiting_for_review(ready):  # noqa: F811
    submitted(ready)

    assert edit_highlight(ready, LEAD)["changed"] is True
    assert edit_highlight(ready, STAFF, "Built event-driven systems for large retail banks.")["changed"] is True
    assert "large retail banks" in resume_of(ready, RAVI)["highlights"][0]["text"]


def test_the_associate_still_cannot_edit_while_it_is_waiting_and_other_people_cannot_edit_at_all(ready):  # noqa: F811
    submitted(ready)

    with pytest.raises(ServiceError) as e:
        edit_highlight(ready, RAVI)
    assert e.value.status == 409
    with pytest.raises(ServiceError) as e:
        edit_highlight(ready, "Arjun Rao")
    assert e.value.status in (403, 404)


def test_nobody_edits_once_it_is_approved_and_a_reviewer_cannot_edit_before_it_is_submitted(ready):  # noqa: F811
    built(ready)
    with pytest.raises(ServiceError):
        edit_highlight(ready, LEAD)  # still the associate's to write

    ready.as_(RAVI).submit(ready.request_id)
    ready.as_(LEAD).decide(ready.request_id, "approve")
    with pytest.raises(ServiceError):
        edit_highlight(ready, LEAD)


def test_the_screen_is_told_who_may_edit_and_that_the_assistant_chat_is_the_associates_only(ready):  # noqa: F811
    built(ready)
    assert ready.as_(RAVI).detail(ready.request_id)["can"]["edit"] and ready.as_(RAVI).detail(ready.request_id)["can"]["chat"]
    ready.as_(RAVI).submit(ready.request_id)

    lead, associate = ready.as_(LEAD).detail(ready.request_id)["can"], ready.as_(RAVI).detail(ready.request_id)["can"]

    assert lead["edit"] is True and lead["chat"] is False
    assert associate["edit"] is False and associate["chat"] is False


def test_the_assistant_chat_is_not_for_reviewers(ready):  # noqa: F811
    submitted(ready)

    with pytest.raises(ServiceError) as e:
        ready.as_(LEAD).chat(ready.request_id, "make it shorter")
    assert e.value.status in (403, 409)


# --- marking what a reviewer added ---------------------------------------------------------------------------------------

def test_a_skill_the_lead_adds_is_marked_with_the_leads_name(ready):  # noqa: F811
    submitted(ready)

    ready.as_(LEAD).edit(ready.request_id, EditCommand(action="add_skill", text="Terraform", category="Infrastructure"))

    skill = line_with(resume_of(ready, RAVI), "Terraform")
    assert skill["origin"] == "user_added" and skill["by"] == "Veera"


def test_a_fact_a_certification_and_dates_added_by_rmg_carry_the_reviewers_name(ready):  # noqa: F811
    submitted(ready)
    rmg = ready.as_(STAFF)

    rmg.edit(ready.request_id, EditCommand(action="add_fact", project=None, text="Led the platform migration."))
    rmg.edit(ready.request_id, EditCommand(action="add_certification", text="Scrum Master"))
    rmg.edit(ready.request_id, EditCommand(action="add_dates", project=0, text="2020 - 2021"))

    resume = resume_of(ready, RAVI)
    for text in ("Led the platform migration.", "Scrum Master", "2020 - 2021"):
        assert line_with(resume, text)["by"] == "Shadrach", text


def test_wording_the_reviewer_changes_to_something_the_resume_does_not_support_is_marked_as_theirs(ready):  # noqa: F811
    submitted(ready)

    edit_highlight(ready, LEAD, "Built event-driven systems on Kubernetes at scale.")

    edited = resume_of(ready, RAVI)["highlights"][0]
    assert edited["origin"] == "user_added" and edited["by"] == "Veera"


def test_what_the_associate_added_earlier_stays_theirs_and_is_not_marked_as_the_reviewers(ready):  # noqa: F811
    ravi = built(ready)
    ravi.edit(ready.request_id, EditCommand(action="add_skill", text="Redis", category="Data"))
    ravi.submit(ready.request_id)

    ready.as_(LEAD).edit(ready.request_id, EditCommand(action="add_skill", text="Terraform", category="Infrastructure"))

    resume = resume_of(ready, RAVI)
    assert line_with(resume, "Redis").get("by") is None and line_with(resume, "Terraform")["by"] == "Veera"


# --- approving and sending back with the edits ----------------------------------------------------------------------------

def test_the_approved_resume_includes_what_the_reviewer_changed(ready):  # noqa: F811
    submitted(ready)
    ready.as_(LEAD).edit(ready.request_id, EditCommand(action="add_skill", text="Terraform", category="Infrastructure"))

    ready.as_(LEAD).decide(ready.request_id, "approve", "Added Terraform")

    name, data, is_draft = ready.as_(STAFF).download(ready.request_id)
    text = " ".join(paragraph_text(p) for p in Document(io.BytesIO(data)).element.body.iter(W + "p"))
    assert name.endswith("_FINAL.docx") and "Terraform" in text and is_draft is False


def test_sending_back_with_a_note_keeps_the_reviewers_edits_for_the_associate_to_see(ready):  # noqa: F811
    submitted(ready)
    ready.as_(LEAD).edit(ready.request_id, EditCommand(action="add_skill", text="Terraform", category="Infrastructure"))

    ready.as_(LEAD).decide(ready.request_id, "send_back", "I added Terraform; please add your Kafka project dates")

    detail = ready.as_(RAVI).detail(ready.request_id)
    assert detail["status"] == "changes_requested" and "Kafka project dates" in detail["decision_note"]
    assert line_with(detail["resume"], "Terraform")["by"] == "Veera" and detail["can"]["edit"] is True


def test_the_associate_can_then_change_it_and_their_own_edits_carry_no_reviewer_mark(ready):  # noqa: F811
    submitted(ready)
    ready.as_(LEAD).decide(ready.request_id, "send_back", "Please add a certification")

    ready.as_(RAVI).edit(ready.request_id, EditCommand(action="add_certification", text="Scrum Master"))

    assert line_with(resume_of(ready, RAVI), "Scrum Master").get("by") is None


def test_a_reviewers_edit_is_recorded_in_the_audit_trail_with_who_made_it(ready):  # noqa: F811
    submitted(ready)

    edit_highlight(ready, STAFF)

    row = ready.db.execute("SELECT actor_id, inputs_json FROM audit_log WHERE action = 'resume_edited' ORDER BY id DESC").fetchone()
    assert row["actor_id"] == ready.id_of(STAFF) and '"reviewer": true' in row["inputs_json"]

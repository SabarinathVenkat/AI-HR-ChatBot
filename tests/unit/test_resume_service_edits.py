"""Edits and chat on a draft, through the workflow service. Only the associate can edit, and only while it is editable."""
import pytest

from app.rmg.resume.chat import EditCommand
from app.rmg.resume.extract import ExtractionError
from app.rmg.resume.service import ResumeEngine, ServiceError
from tests.unit.test_resume_service import LEAD, RAVI, STAFF, World, built, code_of, ready, world  # noqa: F401  (fixtures)


def with_interpreter(source, command=None, error=None):
    def interpreter(message, resume):
        if error:
            raise error
        return command

    new = World(source.db, source.files, ResumeEngine(source.engine.deps, interpreter))
    new.request_id = source.request_id
    return new


def bullets(ravi, request_id, project=0):
    return [b["text"] for b in ravi.detail(request_id)["resume"]["projects"][project]["bullets"]]


def test_an_edit_changes_only_the_draft_and_can_be_undone(ready):  # noqa: F811
    ravi = built(ready)
    before = bullets(ravi, ready.request_id)

    result = ravi.edit(ready.request_id, EditCommand(action="remove", path="projects.0.bullets.0"))
    assert result["changed"] and bullets(ravi, ready.request_id) != before
    undone = ravi.edit(ready.request_id, EditCommand(action="undo"))

    assert undone["message"] == "Undone." and bullets(ravi, ready.request_id) == before
    assert ravi.edit(ready.request_id, EditCommand(action="undo"))["message"] == "There is nothing to undo."


def test_text_the_associate_types_that_the_resume_does_not_support_is_kept_and_marked_as_theirs(ready):  # noqa: F811
    ravi = built(ready)

    ravi.edit(ready.request_id, EditCommand(action="set_text", path="projects.0.bullets.0", text="Maintained the portal on Kubernetes."))

    detail = ravi.detail(ready.request_id)
    assert detail["resume"]["projects"][0]["bullets"][0]["origin"] == "user_added"
    assert any(e["kind"] == "added_by_you" for e in detail["changelog"]["entries"])


def test_a_bad_edit_is_a_clear_422_and_changes_nothing(ready):  # noqa: F811
    ravi = built(ready)

    with pytest.raises(ServiceError) as e:
        ravi.edit(ready.request_id, EditCommand(action="remove", path="projects.9.bullets.0"))

    assert (code_of(e), e.value.status) == ("edit_no_such_item", 422)


def test_only_the_associate_can_edit_and_only_while_it_is_editable(ready):  # noqa: F811
    built(ready)
    with pytest.raises(ServiceError) as e:
        ready.as_(STAFF).edit(ready.request_id, EditCommand(action="undo"))
    assert code_of(e) == "forbidden"
    ready.as_(RAVI).submit(ready.request_id)
    with pytest.raises(ServiceError) as e:
        ready.as_(RAVI).edit(ready.request_id, EditCommand(action="undo"))
    assert code_of(e) == "wrong_status"


def test_chat_runs_the_command_the_model_chose(ready):  # noqa: F811
    built(ready)
    chat_world = with_interpreter(ready, EditCommand(action="remove", path="projects.0.bullets.0", reply="Removed it."))

    result = chat_world.as_(RAVI).chat(ready.request_id, "drop the first bullet of the first project")

    assert result["changed"] and result["reply"] == "Removed it."


def test_chat_refuses_a_rewording_that_adds_a_claim_and_offers_to_add_it_as_their_own(ready):  # noqa: F811
    before = bullets(built(ready), ready.request_id)
    command = EditCommand(action="set_text", path="projects.0.bullets.0", text="Maintained the portal on Kubernetes.")

    result = with_interpreter(ready, command).as_(RAVI).chat(ready.request_id, "mention Kubernetes")

    assert not result["changed"] and "Kubernetes" in result["reply"] and "your own statement" in result["reply"]
    assert bullets(ready.as_(RAVI), ready.request_id) == before


def test_chat_can_add_a_fact_the_associate_states_as_theirs(ready):  # noqa: F811
    built(ready)
    command = EditCommand(action="add_fact", project=0, text="Administered Kubernetes clusters at a client site.", reply="Added.")

    result = with_interpreter(ready, command).as_(RAVI).chat(ready.request_id, "I also ran Kubernetes clusters")

    assert result["changed"] and "Administered Kubernetes clusters at a client site." in bullets(ready.as_(RAVI), ready.request_id)


def test_chat_explains_what_changed_from_the_change_log_without_changing_anything(ready):  # noqa: F811
    built(ready)
    ready.as_(RAVI).edit(ready.request_id, EditCommand(action="remove", path="projects.0.bullets.0"))

    result = with_interpreter(ready, EditCommand(action="explain")).as_(RAVI).chat(ready.request_id, "what did you change?")

    assert not result["changed"] and "dropped" in result["reply"] and "Changes:" in result["reply"]


def test_chat_survives_a_model_that_cannot_be_understood_and_an_unclear_request(ready):  # noqa: F811
    built(ready)

    unreadable = with_interpreter(ready, error=ExtractionError("invalid")).as_(RAVI).chat(ready.request_id, "???")
    unclear = with_interpreter(ready, EditCommand(action="none", reply="Which bullet do you mean?")).as_(RAVI).chat(ready.request_id, "fix it")

    assert not unreadable["changed"] and "another way" in unreadable["reply"]
    assert unclear["reply"] == "Which bullet do you mean?"


def test_chat_needs_an_interpreter_and_the_associate(ready):  # noqa: F811
    built(ready)
    with pytest.raises(ServiceError) as e:
        ready.as_(RAVI).chat(ready.request_id, "hello")  # the default engine has no interpreter
    assert (code_of(e), e.value.status) == ("chat_unavailable", 503)
    with pytest.raises(ServiceError) as e:
        with_interpreter(ready, EditCommand(action="undo")).as_(STAFF).chat(ready.request_id, "x")
    assert code_of(e) == "forbidden"


def test_a_submission_with_a_user_added_claim_is_allowed_because_it_is_marked_for_the_lead(ready):  # noqa: F811
    ravi = built(ready)
    ravi.edit(ready.request_id, EditCommand(action="add_fact", project=0, text="Ran Kubernetes clusters."))

    ravi.submit(ready.request_id)

    entries = ready.as_(LEAD).detail(ready.request_id)["changelog"]["entries"]
    assert any(e["kind"] == "added_by_you" for e in entries)


# --- skills ----------------------------------------------------------------------------------------------------------------

def skills_of(ravi, request_id):
    return [[i["text"] for i in g["items"]] for g in ravi.detail(request_id)["resume"]["skill_groups"]]


def test_the_associate_can_add_a_skill_and_it_counts_towards_the_score_and_is_marked_for_the_lead(ready):  # noqa: F811
    ravi = built(ready)
    before = ravi.detail(ready.request_id)["changelog"]["coverage"]
    assert "Spring Boot" in before["missing_required"]  # the demo job wants it and the sample resume lacks it

    result = ravi.edit(ready.request_id, EditCommand(action="add_skill", group=0, text="Spring Boot"))

    after = result["detail"]["changelog"]
    assert "Spring Boot" in skills_of(ravi, ready.request_id)[0]
    assert "Spring Boot" not in after["coverage"]["missing_required"]
    assert after["coverage"]["required_after"] > before["required_after"]  # the score moves up
    assert any(e["kind"] == "added_by_you" and "Spring Boot" in e["where"] for e in after["entries"])


def test_a_skill_can_be_edited_removed_and_the_change_undone(ready):  # noqa: F811
    ravi = built(ready)
    first = skills_of(ravi, ready.request_id)

    ravi.edit(ready.request_id, EditCommand(action="remove", path="skill_groups.0.items.0"))
    assert skills_of(ravi, ready.request_id)[0] == first[0][1:]
    ravi.edit(ready.request_id, EditCommand(action="undo"))
    assert skills_of(ravi, ready.request_id) == first
    ravi.edit(ready.request_id, EditCommand(action="set_text", path="skill_groups.0.items.0", text="Python 3"))
    assert skills_of(ravi, ready.request_id)[0][0] == "Python 3"


def test_a_duplicate_or_missing_skill_gives_a_clear_error_and_changes_nothing(ready):  # noqa: F811
    ravi = built(ready)
    existing = skills_of(ravi, ready.request_id)[0][0]

    with pytest.raises(ServiceError) as e:
        ravi.edit(ready.request_id, EditCommand(action="add_skill", group=0, text=existing.lower()))
    assert (e.value.code, e.value.status) == ("edit_duplicate", 422) and "already listed" in str(e.value)
    with pytest.raises(ServiceError) as e:
        ravi.edit(ready.request_id, EditCommand(action="add_skill", group=0))
    assert e.value.code == "edit_empty_text"


def test_chat_cannot_add_a_skill_even_if_the_model_asks_to(ready):  # noqa: F811
    built(ready)
    command = EditCommand(action="add_skill", group=0, text="Kubernetes")

    result = with_interpreter(ready, command).as_(RAVI).chat(ready.request_id, "I know Kubernetes")

    assert not result["changed"] and "Add a skill" in result["reply"]
    assert "Kubernetes" not in sum(skills_of(ready.as_(RAVI), ready.request_id), [])


def test_the_chat_prompt_tells_the_model_never_to_add_skills():
    from app.rmg.resume.chat import build_prompt
    from tests.unit.resume_fakes import RESUME

    prompt = build_prompt("anything", RESUME)

    assert "add_skill: NEVER use this" in prompt


# --- what the Word file cannot hold is said on screen ------------------------------------------------------------------------

def test_the_request_says_what_the_template_has_no_place_for(ready):  # noqa: F811
    ravi = built(ready)

    notes = ravi.detail(ready.request_id)["render_notes"]

    assert any("Work history" in n for n in notes)  # the sample template has no subheading to hang it under


def test_a_template_that_can_hold_everything_gives_no_notes(ready):  # noqa: F811
    from tests.unit.resume_templates import make_template
    from tests.unit.test_resume_service import HEAD, template_bytes

    ready.as_(HEAD).upload_template("full.docx", template_bytes(highlights_subheading="Professional summary and Key highlights"))
    ravi = ready.as_(RAVI)
    ravi.upload_resume(ready.request_id, "cv.txt", b"Ravi")
    ravi.build(ready.request_id, force=True)

    assert ravi.detail(ready.request_id)["render_notes"] == []
    assert make_template is not None


def test_before_anything_is_built_there_are_no_notes(ready):  # noqa: F811
    assert ready.as_(RAVI).detail(ready.request_id)["render_notes"] == []

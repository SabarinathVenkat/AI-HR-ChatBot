"""Draft-only edits to a resume. Every function returns a new Resume and never touches the original.

Text the associate types is theirs: if it is not supported by their original resume it is kept but marked as theirs
(user_added). Text the assistant writes must be grounded or it is refused.
"""
import pytest

from app.rmg.resume.edit import EditError, add_fact, move_bullet, move_project, remove_item, set_role_line, set_text
from app.rmg.resume.match import build_match_plan
from app.rmg.resume.model import MAX_BULLETS_PER_PROJECT, Item, Origin, Project
from tests.unit.resume_fakes import JD, RESUME

BASE = RESUME
PLAN = build_match_plan(BASE, JD.roles[0])  # Kubernetes is wanted but the resume does not have it
BULLET = "projects.1.bullets.0"  # "Wrote Java services."


def texts(resume, project):
    return [b.text for b in resume.projects[project].bullets]


# --- changing text -----------------------------------------------------------------------------------------

def test_a_grounded_rewording_keeps_its_source_and_is_marked_reworded():
    result = set_text(BASE, BASE, PLAN, BULLET, "Wrote Java services for payments.", by="user")

    item = result.projects[1].bullets[0]
    assert (item.text, item.origin, item.source) == ("Wrote Java services for payments.", Origin.REWORDED, "projects.1.bullets.0")


def test_putting_the_original_text_back_makes_it_original_again():
    changed = set_text(BASE, BASE, PLAN, BULLET, "Wrote Java services for payments.", by="user")

    restored = set_text(changed, BASE, PLAN, BULLET, "Wrote Java services.", by="user")

    assert restored.projects[1].bullets[0].origin is Origin.ORIGINAL


def test_when_the_associate_types_something_the_resume_does_not_support_it_is_kept_as_theirs():
    result = set_text(BASE, BASE, PLAN, BULLET, "Wrote Java services on Kubernetes.", by="user")

    item = result.projects[1].bullets[0]
    assert item.origin is Origin.USER_ADDED and item.source is None and "Kubernetes" in item.text


def test_when_the_assistant_writes_something_the_resume_does_not_support_it_is_refused_and_says_why():
    with pytest.raises(EditError) as e:
        set_text(BASE, BASE, PLAN, BULLET, "Wrote Java services on Kubernetes.", by="assistant")

    assert e.value.code == "ungrounded" and "Kubernetes" in str(e.value)


def test_an_item_the_associate_added_stays_theirs_when_edited():
    added = add_fact(BASE, 1, "Hands-on Kubernetes administration.")

    edited = set_text(added, BASE, PLAN, "projects.1.bullets.2", "Ran Kubernetes clusters.", by="assistant")

    assert edited.projects[1].bullets[2].origin is Origin.USER_ADDED


@pytest.mark.parametrize("path,text,code", [
    ("projects.9.bullets.0", "x ok", "no_such_item"), ("nonsense", "x ok", "no_such_item"),
    (BULLET, "   ", "empty_text"), (BULLET, "x" * 1300, "too_long"),
])
def test_bad_edits_are_refused_with_a_code(path, text, code):
    with pytest.raises(EditError) as e:
        set_text(BASE, BASE, PLAN, path, text, by="user")
    assert e.value.code == code


def test_editing_never_changes_the_resume_it_was_given():
    before = BASE.model_copy(deep=True)

    set_text(BASE, BASE, PLAN, BULLET, "Changed.", by="user")

    assert BASE == before


# --- removing and moving ---------------------------------------------------------------------------------------

def test_a_bullet_and_a_description_can_be_removed():
    result = remove_item(remove_item(BASE, BULLET), "projects.1.description")

    assert texts(result, 1) == ["Tuned SQL queries."] and result.projects[1].description is None


def test_removing_something_that_is_not_there_is_an_error():
    with pytest.raises(EditError) as e:
        remove_item(BASE, "projects.1.bullets.7")
    assert e.value.code == "no_such_item"


def test_a_project_can_be_moved_and_a_bad_position_is_refused():
    result = move_project(BASE, 1, 0)

    assert [p.name for p in result.projects] == ["Payments", "Intranet"]
    with pytest.raises(EditError):
        move_project(BASE, 0, 5)


def test_a_bullet_can_be_moved_inside_its_project():
    assert texts(move_bullet(BASE, 1, 1, 0), 1) == ["Tuned SQL queries.", "Wrote Java services."]
    with pytest.raises(EditError):
        move_bullet(BASE, 1, 0, 9)


# --- adding a fact the associate provides ------------------------------------------------------------------------

def test_a_fact_the_associate_provides_is_added_as_theirs_to_a_project_or_the_highlights():
    in_project = add_fact(BASE, 0, "Led the migration to SSO.")
    in_highlights = add_fact(BASE, None, "Mentored three juniors.")

    added = in_project.projects[0].bullets[-1]
    assert (added.origin, added.source, added.text) == (Origin.USER_ADDED, None, "Led the migration to SSO.")
    assert in_highlights.highlights[-1].origin is Origin.USER_ADDED


def test_a_project_that_is_full_cannot_take_another_bullet():
    full = BASE.model_copy(update={"projects": [Project(name="P", bullets=[
        Item(text=f"Bullet {i}.", origin=Origin.USER_ADDED) for i in range(MAX_BULLETS_PER_PROJECT)])]})

    with pytest.raises(EditError) as e:
        add_fact(full, 0, "One more.")
    assert e.value.code == "full"


def test_an_added_fact_needs_real_text_and_a_real_project():
    with pytest.raises(EditError):
        add_fact(BASE, 0, "  ")
    with pytest.raises(EditError):
        add_fact(BASE, 9, "Something true.")


# --- the role line ---------------------------------------------------------------------------------------------------

def test_the_role_line_can_be_changed_and_is_theirs_if_the_resume_does_not_support_it():
    supported = set_role_line(BASE, BASE, PLAN, "Senior Backend Engineer, Java", by="user")
    new = set_role_line(BASE, BASE, PLAN, "Principal Architect", by="user")

    assert supported.role_title.origin is Origin.REWORDED and supported.role_title.source == "title"
    assert new.role_title.origin is Origin.USER_ADDED


def test_the_assistant_cannot_give_the_associate_a_title_the_resume_does_not_support():
    with pytest.raises(EditError):
        set_role_line(BASE, BASE, PLAN, "Principal Architect", by="assistant")

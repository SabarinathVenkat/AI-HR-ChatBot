"""Start and end dates for a project: kept when the resume has them, offered when it does not, shown in the Word file only if present."""
import io

import pytest
from docx import Document

from app.rmg.resume.edit import EditError, add_dates_as, add_fact, move_bullet, remove_item, set_text
from app.rmg.resume.extract import ExtractedProject, ExtractedResume, to_resume
from app.rmg.resume.match import build_match_plan
from app.rmg.resume.model import Item, Origin, Project, Resume
from app.rmg.resume.render import render_resume
from app.rmg.resume.template import W, paragraph_text
from tests.unit.resume_fakes import JD
from tests.unit.resume_templates import make_template


def orig(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def resume(dates=True) -> Resume:
    return Resume(
        name="Anil Verma", skill_groups=[], highlights=[orig("A highlight.", "highlights.0")],
        projects=[Project(name="Payments", dates=orig("Jan 2022 – Mar 2023", "projects.0.dates") if dates else None,
                          description=orig("Built payments.", "projects.0.description"), bullets=[orig("Wrote Java services.", "projects.0.bullets.0"), orig("Tuned SQL.", "projects.0.bullets.1")])])


BASE = resume()
PLAN = build_match_plan(BASE, JD.roles[0])


# --- reading them ---------------------------------------------------------------------------------------------------

def test_the_dates_a_resume_gives_a_project_are_kept_as_its_own():
    extracted = ExtractedResume(name="A", projects=[ExtractedProject(name="Payments", dates="Jan 2022 – Mar 2023", bullets=["x"]),
                                                    ExtractedProject(name="Intranet", bullets=["y"])])

    projects = to_resume(extracted).projects

    assert (projects[0].dates.text, projects[0].dates.origin, projects[0].dates.source) == ("Jan 2022 – Mar 2023", Origin.ORIGINAL, "projects.0.dates")
    assert projects[1].dates is None


def test_dates_are_one_of_the_resumes_items_so_they_are_compared_and_listed_like_the_rest():
    assert ("projects.0.dates", BASE.projects[0].dates) in list(BASE.all_items())


# --- offering them when the resume has none --------------------------------------------------------------------------------

def test_the_associate_can_add_dates_to_a_project_that_has_none_and_they_are_marked_as_theirs():
    result = add_dates_as(resume(dates=False), 0, "2021 - 2022", by="user")

    dates = result.projects[0].dates
    assert (dates.text, dates.origin, dates.source) == ("2021 - 2022", Origin.USER_ADDED, None)


def test_the_assistant_may_not_add_dates_because_a_date_is_a_claim():
    with pytest.raises(EditError) as e:
        add_dates_as(resume(dates=False), 0, "2021 - 2022", by="assistant")
    assert e.value.code == "not_allowed"


def test_dates_cannot_be_added_to_a_project_that_does_not_exist_or_over_existing_dates():
    with pytest.raises(EditError) as e:
        add_dates_as(resume(), 5, "2021", by="user")
    assert e.value.code == "no_such_item"
    with pytest.raises(EditError) as e:
        add_dates_as(resume(), 0, "2021", by="user")
    assert e.value.code == "duplicate"


def test_blank_dates_are_refused():
    with pytest.raises(EditError) as e:
        add_dates_as(resume(dates=False), 0, "   ", by="user")
    assert e.value.code == "empty_text"


def test_dates_can_be_edited_and_removed_like_any_line():
    edited = set_text(BASE, BASE, PLAN, "projects.0.dates", "Jan 2022 – Mar 2024", by="user")  # a new year: not in the original
    removed = remove_item(BASE, "projects.0.dates")

    assert edited.projects[0].dates.text == "Jan 2022 – Mar 2024" and edited.projects[0].dates.origin is Origin.USER_ADDED
    assert removed.projects[0].dates is None and removed.projects[0].name == "Payments"


def test_other_edits_to_a_project_do_not_lose_its_dates():
    assert move_bullet(BASE, 0, 1, 0).projects[0].dates == BASE.projects[0].dates
    assert add_fact(BASE, 0, "A new fact.").projects[0].dates == BASE.projects[0].dates


# --- in the Word file ---------------------------------------------------------------------------------------------------------

def names_in_output(r: Resume) -> list[str]:
    out = io.BytesIO()
    make_template(highlights_subheading="Professional summary and Key highlights").save(out)
    doc = Document(io.BytesIO(render_resume(out.getvalue(), r).docx))
    return [paragraph_text(p) for p in doc.element.body.iter(W + "p") if paragraph_text(p).startswith("Payments")]


def test_the_dates_follow_the_project_name_in_the_word_file():
    assert names_in_output(resume()) == ["Payments (Jan 2022 – Mar 2023)"]


def test_a_project_with_no_dates_shows_just_its_name_so_nothing_empty_is_visible():
    assert names_in_output(resume(dates=False)) == ["Payments"]

"""The structured resume model: the one shape every resume-builder step agrees on.

Provenance is part of the model: an item either points to where it came from in the associate's resume, or it is
explicitly marked as typed in by the associate. A made-up item with no source cannot be constructed.
"""
import pytest
from pydantic import ValidationError

from app.rmg.resume.model import (
    MAX_ITEM_CHARS, MAX_PROJECTS, Education, Item, Job, Origin, Project, Resume, SkillGroup,
)


def original(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def make_resume(**overrides) -> Resume:
    data = dict(
        name="Anil Verma",
        role_title=original("Senior Backend Engineer", "title"),
        summary=original("Backend engineer with 8 years of experience.", "summary"),
        skill_groups=[
            SkillGroup(category="Backend", items=[original("Java", "skills.0.0"), original("Spring Boot", "skills.0.1")]),
            SkillGroup(category="Cloud", items=[original("AWS", "skills.1.0")]),
        ],
        education=[Education(degree="B.E. Computer Science", institution="Anna University", year="2015")],
        certifications=["AWS Certified Developer"],
        highlights=[original("Built event-driven microservices.", "summary")],
        jobs=[Job(company="Finwave", title="Senior Engineer", start="Mar 2020", end="Present")],
        projects=[
            Project(
                name="Payment Platform",
                description=original("Built payment workflows on Kafka.", "projects.0.description"),
                bullets=[original("Designed REST APIs.", "projects.0.bullets.0"),
                         original("Added tracing across 14 services.", "projects.0.bullets.1")],
            ),
        ],
    )
    data.update(overrides)
    return Resume(**data)


# --- the invariant: provenance ---------------------------------------------------------------

def test_an_original_item_must_say_where_it_came_from():
    with pytest.raises(ValidationError, match="source"):
        Item(text="Kubernetes", origin=Origin.ORIGINAL)


def test_a_reworded_item_must_say_which_original_it_came_from():
    with pytest.raises(ValidationError, match="source"):
        Item(text="Led a team", origin=Origin.REWORDED)
    assert Item(text="Led a team", origin=Origin.REWORDED, source="projects.0.bullets.2").source == "projects.0.bullets.2"


def test_a_user_added_item_has_no_source_because_it_is_not_in_the_original():
    item = Item(text="Kubernetes", origin=Origin.USER_ADDED)
    assert item.source is None
    with pytest.raises(ValidationError, match="source"):
        Item(text="Kubernetes", origin=Origin.USER_ADDED, source="skills.0.0")


# --- text hygiene and limits (resume text is untrusted input) --------------------------------

def test_text_is_trimmed():
    assert original("  Java  ", "skills.0.0").text == "Java"


@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_blank_text_is_rejected(blank):
    with pytest.raises(ValidationError):
        original(blank, "skills.0.0")


def test_a_very_long_item_is_rejected():
    with pytest.raises(ValidationError):
        original("x" * (MAX_ITEM_CHARS + 1), "summary")
    assert original("x" * MAX_ITEM_CHARS, "summary")


def test_the_candidate_name_cannot_be_blank():
    with pytest.raises(ValidationError):
        make_resume(name="  ")


def test_there_is_a_limit_on_the_number_of_projects():
    project = make_resume().projects[0]
    with pytest.raises(ValidationError):
        make_resume(projects=[project] * (MAX_PROJECTS + 1))


def test_unknown_fields_are_rejected_so_nothing_slips_in():
    with pytest.raises(ValidationError):
        Item(text="Java", origin=Origin.ORIGINAL, source="skills.0.0", confidence=0.9)
    with pytest.raises(ValidationError):
        make_resume(salary="secret")


# --- behaviour --------------------------------------------------------------------------------

def test_resumes_are_immutable_so_a_step_cannot_change_one_by_accident():
    resume = make_resume()
    with pytest.raises(ValidationError):
        resume.name = "Someone Else"


def test_a_resume_survives_a_json_round_trip():
    resume = make_resume()

    again = Resume.model_validate_json(resume.model_dump_json())

    assert again == resume


def test_every_text_item_can_be_listed_with_its_path():
    items = dict(make_resume().all_items())

    assert items["role_title"].text == "Senior Backend Engineer"
    assert items["summary"].text.startswith("Backend engineer")
    assert items["skill_groups.0.items.1"].text == "Spring Boot"
    assert items["skill_groups.1.items.0"].text == "AWS"
    assert items["highlights.0"].text == "Built event-driven microservices."
    assert items["projects.0.description"].text == "Built payment workflows on Kafka."
    assert items["projects.0.bullets.1"].text == "Added tracing across 14 services."


def test_items_without_a_role_title_or_summary_are_simply_skipped():
    items = dict(make_resume(role_title=None, summary=None).all_items())

    assert "role_title" not in items and "summary" not in items


def test_items_can_be_filtered_by_origin():
    resume = make_resume(highlights=[
        original("Built event-driven microservices.", "summary"),
        Item(text="Mentors junior engineers.", origin=Origin.USER_ADDED),
    ])

    added = resume.items_with_origin(Origin.USER_ADDED)

    assert [(path, item.text) for path, item in added] == [("highlights.1", "Mentors junior engineers.")]


def test_the_skills_can_be_read_as_a_flat_list():
    assert make_resume().skills_flat() == ["Java", "Spring Boot", "AWS"]

"""The grounding check: nothing in a tailored resume may be a claim the original resume does not support.

The tailoring model is not trusted. This check compares the tailored resume with the original, in code, and a fake skill
that someone (or something) slipped in must be caught. enforce_grounding then puts the original wording back.
"""
import pytest

from app.rmg.resume.grounding import check_grounding, enforce_grounding
from app.rmg.resume.jd import Role
from app.rmg.resume.match import build_match_plan
from app.rmg.resume.model import Item, Origin, Project, Resume, SkillGroup


def orig(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def reworded(text, source):
    return Item(text=text, origin=Origin.REWORDED, source=source)


ORIGINAL = Resume(
    name="Anil Verma",
    summary=orig("Backend engineer with 8 years of experience.", "summary"),
    skill_groups=[SkillGroup(category="Backend", items=[orig("Java", "skills.0.0"), orig("Spring Boot", "skills.0.1")])],
    projects=[Project(name="Payments", description=orig("Built payment workflows on Kafka.", "projects.0.description"),
                      bullets=[orig("Designed REST APIs for 14 partner systems.", "projects.0.bullets.0"),
                               orig("Added tracing across services.", "projects.0.bullets.1")])],
)
ROLE = Role(title="Java Developer", min_years=None, must_have=["Java", "Kubernetes"], nice_to_have=[])
PLAN = build_match_plan(ORIGINAL, ROLE)  # Kubernetes is required by the JD but absent from the resume


def tailored(*, bullets=None, skills=None, summary=None, description=None) -> Resume:
    project = Project(
        name="Payments", description=description or ORIGINAL.projects[0].description,
        bullets=bullets if bullets is not None else list(ORIGINAL.projects[0].bullets))
    groups = [SkillGroup(category="Backend", items=skills)] if skills is not None else ORIGINAL.skill_groups
    return ORIGINAL.model_copy(update={"projects": [project], "skill_groups": groups, "summary": summary or ORIGINAL.summary})


def kinds(report):
    return [v.kind for v in report.violations]


# --- what is allowed -----------------------------------------------------------------------------

def test_an_unchanged_resume_is_grounded():
    assert check_grounding(ORIGINAL, ORIGINAL, PLAN).ok


def test_rewording_that_reuses_the_original_facts_is_grounded():
    t = tailored(bullets=[reworded("Designed REST APIs serving 14 partner systems.", "projects.0.bullets.0"),
                          ORIGINAL.projects[0].bullets[1]])

    report = check_grounding(ORIGINAL, t, PLAN)

    assert report.ok, report.violations


def test_a_sentence_may_start_with_a_new_capitalised_verb():
    t = tailored(bullets=[reworded("Delivered REST APIs for 14 partner systems.", "projects.0.bullets.0")])

    assert check_grounding(ORIGINAL, t, PLAN).ok


# --- the fake skill must be caught ---------------------------------------------------------------

def test_a_jd_skill_the_resume_does_not_have_is_caught_in_a_bullet():
    t = tailored(bullets=[reworded("Designed REST APIs for 14 partner systems on Kubernetes.", "projects.0.bullets.0")])

    report = check_grounding(ORIGINAL, t, PLAN)

    assert not report.ok and kinds(report) == ["missing_skill"]
    assert report.violations[0].path == "projects.0.bullets.0"


def test_a_new_technology_that_is_not_even_in_the_jd_is_caught():
    t = tailored(bullets=[reworded("Designed REST APIs for 14 partner systems using Terraform.", "projects.0.bullets.0")])

    assert kinds(check_grounding(ORIGINAL, t, PLAN)) == ["new_term"]


def test_a_skill_slipped_into_the_skills_section_is_caught():
    t = tailored(skills=[*ORIGINAL.skill_groups[0].items, orig("Kubernetes", "skills.0.9")])

    report = check_grounding(ORIGINAL, t, PLAN)

    assert kinds(report) == ["unknown_source"] and report.violations[0].path == "skill_groups.0.items.2"


def test_a_skill_reworded_into_another_skill_is_caught():
    t = tailored(skills=[reworded("Kubernetes", "skills.0.0"), ORIGINAL.skill_groups[0].items[1]])

    assert "missing_skill" in kinds(check_grounding(ORIGINAL, t, PLAN))


def test_an_invented_number_is_caught_but_a_number_from_the_original_is_fine():
    invented = tailored(bullets=[reworded("Designed REST APIs for 14 partner systems, cutting latency by 40%.", "projects.0.bullets.0")])
    inflated = tailored(bullets=[reworded("Designed REST APIs for 140 partner systems.", "projects.0.bullets.0")])

    assert kinds(check_grounding(ORIGINAL, invented, PLAN)) == ["new_number"]
    assert kinds(check_grounding(ORIGINAL, inflated, PLAN)) == ["new_number"]


def test_an_item_that_claims_to_be_original_but_was_changed_is_caught():
    t = tailored(bullets=[orig("Designed REST APIs for 14 partner systems and mentored staff.", "projects.0.bullets.0")])

    assert "altered_original" in kinds(check_grounding(ORIGINAL, t, PLAN))


def test_the_summary_is_checked_like_everything_else():
    t = tailored(summary=reworded("Backend engineer with 12 years of experience.", "summary"))

    assert kinds(check_grounding(ORIGINAL, t, PLAN)) == ["new_number"]


# --- what the person adds is theirs --------------------------------------------------------------

def test_an_item_the_associate_added_is_not_flagged_but_is_listed_for_the_lead():
    mine = Item(text="Hands-on Kubernetes administration at a previous client.", origin=Origin.USER_ADDED)
    t = tailored(bullets=[*ORIGINAL.projects[0].bullets, mine])

    report = check_grounding(ORIGINAL, t, PLAN)

    assert report.ok and report.user_added == ("projects.0.bullets.2",)


# --- putting the original back --------------------------------------------------------------------

def test_enforcing_restores_the_original_wording_and_drops_items_that_have_no_original():
    t = tailored(bullets=[reworded("Designed REST APIs for 14 partner systems on Kubernetes.", "projects.0.bullets.0"),
                          ORIGINAL.projects[0].bullets[1]],
                 skills=[*ORIGINAL.skill_groups[0].items, orig("Terraform", "skills.0.9")])

    safe, report = enforce_grounding(ORIGINAL, t, PLAN)

    assert safe.projects[0].bullets[0] == ORIGINAL.projects[0].bullets[0]
    assert safe.skills_flat() == ["Java", "Spring Boot"]
    assert sorted(kinds(report)) == ["missing_skill", "unknown_source"]
    assert check_grounding(ORIGINAL, safe, PLAN).ok


def test_enforcing_a_clean_resume_changes_nothing_and_never_modifies_its_input():
    t = tailored(bullets=[reworded("Designed REST APIs serving 14 partner systems.", "projects.0.bullets.0"),
                          ORIGINAL.projects[0].bullets[1]])
    before = t.model_copy(deep=True)

    safe, report = enforce_grounding(ORIGINAL, t, PLAN)

    assert report.ok and safe == t and t == before


def test_an_item_with_several_problems_is_reverted_once():
    t = tailored(bullets=[reworded("Designed APIs on Kubernetes with Terraform, cutting cost by 40%.", "projects.0.bullets.0"),
                          ORIGINAL.projects[0].bullets[1]])

    safe, report = enforce_grounding(ORIGINAL, t, PLAN)

    assert len(report.violations) >= 3 and safe.projects[0].bullets[0] == ORIGINAL.projects[0].bullets[0]


@pytest.mark.parametrize("path", ["projects.0.description"])
def test_a_reworded_description_is_reverted_the_same_way(path):
    t = tailored(description=reworded("Built payment workflows on Kafka and Kubernetes.", "projects.0.description"))

    safe, report = enforce_grounding(ORIGINAL, t, PLAN)

    assert safe.projects[0].description == ORIGINAL.projects[0].description and report.violations[0].path == path

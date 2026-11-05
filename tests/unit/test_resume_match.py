"""The match plan: which JD requirements the associate's resume already evidences, and which it does not.

Pure code, no model. "Evidenced" means the skill is actually written somewhere in the resume. A requirement that is not
evidenced is reported as missing and must never be claimed in the tailored resume.
"""
import pytest

from app.rmg.resume.facts import Experience
from app.rmg.resume.jd import Role
from app.rmg.resume.match import build_match_plan, mentions
from app.rmg.resume.model import Item, Origin, Project, Resume, SkillGroup


def item(text, source="x"):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def role(must=("Java",), nice=(), title="Java Developer", min_years=None):
    return Role(title=title, min_years=min_years, must_have=list(must), nice_to_have=list(nice))


def resume(skills=(), projects=(), summary=None, highlights=()):
    return Resume(
        name="A", summary=item(summary) if summary else None,
        skill_groups=[SkillGroup(category="Skills", items=[item(s) for s in skills])] if skills else [],
        highlights=[item(h) for h in highlights],
        projects=[Project(name=n, description=item(d) if d else None, bullets=[item(b) for b in bullets])
                  for n, d, bullets in projects],
    )


# --- finding a skill in text ---------------------------------------------------------------------

@pytest.mark.parametrize("skill,text,expected", [
    ("Java", "Built services in Java and Kafka.", True),
    ("Java", "Built services in java.", True),
    ("Java", "Wrote JavaScript front ends.", False),
    ("C", "Experienced in C++ and C#.", False),
    ("C", "Experienced in C, Go.", True),
    ("C++", "Experienced in C++.", True),
    (".NET", "Built .NET services.", True),
    ("Node.js", "Used Node.js daily.", True),
    ("Spring Boot", "Used Spring   Boot.", True),
    ("Go", "Used Django.", False),
])
def test_a_skill_is_found_as_a_whole_word_not_inside_another(skill, text, expected):
    assert mentions(text, skill) is expected


# --- evidence ------------------------------------------------------------------------------------

def test_a_skill_in_the_skills_section_is_evidenced_there():
    plan = build_match_plan(resume(skills=["java", "SQL"]), role(must=["Java"]))

    [m] = plan.matches
    assert (m.skill, m.required, m.in_skills, m.projects) == ("Java", True, True, ())
    assert plan.missing_required == ()


def test_a_skill_only_used_in_a_project_still_counts_and_says_which_project():
    r = resume(skills=["SQL"], projects=[("Billing", "Built billing in Python.", ["Tuned queries."]),
                                         ("Payments", None, ["Wrote Kafka consumers in Java."])])

    [m] = build_match_plan(r, role(must=["Java"])).matches

    assert m.in_skills is False and m.projects == (1,)


def test_a_skill_in_the_summary_or_highlights_counts_as_evidence():
    plan = build_match_plan(resume(summary="Java engineer.", highlights=["Led Kafka work"]), role(must=["Java", "Kafka"]))

    assert [m.skill for m in plan.matches] == ["Java", "Kafka"] and plan.missing_required == ()


def test_a_requirement_the_resume_never_mentions_is_missing_and_cannot_be_claimed():
    plan = build_match_plan(resume(skills=["Java"]), role(must=["Java", "Kubernetes"], nice=["Kafka"]))

    assert plan.missing_required == ("Kubernetes",) and plan.missing_nice == ("Kafka",)
    assert [m.skill for m in plan.matches] == ["Java"]


def test_nice_to_have_matches_are_marked_not_required():
    plan = build_match_plan(resume(skills=["Java", "Kafka"]), role(must=["Java"], nice=["Kafka"]))

    assert [(m.skill, m.required) for m in plan.matches] == [("Java", True), ("Kafka", False)]


def test_required_coverage_is_the_share_of_must_haves_evidenced():
    plan = build_match_plan(resume(skills=["Java", "SQL"]), role(must=["Java", "SQL", "AWS", "Kafka"]))

    assert plan.required_coverage == 0.5


def test_coverage_is_none_when_the_role_lists_no_must_haves():
    assert build_match_plan(resume(skills=["Java"]), role(must=[])).required_coverage is None


# --- projects and skills order -------------------------------------------------------------------

def test_projects_are_ranked_by_how_much_of_the_jd_they_cover_with_required_skills_counting_double():
    r = resume(projects=[("Intranet", "Wrote Kafka tooling.", []),                   # 1 nice = 1
                         ("Core", "Java and Spring services.", ["Used Kafka."]),     # 2 must + 1 nice = 5
                         ("Reports", None, ["Wrote Java reports."]),                 # 1 must = 2
                         ("Misc", "Did other things.", [])])                        # 0

    plan = build_match_plan(r, role(must=["Java", "Spring"], nice=["Kafka"]))

    assert [(p.index, p.name) for p in plan.project_order] == [(1, "Core"), (2, "Reports"), (0, "Intranet"), (3, "Misc")]
    assert plan.project_order[0].skills == ("Java", "Spring", "Kafka")


def test_equally_relevant_projects_keep_their_original_order():
    r = resume(projects=[("A", "Java.", []), ("B", "Java.", []), ("C", "Java.", [])])

    assert [p.index for p in build_match_plan(r, role()).project_order] == [0, 1, 2]


def test_skills_the_jd_wants_come_first_and_the_rest_keep_their_order():
    plan = build_match_plan(resume(skills=["Python", "Kafka", "Java", "Go"]), role(must=["Java"], nice=["Kafka"]))

    assert plan.skill_order == ("Java", "Kafka", "Python", "Go")


# --- experience ----------------------------------------------------------------------------------

@pytest.mark.parametrize("months,min_years,expected", [(96, 5, True), (60, 5, True), (59, 5, False), (10, None, None)])
def test_minimum_years_are_compared_with_the_computed_experience(months, min_years, expected):
    plan = build_match_plan(resume(), role(min_years=min_years), Experience(months=months, skipped=()))

    assert plan.meets_min_years is expected


def test_without_a_computed_experience_the_years_check_is_unknown():
    assert build_match_plan(resume(), role(min_years=5)).meets_min_years is None


def test_the_plan_is_immutable_and_does_not_change_the_resume():
    r = resume(skills=["Java"])
    plan = build_match_plan(r, role())

    with pytest.raises(Exception):  # noqa: B017  frozen model
        plan.role_title = "x"
    assert r.skills_flat() == ["Java"]

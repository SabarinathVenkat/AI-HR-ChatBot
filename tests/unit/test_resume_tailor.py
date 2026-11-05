"""Drafting every project in parallel with a LangGraph fan-out (Send), then putting the resume back together.

The drafter is a plain function here, so no model is involved: what is tested is the graph's behaviour.
"""
import threading

from app.rmg.resume.draft import DraftedBullet, DraftedProject, TailoringSettings
from app.rmg.resume.jd import Role
from app.rmg.resume.match import build_match_plan
from app.rmg.resume.model import Item, Origin, Project, Resume, SkillGroup
from app.rmg.resume.tailor import tailor_projects


def item(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def make_project(n, text):
    return Project(name=f"P{n}", description=item(f"About {text}.", f"projects.{n}.description"),
                   bullets=[item(f"Used {text} daily.", f"projects.{n}.bullets.0")])


def make_resume(*texts):
    return Resume(name="Anil", skill_groups=[SkillGroup(category="S", items=[item("Java", "skills.0.0")])],
                  projects=[make_project(n, t) for n, t in enumerate(texts)])


ROLE = Role(title="Java Developer", min_years=None, must_have=["Java"], nice_to_have=["Kafka"])


def reword(project, role, plan):
    return DraftedProject(description="", bullets=[DraftedBullet(text=f"[tailored] {b.text}", from_bullet=i)
                                                   for i, b in enumerate(project.bullets)])


def run(resume, drafter=reword, settings=TailoringSettings()):
    return tailor_projects(resume, ROLE, build_match_plan(resume, ROLE), drafter, settings)


def test_every_project_is_drafted_once_and_the_most_relevant_come_first():
    resume = make_resume("Python", "Java", "Java and Kafka")
    seen = []

    def spy(project, role, plan):
        seen.append(project.name)
        return reword(project, role, plan)

    result = run(resume, spy)

    assert sorted(seen) == ["P0", "P1", "P2"]
    assert [p.name for p in result.resume.projects] == ["P2", "P1", "P0"]
    assert all(p.bullets[0].text.startswith("[tailored]") and p.bullets[0].origin is Origin.REWORDED for p in result.resume.projects)
    assert result.warnings == ()


def test_the_rest_of_the_resume_is_untouched_and_the_input_is_not_changed():
    resume = make_resume("Java", "Python")

    result = run(resume)

    assert result.resume.name == "Anil" and result.resume.skill_groups == resume.skill_groups
    assert resume.projects[0].bullets[0].text == "Used Java daily."


def test_projects_really_are_drafted_at_the_same_time():
    barrier = threading.Barrier(3, timeout=10)  # all three drafts must be running together to get past it

    def meet(project, role, plan):
        barrier.wait()
        return reword(project, role, plan)

    result = run(make_resume("Java", "Java", "Java"), meet)

    assert result.warnings == ()


def test_a_project_whose_draft_fails_is_kept_as_written_and_the_others_still_succeed():
    resume = make_resume("Java", "Java and Kafka")

    def flaky(project, role, plan):
        if project.name == "P0":
            raise RuntimeError("401 sk-ant-SECRET")
        return reword(project, role, plan)

    result = run(resume, flaky)

    by_name = {p.name: p for p in result.resume.projects}
    assert by_name["P0"] == resume.projects[0]
    assert by_name["P1"].bullets[0].text.startswith("[tailored]")
    assert result.warnings == ("Project 'P0' could not be tailored and was kept as written.",)
    assert "SECRET" not in str(result.warnings)


def test_a_draft_that_breaks_the_rules_is_kept_as_written_with_a_warning():
    resume = make_resume("Java")

    def bad(project, role, plan):
        return DraftedProject(description="", bullets=[DraftedBullet(text="x", from_bullet=9)])

    result = run(resume, bad)

    assert result.resume.projects == resume.projects and len(result.warnings) == 1


def test_a_resume_with_no_projects_comes_back_unchanged():
    resume = make_resume()

    result = run(resume)

    assert result.resume == resume and result.warnings == ()


def test_the_bullet_limit_from_the_settings_is_applied():
    resume = Resume(name="A", projects=[Project(name="P", bullets=[item(f"Java {i}.", f"projects.0.bullets.{i}") for i in range(5)])])

    def keep_all(project, role, plan):
        return DraftedProject(description="", bullets=[DraftedBullet(text=b.text, from_bullet=i) for i, b in enumerate(project.bullets)])

    assert len(run(resume, keep_all, TailoringSettings(max_bullets=3)).resume.projects[0].bullets) == 3

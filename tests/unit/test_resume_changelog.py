"""The change log: what tailoring changed, in words a person can check, computed in code from the two resumes.

Kinds: reworded, emphasised (now brings forward a skill the role wants), condensed (clearly shorter), dropped,
reordered, rejected (a change grounding refused), added_by_you (typed by the associate). Plus the JD coverage view.
"""
import pytest

from app.rmg.resume.changelog import build_change_log
from app.rmg.resume.grounding import GroundingReport, Violation
from app.rmg.resume.jd import Role
from app.rmg.resume.model import Item, Origin, Project, Resume, SkillGroup


def orig(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def reworded(text, source):
    return Item(text=text, origin=Origin.REWORDED, source=source)


LONG = "Designed REST APIs for 14 partner systems using Java and a lot of careful engineering work."
ORIGINAL = Resume(
    name="Anil",
    skill_groups=[SkillGroup(category="Backend", items=[orig("Java", "skills.0.0"), orig("Kafka", "skills.0.1")])],
    projects=[
        Project(name="Intranet", bullets=[orig("Maintained the staff intranet portal for HR.", "projects.0.bullets.0")]),
        Project(name="Payments", description=orig("Built payment workflows on Kafka.", "projects.1.description"),
                bullets=[orig(LONG, "projects.1.bullets.0"), orig("Added tracing across services.", "projects.1.bullets.1"),
                         orig("Ran weekly standups.", "projects.1.bullets.2")]),
    ],
)
ROLE = Role(title="Java Developer", min_years=None, must_have=["Java", "Kubernetes"], nice_to_have=["Kafka"])
NO_REPORT = GroundingReport(violations=(), user_added=())


def payments(bullets, description=None):
    return Project(name="Payments", description=description or ORIGINAL.projects[1].description, bullets=bullets)


def tailored(projects) -> Resume:
    return ORIGINAL.model_copy(update={"projects": projects})


def log_for(t, report=NO_REPORT):
    return build_change_log(ORIGINAL, t, ROLE, report)


def kinds(log):
    return [e.kind for e in log.entries]


UNCHANGED = list(ORIGINAL.projects)


# --- what changed ----------------------------------------------------------------------------------

def test_an_unchanged_resume_has_no_entries_and_says_so():
    log = log_for(tailored(UNCHANGED))

    assert log.entries == () and "No changes" in log.summary


def test_a_plain_rewording_shows_before_after_and_where():
    t = tailored([UNCHANGED[0], payments([ORIGINAL.projects[1].bullets[0], reworded("Added tracing to every service.", "projects.1.bullets.1"),
                                          ORIGINAL.projects[1].bullets[2]])])

    [e] = log_for(t).entries

    assert e.kind == "reworded" and e.before == "Added tracing across services." and e.after == "Added tracing to every service."
    assert e.where == "Project 'Payments', bullet 2" and e.source == "projects.1.bullets.1"


def test_a_rewording_that_brings_forward_a_skill_the_role_wants_is_emphasised_and_says_which():
    t = tailored([UNCHANGED[0], payments([ORIGINAL.projects[1].bullets[0], reworded("Added tracing across Java services.", "projects.1.bullets.1"),
                                          ORIGINAL.projects[1].bullets[2]])])

    [e] = log_for(t).entries

    assert e.kind == "emphasised" and "Java" in e.reason


def test_a_much_shorter_rewording_is_condensed():
    t = tailored([UNCHANGED[0], payments([reworded("Designed REST APIs for 14 partner systems in Java.", "projects.1.bullets.0"),
                                          ORIGINAL.projects[1].bullets[1], ORIGINAL.projects[1].bullets[2]])])

    [e] = log_for(t).entries

    assert e.kind == "condensed"


def test_an_original_item_that_is_gone_is_listed_as_dropped_with_its_text():
    t = tailored([UNCHANGED[0], payments([ORIGINAL.projects[1].bullets[0], ORIGINAL.projects[1].bullets[1]])])

    [e] = log_for(t).entries

    assert e.kind == "dropped" and e.before == "Ran weekly standups." and e.after is None
    assert e.where == "Project 'Payments', bullet 3"


def test_a_project_that_moves_is_listed_with_old_and_new_position_and_why():
    t = tailored([UNCHANGED[1], UNCHANGED[0]])

    entries = [e for e in log_for(t).entries if e.kind == "reordered"]

    first = next(e for e in entries if e.where == "Project 'Payments'")
    assert (first.before, first.after) == ("Position 2", "Position 1") and "Java" in first.reason or "Kafka" in first.reason
    assert any(e.where == "Project 'Intranet'" and e.after == "Position 2" for e in entries)


def test_bullets_that_change_order_inside_a_project_are_listed_once_for_that_project():
    b = ORIGINAL.projects[1].bullets
    t = tailored([UNCHANGED[0], payments([b[1], b[0], b[2]])])

    [e] = log_for(t).entries

    assert e.kind == "reordered" and e.where == "Project 'Payments', bullets"


def test_something_the_associate_added_is_listed_as_theirs():
    mine = Item(text="Hands-on Kubernetes administration.", origin=Origin.USER_ADDED)
    t = tailored([UNCHANGED[0], payments([*ORIGINAL.projects[1].bullets, mine])])

    [e] = build_change_log(ORIGINAL, t, ROLE, GroundingReport(violations=(), user_added=("projects.1.bullets.3",))).entries

    assert e.kind == "added_by_you" and e.after == "Hands-on Kubernetes administration." and e.before is None


def test_a_change_that_grounding_refused_is_listed_with_the_reason():
    report = GroundingReport(violations=(Violation("missing_skill", "projects.1.bullets.1", "Kubernetes"),), user_added=())

    [e] = log_for(tailored(UNCHANGED), report).entries

    assert e.kind == "rejected" and "Kubernetes" in e.reason and e.before == "Added tracing across services."
    assert e.where == "Project 'Payments', bullet 2"


def test_several_violations_on_one_item_make_one_rejected_entry():
    report = GroundingReport(violations=(Violation("missing_skill", "projects.1.bullets.1", "Kubernetes"),
                                         Violation("new_term", "projects.1.bullets.1", "Terraform")), user_added=())

    entries = log_for(tailored(UNCHANGED), report).entries

    assert len(entries) == 1 and "Kubernetes" in entries[0].reason and "Terraform" in entries[0].reason


# --- coverage and the summary ----------------------------------------------------------------------

def test_coverage_shows_what_the_resume_covers_and_what_it_cannot_claim():
    cov = log_for(tailored(UNCHANGED)).coverage

    assert cov.covered == ("Java", "Kafka") and cov.missing_required == ("Kubernetes",) and cov.missing_nice == ()
    assert cov.required_before == cov.required_after == 0.5


def test_coverage_is_recomputed_on_the_tailored_resume():
    dropped_java_use = tailored([UNCHANGED[0], payments([ORIGINAL.projects[1].bullets[1]])])

    cov = log_for(dropped_java_use).coverage

    assert cov.required_before == 0.5 and cov.required_after == 0.5  # Java is still in the skills section


def test_the_summary_counts_the_changes_and_names_the_gaps_in_plain_words():
    b = ORIGINAL.projects[1].bullets
    t = tailored([UNCHANGED[0], payments([reworded("Added tracing across Java services.", "projects.1.bullets.1"), b[0]])])

    summary = log_for(t).summary

    assert "1 item emphasised" in summary and "1 item dropped" in summary
    assert "1 of 2 required skills" in summary and "Kubernetes" in summary


@pytest.mark.parametrize("n,word", [(1, "1 item reworded"), (2, "2 items reworded")])
def test_counts_use_the_right_plural(n, word):
    bullets = [reworded("Added tracing to every service.", "projects.1.bullets.1"), reworded("Ran standups weekly.", "projects.1.bullets.2")][:n]
    keep = [ORIGINAL.projects[1].bullets[0], *bullets] + ([ORIGINAL.projects[1].bullets[2]] if n == 1 else [])
    keep = [keep[0], *sorted(keep[1:], key=lambda i: i.source)]

    assert word in log_for(tailored([UNCHANGED[0], payments(keep)])).summary


def test_the_log_is_immutable_and_the_resumes_are_untouched():
    t = tailored(UNCHANGED)
    before = ORIGINAL.model_copy(deep=True)

    log = log_for(t)

    assert ORIGINAL == before
    with pytest.raises(Exception):  # noqa: B017  frozen
        log.summary = "x"


# --- skills in the change list -------------------------------------------------------------------------------------------

def with_skills(items):
    return ORIGINAL.model_copy(update={"skill_groups": [SkillGroup(category="Backend", items=items)]})


def test_a_skill_the_associate_removed_is_listed_as_dropped_with_where_it_was():
    t = with_skills([ORIGINAL.skill_groups[0].items[0]])  # Kafka is gone

    [e] = [e for e in log_for(t).entries if e.kind == "dropped"]

    assert e.before == "Kafka" and e.after is None and e.where == "Skill 'Kafka' in Backend"


def test_a_skill_the_associate_added_is_listed_as_theirs_with_where_it_is():
    mine = Item(text="Terraform", origin=Origin.USER_ADDED)
    t = with_skills([*ORIGINAL.skill_groups[0].items, mine])

    [e] = build_change_log(ORIGINAL, t, ROLE, GroundingReport(violations=(), user_added=("skill_groups.0.items.2",))).entries

    assert e.kind == "added_by_you" and e.after == "Terraform" and e.where == "Skill 'Terraform' in Backend"


def test_a_skill_that_was_renamed_is_listed_as_reworded_with_before_and_after():
    renamed = reworded("Apache Kafka", "skills.0.1")
    t = with_skills([ORIGINAL.skill_groups[0].items[0], renamed])

    [e] = log_for(t).entries

    assert e.kind in ("reworded", "emphasised") and e.before == "Kafka" and e.after == "Apache Kafka"
    assert e.where == "Skill 'Apache Kafka' in Backend"


# --- each change says which line of the resume it is about --------------------------------------------------------------

def test_a_reworded_item_points_at_its_line_in_the_tailored_resume():
    t = tailored([UNCHANGED[0], payments([ORIGINAL.projects[1].bullets[0], reworded("Added tracing to every service.", "projects.1.bullets.1"),
                                          ORIGINAL.projects[1].bullets[2]])])

    [e] = log_for(t).entries

    assert e.path == "projects.1.bullets.1"


def test_a_moved_project_and_reordered_bullets_point_at_the_project_in_its_new_position():
    moved = [e for e in log_for(tailored([UNCHANGED[1], UNCHANGED[0]])).entries if e.kind == "reordered"]
    b = ORIGINAL.projects[1].bullets
    bullets = log_for(tailored([UNCHANGED[0], payments([b[1], b[0], b[2]])])).entries

    assert {e.where: e.path for e in moved} == {"Project 'Payments'": "projects.0", "Project 'Intranet'": "projects.1"}
    assert [e.path for e in bullets] == ["projects.1"]


def test_something_the_associate_added_and_something_grounding_refused_point_at_their_lines():
    mine = Item(text="Hands-on Kubernetes administration.", origin=Origin.USER_ADDED)
    t = tailored([UNCHANGED[0], payments([*ORIGINAL.projects[1].bullets, mine])])
    added = build_change_log(ORIGINAL, t, ROLE, GroundingReport(violations=(), user_added=("projects.1.bullets.3",))).entries
    refused = log_for(tailored(UNCHANGED), GroundingReport(violations=(Violation("new_term", "projects.1.bullets.1", "Terraform"),), user_added=())).entries

    assert [e.path for e in added] == ["projects.1.bullets.3"] and [e.path for e in refused] == ["projects.1.bullets.1"]


def test_a_dropped_item_has_no_line_in_the_resume_to_point_at():
    t = tailored([UNCHANGED[0], payments([ORIGINAL.projects[1].bullets[0], ORIGINAL.projects[1].bullets[1]])])

    [e] = log_for(t).entries

    assert e.kind == "dropped" and e.path is None

"""Deep match: the resume is rebuilt around the job (new and merged bullets, a rewritten summary, more highlights), and every
claim is still checked in code, so it can say a lot more and still never invent a skill, a number or a technology.
"""
import pytest

from app.rmg.resume.deep import (
    DEEP_HIGHLIGHTS, DraftedSummary, MODES, build_prompt as summary_prompt, drop_repeated_bullets, rewrite_summary,
)
from app.rmg.resume.draft import (
    DEEP_SETTINGS, DraftedBullet, DraftedProject, DraftError, TailoringSettings, apply_draft, build_prompt,
)
from app.rmg.resume.extract import ExtractionError
from app.rmg.resume.grounding import enforce_grounding
from app.rmg.resume.highlights import DraftedHighlight, HighlightDraft
from app.rmg.resume.model import Item, Origin, Project
from app.rmg.resume.pipeline import PipelineDeps, PipelineRequest, run_pipeline
from tests.unit.resume_fakes import FakeJDExtractor, FakeResumeExtractor, keep_as_written
from tests.unit.resume_templates import make_template
from tests.unit.test_resume_highlights import BASE, PLAN, ROLE


def deep_project() -> Project:
    return BASE.projects[0]


def bullet(text, main, *also):
    return DraftedBullet(text=text, from_bullet=main, also_from=list(also))


def texts(project: Project) -> list[str]:
    return [b.text for b in project.bullets]


# --- the project, rebuilt ----------------------------------------------------------------------------------------

def test_a_deep_draft_may_split_one_original_into_several_bullets_and_each_keeps_its_source():
    draft = DraftedProject(bullets=[
        bullet("Designed the REST API layer used by 14 partner systems.", 0),
        bullet("Built the Java services behind the REST APIs for 14 partner systems.", 0),
        bullet("Cut report time from 40 seconds to 6 seconds by tuning PostgreSQL queries.", 1),
    ])

    result = apply_draft(deep_project(), draft, DEEP_SETTINGS)

    assert len(result.bullets) == 3
    assert [b.source for b in result.bullets] == ["projects.0.bullets.0", "projects.0.bullets.0", "projects.0.bullets.1"]
    assert all(b.origin is Origin.REWORDED for b in result.bullets)


def test_a_deep_bullet_may_draw_on_several_original_lines_and_cites_all_of_them():
    draft = DraftedProject(bullets=[bullet("Built Java APIs and tuned the PostgreSQL behind them.", 0, 1)])

    result = apply_draft(deep_project(), draft, DEEP_SETTINGS)

    assert result.bullets[0].source == "projects.0.bullets.0+projects.0.bullets.1"


def test_polish_still_refuses_to_use_an_original_twice_or_to_merge_lines():
    twice = DraftedProject(bullets=[bullet("One.", 0), bullet("Two.", 0)])
    merged = DraftedProject(bullets=[bullet("Both.", 0, 1)])

    with pytest.raises(DraftError):
        apply_draft(deep_project(), twice, TailoringSettings())
    with pytest.raises(DraftError):
        apply_draft(deep_project(), merged, TailoringSettings())


def test_deep_match_allows_more_bullets_than_polish_and_drops_a_bullet_said_twice():
    many = DraftedProject(bullets=[bullet(f"Point {i} about the payment gateway.", 0) for i in range(8)] + [bullet("Point 0 about the payment gateway.", 1)])

    result = apply_draft(deep_project(), many, DEEP_SETTINGS)

    assert len(result.bullets) == 8 and len(set(texts(result))) == 8
    assert DEEP_SETTINGS.max_bullets > TailoringSettings().max_bullets


def test_a_deep_draft_that_cites_a_line_that_does_not_exist_is_refused():
    with pytest.raises(DraftError):
        apply_draft(deep_project(), DraftedProject(bullets=[bullet("Text.", 0, 9)]), DEEP_SETTINGS)


def test_the_deep_prompt_is_job_first_forbids_missing_skills_and_names_them():
    prompt = build_prompt(deep_project(), ROLE, PLAN, DEEP_SETTINGS, deep=True)

    assert "The job comes first" in prompt and "split" in prompt and "also_from" in prompt
    assert "never mention" in prompt and "Kubernetes" in prompt and "Snowflake" in prompt
    assert "Never add a technology" in prompt
    assert "also_from" not in build_prompt(deep_project(), ROLE, PLAN, TailoringSettings())  # polish is unchanged


# --- the grounding check still holds ----------------------------------------------------------------------------

def test_a_deep_bullet_that_claims_a_skill_the_resume_lacks_is_put_back_never_kept():
    project = apply_draft(deep_project(), DraftedProject(bullets=[
        bullet("Designed REST APIs for 14 partner systems and ran them on Kubernetes.", 0),
        bullet("Cut report time from 40 seconds to 6 seconds.", 1),
    ]), DEEP_SETTINGS)
    tailored = BASE.model_copy(update={"projects": [project, *BASE.projects[1:]]})

    grounded, report = enforce_grounding(BASE, tailored, PLAN)

    assert any(v.kind == "missing_skill" and v.detail == "Kubernetes" for v in report.violations)
    assert "Kubernetes" not in " ".join(texts(grounded.projects[0]))
    assert "Designed REST APIs for 14 partner systems using Java." in texts(grounded.projects[0])


def test_a_deep_bullet_with_a_made_up_number_is_refused():
    project = apply_draft(deep_project(), DraftedProject(bullets=[bullet("Designed REST APIs for 200 partner systems using Java.", 0)]), DEEP_SETTINGS)
    tailored = BASE.model_copy(update={"projects": [project, *BASE.projects[1:]]})

    _, report = enforce_grounding(BASE, tailored, PLAN)

    assert any(v.kind == "new_number" and v.detail == "200" for v in report.violations)


def test_a_merged_bullet_that_fails_is_dropped_because_it_has_no_single_original():
    project = apply_draft(deep_project(), DraftedProject(bullets=[bullet("Built Spark pipelines on Databricks.", 0, 1), bullet("Cut report time to 6 seconds.", 1)]), DEEP_SETTINGS)
    tailored = BASE.model_copy(update={"projects": [project, *BASE.projects[1:]]})

    grounded, _ = enforce_grounding(BASE, tailored, PLAN)

    assert not any("Spark" in t for t in texts(grounded.projects[0]))


def test_a_bullet_put_back_to_its_original_does_not_repeat_one_that_was_kept():
    original = deep_project().bullets[0].text
    project = deep_project().model_copy(update={"bullets": [
        Item(text=original, origin=Origin.ORIGINAL, source="projects.0.bullets.0"),
        Item(text=original, origin=Origin.ORIGINAL, source="projects.0.bullets.0")]})

    deduped = drop_repeated_bullets(BASE.model_copy(update={"projects": [project]}))

    assert texts(deduped.projects[0]) == [original]


# --- the summary ------------------------------------------------------------------------------------------------

class FakeSummarizer:
    def __init__(self, text, *lines, error=None):
        self.draft, self.error = DraftedSummary(text=text, from_lines=list(lines)), error

    def __call__(self, r, role, plan):
        if self.error:
            raise self.error
        return self.draft


def test_a_grounded_summary_replaces_the_old_one_and_cites_what_it_came_from():
    summarizer = FakeSummarizer("Backend engineer who builds Java payment platforms with Kafka and PostgreSQL.", "summary", "projects.1.bullets.0")

    result, notes = rewrite_summary(BASE, BASE, PLAN, ROLE, summarizer)

    assert result.summary.text.startswith("Backend engineer who builds Java payment platforms")
    assert result.summary.origin is Origin.REWORDED and result.summary.source == "summary+projects.1.bullets.0" and notes == ()


def test_a_summary_that_claims_a_missing_skill_is_not_used():
    summarizer = FakeSummarizer("Java and Kubernetes engineer building payment platforms.", "summary")

    result, notes = rewrite_summary(BASE, BASE, PLAN, ROLE, summarizer)

    assert result.summary == BASE.summary and "does not support" in notes[0]


def test_a_summary_with_an_invented_number_or_no_sources_is_not_used():
    invented = rewrite_summary(BASE, BASE, PLAN, ROLE, FakeSummarizer("Engineer with 12 years of Java.", "summary"))
    uncited = rewrite_summary(BASE, BASE, PLAN, ROLE, FakeSummarizer("A backend engineer.", "nowhere.0"))

    assert invented[0].summary == BASE.summary and uncited[0].summary == BASE.summary


def test_a_failing_summarizer_leaves_the_summary_and_says_so():
    result, notes = rewrite_summary(BASE, BASE, PLAN, ROLE, FakeSummarizer("x", error=ExtractionError("model_error")))

    assert result.summary == BASE.summary and "could not be rewritten" in notes[0]


def test_the_summary_prompt_forbids_years_and_missing_skills():
    prompt = summary_prompt(BASE, ROLE, PLAN)

    assert "Never state years of experience" in prompt and "never mention" in prompt and "Kubernetes" in prompt


# --- the whole run ----------------------------------------------------------------------------------------------

def deep_drafter(project, role, plan):
    """Every original kept, plus one new bullet built from the first and last originals."""
    kept = [DraftedBullet(text=b.text, from_bullet=i) for i, b in enumerate(project.bullets)]
    return DraftedProject(bullets=[*kept, bullet(f"Delivered {project.name} end to end.", 0, len(project.bullets) - 1)])


class EightHighlighter:
    def __init__(self):
        self.asked = []

    def __call__(self, r, role, plan, count):
        self.asked.append(count)
        lines = ["projects.0.bullets.0", "projects.0.bullets.1", "projects.1.bullets.0", "summary"]
        return HighlightDraft(highlights=[DraftedHighlight(text=f"Highlight number {i} about payment platforms built in Java.", from_lines=[lines[i % 4]])
                                          for i in range(count)])


def request(mode):
    import io
    out = io.BytesIO()
    make_template().save(out)
    return PipelineRequest(resume_file=("cv.txt", b"x"), template=out.getvalue(), jd_file=("jd.txt", b"x"), mode=mode)


def run(mode, **deps):
    base = dict(resume_extractor=FakeResumeExtractor(), jd_extractor=FakeJDExtractor(), drafter=keep_as_written)
    return run_pipeline(PipelineDeps(**{**base, **deps}), request(mode))


def test_polish_mode_never_calls_the_deep_parts():
    called = []
    result = run("polish", deep_drafter=lambda *a: called.append("deep"), summarizer=lambda *a: called.append("summary"))

    assert called == [] and result.mode == "polish"


def test_deep_mode_uses_the_deep_drafter_and_may_add_bullets_polish_would_not():
    polish = run("polish")
    deep = run("deep", deep_drafter=deep_drafter)

    assert deep.mode == "deep"
    assert sum(len(p.bullets) for p in deep.tailored.projects) > sum(len(p.bullets) for p in polish.tailored.projects)


def test_deep_mode_asks_for_eight_highlights_and_polish_for_five():
    deep_highlighter, polish_highlighter = EightHighlighter(), EightHighlighter()

    deep = run("deep", deep_drafter=deep_drafter, highlighter=deep_highlighter)
    polish = run("polish", highlighter=polish_highlighter)

    assert DEEP_HIGHLIGHTS == 8 and deep.mode == "deep" and polish.mode == "polish"
    assert deep_highlighter.asked[0] > polish_highlighter.asked[0]  # it asks for more when rebuilding for the job


def test_deep_mode_without_a_deep_drafter_falls_back_to_polish_and_says_so():
    result = run("deep")

    assert result.mode == "polish" and any("Deep match is not available" in w for w in result.warnings)


def test_deep_additions_show_up_in_the_change_log_as_written_for_you():
    result = run("deep", deep_drafter=deep_drafter)

    written = [e for e in result.changelog.entries if e.kind == "written"]

    assert written and all("project work" in e.reason for e in written)
    assert "written for you" in result.changelog.summary


def test_the_modes_are_polish_and_deep():
    assert MODES == ("polish", "deep")


def test_a_capital_letter_at_the_start_of_a_later_sentence_is_not_taken_for_a_technology():
    from app.rmg.resume.grounding import check_grounding

    later = Item(text="Designed REST APIs for 14 partner systems using Java. Redesigned nothing else here.", origin=Origin.REWORDED, source="projects.0.bullets.0")
    camel = Item(text="Designed REST APIs for 14 partner systems using Java. Used FooBarDB too.", origin=Origin.REWORDED, source="projects.0.bullets.0")

    def terms(item):
        project = BASE.projects[0].model_copy(update={"bullets": [item]})
        report = check_grounding(BASE, BASE.model_copy(update={"projects": [project, *BASE.projects[1:]]}), PLAN)
        return {v.detail for v in report.violations if v.kind == "new_term"}

    assert terms(later) == set()  # "Redesigned" opens a sentence
    assert "FooBarDB" in terms(camel)  # but a technology-shaped word is still caught anywhere


def test_a_summary_that_fails_the_check_is_tried_once_more_and_the_good_second_try_is_used():
    class Twice:
        def __init__(self):
            self.drafts = [DraftedSummary(text="Java and Kubernetes engineer.", from_lines=["summary"]),
                           DraftedSummary(text="Backend engineer who builds Java payment platforms.", from_lines=["summary"])]

        def __call__(self, r, role, plan):
            return self.drafts.pop(0)

    result, notes = rewrite_summary(BASE, BASE, PLAN, ROLE, Twice())

    assert result.summary.text == "Backend engineer who builds Java payment platforms." and notes == ()

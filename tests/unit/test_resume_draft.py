"""Turning a model's draft of one project into a safe Project.

The model proposes new wording and says which original bullet each new bullet rewrites. Code decides what is accepted:
provenance, the bullet limit, no invented description, no bullet used twice. Anything off is a DraftError, and the
caller keeps the project as written.
"""
import pytest

from app.rmg.resume.draft import (
    DraftedBullet, DraftedProject, DraftError, LLMProjectDrafter, TailoringSettings, apply_draft,
)
from app.rmg.resume.extract import ExtractionError
from app.rmg.resume.jd import Role
from app.rmg.resume.match import build_match_plan
from app.rmg.resume.model import Item, Origin, Project, Resume, SkillGroup
from tests.unit.resume_fakes import FakeModel


def item(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def project(description="Built payment workflows.", bullets=("Wrote Java services.", "Tuned SQL queries.", "Ran standups.")):
    return Project(
        name="Payments", description=item(description, "projects.0.description") if description else None,
        bullets=[item(b, f"projects.0.bullets.{i}") for i, b in enumerate(bullets)])


def draft(description="", *bullets):
    return DraftedProject(description=description, bullets=[DraftedBullet(text=t, from_bullet=i) for t, i in bullets])


SETTINGS = TailoringSettings(max_bullets=2)


def test_a_reworded_bullet_is_marked_reworded_and_points_to_the_original_it_came_from():
    result = apply_draft(project(), draft("", ("Built Java services for payments.", 0), ("Tuned SQL queries.", 1)), SETTINGS)

    first, second = result.bullets
    assert (first.origin, first.source, first.text) == (Origin.REWORDED, "projects.0.bullets.0", "Built Java services for payments.")
    assert (second.origin, second.source) == (Origin.ORIGINAL, "projects.0.bullets.1")  # unchanged text stays original


def test_bullets_can_be_reordered_by_the_draft():
    result = apply_draft(project(), draft("", ("Tuned SQL queries.", 1), ("Wrote Java services.", 0)), SETTINGS)

    assert [b.source for b in result.bullets] == ["projects.0.bullets.1", "projects.0.bullets.0"]


def test_only_the_bullet_limit_is_kept_and_the_first_ones_win():
    result = apply_draft(project(), draft("", ("A one.", 0), ("B two.", 1), ("C three.", 2)), SETTINGS)

    assert [b.text for b in result.bullets] == ["A one.", "B two."]


def test_the_description_is_reworded_with_its_own_source_and_kept_if_the_draft_leaves_it_blank():
    reworded = apply_draft(project(), draft("Built payments in Java.", ("x ok", 0)), SETTINGS)
    kept = apply_draft(project(), draft("", ("x ok", 0)), SETTINGS)

    assert (reworded.description.origin, reworded.description.source) == (Origin.REWORDED, "projects.0.description")
    assert kept.description == project().description


def test_a_description_cannot_be_invented_for_a_project_that_had_none():
    result = apply_draft(project(description=None), draft("A brand new description.", ("x ok", 0)), SETTINGS)

    assert result.description is None


@pytest.mark.parametrize("bad", [
    draft("", ("x", 3)),                      # no such original bullet
    draft("", ("x", -1)),
    draft("", ("x", 0), ("y", 0)),            # the same original used twice
    draft(""),                                # everything dropped
    draft("", ("   ", 0)),                    # nothing usable
    draft("", ("x" * 5000, 0)),               # too long
])
def test_a_draft_that_breaks_the_rules_is_rejected(bad):
    with pytest.raises(DraftError):
        apply_draft(project(), bad, SETTINGS)


def test_a_project_with_no_bullets_stays_as_it_is():
    result = apply_draft(project(bullets=()), draft("Reworded."), SETTINGS)

    assert result.bullets == [] and result.name == "Payments"


def test_the_project_name_is_never_changed_by_a_draft():
    assert apply_draft(project(), draft("", ("x ok", 0)), SETTINGS).name == "Payments"


# --- the model-backed drafter --------------------------------------------------------------------

def role():
    return Role(title="Java Developer", min_years=None, must_have=["Java", "Kubernetes"], nice_to_have=[])


def plan():
    resume = Resume(name="A", skill_groups=[SkillGroup(category="S", items=[item("Java", "skills.0.0")])], projects=[project()])
    return build_match_plan(resume, role())


def drafter_with(model):
    return LLMProjectDrafter(lambda max_tokens: model, TailoringSettings(max_bullets=6))


def test_the_prompt_names_the_role_and_only_skills_the_resume_really_has():
    model = FakeModel(parsed=draft("", ("Wrote Java services.", 0)))

    drafter_with(model)(project(), role(), plan())

    prompt = model.structured.messages[0].content
    assert "Java Developer" in prompt and "Java" in prompt
    assert "Kubernetes" not in prompt  # a missing requirement is never offered to the model
    assert "untrusted" in prompt and "<document>" in prompt
    assert "[0] Wrote Java services." in prompt and "[2] Ran standups." in prompt


def test_the_drafter_returns_what_the_model_proposed():
    proposal = draft("", ("Wrote Java services.", 0))

    assert drafter_with(FakeModel(parsed=proposal))(project(), role(), plan()) == proposal


@pytest.mark.parametrize("model,code", [
    (FakeModel(parsed=draft(), stop_reason="max_tokens"), "truncated"),
    (FakeModel(parsed=None, parsing_error=ValueError("x")), "invalid"),
    (FakeModel(error=RuntimeError("401 sk-ant-SECRET")), "model_error"),
])
def test_model_failures_are_the_same_loud_errors_as_elsewhere(model, code):
    with pytest.raises(ExtractionError) as e:
        drafter_with(model)(project(), role(), plan())
    assert e.value.code == code and "SECRET" not in str(e.value)

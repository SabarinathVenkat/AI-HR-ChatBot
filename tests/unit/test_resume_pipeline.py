"""The whole resume-builder run as one LangGraph graph, with every model replaced by a fake.

What is tested is the wiring: order, what runs at the same time, what stops the run and with which error, and that the
safety steps (template check first, de-duplication, grounding, draft mark) really are in the path.
"""
import io
import threading
from datetime import date

import pytest
from docx import Document

from app.rmg.resume.draft import DraftedBullet, DraftedProject, TailoringSettings
from app.rmg.resume.extract import ExtractionError
from app.rmg.resume.pipeline import PipelineDeps, PipelineError, PipelineRequest, run_pipeline
from app.rmg.resume.template import W, paragraph_text
from tests.unit.resume_fakes import JD, RESUME, FakeJDExtractor, FakeResumeExtractor, keep_as_written
from tests.unit.resume_templates import make_template

TODAY = date(2026, 11, 5)


def deps(resume_extractor=None, jd_extractor=None, drafter=keep_as_written):
    return PipelineDeps(resume_extractor or FakeResumeExtractor(), jd_extractor or FakeJDExtractor(), drafter, TailoringSettings())


def template_bytes(**kw) -> bytes:
    buf = io.BytesIO()
    make_template(**kw).save(buf)
    return buf.getvalue()


def request(**kw) -> PipelineRequest:
    base = dict(resume_file=("cv.txt", b"Anil Verma, a backend engineer"), jd_file=("jd.txt", b"We need a Java developer"),
                template=template_bytes(), today=TODAY)
    base.update(kw)
    return PipelineRequest(**base)


def lines(result) -> list[str]:
    doc = Document(io.BytesIO(result.rendered.docx))
    return [paragraph_text(p) for p in doc.element.body.iter(W + "p")]


def header(result) -> str:
    doc = Document(io.BytesIO(result.rendered.docx))
    return " ".join(p.text for s in doc.sections for p in s.header.paragraphs)


# --- the run, start to finish ------------------------------------------------------------------------

def test_a_run_produces_a_rendered_tailored_resume_with_its_change_log():
    result = run_pipeline(deps(), request())

    text = lines(result)
    assert "Anil Verma" in text and "Senior Backend Engineer 6 years 9 months" in text
    assert [p.name for p in result.tailored.projects] == ["Payments", "Intranet"]  # most relevant first
    assert result.changelog.coverage.missing_required == ("Kubernetes",)
    assert result.role.title == "Java Developer" and result.plan.missing_required == ("Kubernetes",)
    assert result.warnings == () and result.rendered.problems == ()


def test_the_resume_and_the_jd_are_read_at_the_same_time():
    barrier = threading.Barrier(2, timeout=10)  # both extractors must be running together to get past it

    run_pipeline(deps(FakeResumeExtractor(barrier=barrier), FakeJDExtractor(barrier=barrier)), request())


def test_duplicate_skills_are_removed_and_the_wanted_ones_come_first():
    text = lines(run_pipeline(deps(), request()))

    assert "Java, Kafka, Python" in text  # one Java; Java and Kafka (wanted by the JD) before Python


def test_a_job_description_that_was_already_read_is_used_without_calling_the_model_again():
    j = FakeJDExtractor()

    result = run_pipeline(deps(jd_extractor=j), request(jd_file=None, jd=JD))

    assert j.calls == [] and result.role.title == "Java Developer"


def test_a_second_role_in_the_jd_can_be_chosen():
    result = run_pipeline(deps(), request(role_index=1))

    assert result.role.title == "QA Lead" and result.plan.missing_required == ("Selenium",)


def test_the_years_line_is_left_out_when_no_experience_could_be_computed():
    no_dates = RESUME.model_copy(update={"jobs": []})

    assert "Senior Backend Engineer" in lines(run_pipeline(deps(FakeResumeExtractor(no_dates)), request()))


def test_a_download_is_marked_draft_unless_it_is_approved():
    assert "DRAFT" in header(run_pipeline(deps(), request()))
    assert "DRAFT" not in header(run_pipeline(deps(), request(draft=False)))


# --- the safety steps are in the path ------------------------------------------------------------------

def test_a_fake_skill_added_by_the_tailoring_model_never_reaches_the_document():
    def inject(project, role, plan):
        return DraftedProject(description="", bullets=[DraftedBullet(text=b.text + " on Kubernetes", from_bullet=i)
                                                       for i, b in enumerate(project.bullets)])

    result = run_pipeline(deps(drafter=inject), request())

    assert not [t for t in lines(result) if "Kubernetes" in t]
    assert any(e.kind == "rejected" and "Kubernetes" in e.reason for e in result.changelog.entries)


def test_a_project_whose_draft_fails_is_kept_and_the_run_reports_a_warning():
    def broken(project, role, plan):
        raise RuntimeError("model down")

    result = run_pipeline(deps(drafter=broken), request())

    assert len(result.warnings) == 2 and "Payments" in lines(result)


# --- failures stop the run with a clear error -----------------------------------------------------------

def test_a_template_that_cannot_be_used_stops_the_run_before_any_model_is_called():
    r, j = FakeResumeExtractor(), FakeJDExtractor()

    with pytest.raises(PipelineError) as e:
        run_pipeline(deps(r, j), request(template=template_bytes(numbered_bullets=False)))

    assert (e.value.stage, e.value.code) == ("template", "incomplete") and "projects" in str(e.value)
    assert r.calls == [] and j.calls == []


def test_an_unreadable_resume_file_stops_the_run_with_the_upload_error():
    with pytest.raises(PipelineError) as e:
        run_pipeline(deps(), request(resume_file=("cv.exe", b"x")))

    assert (e.value.stage, e.value.code) == ("resume", "unsupported_type") and "Word" in str(e.value)


def test_a_jd_the_model_cannot_read_stops_the_run():
    with pytest.raises(PipelineError) as e:
        run_pipeline(deps(jd_extractor=FakeJDExtractor(error=ExtractionError("no_roles"))), request())

    assert (e.value.stage, e.value.code) == ("job_description", "no_roles")


def test_when_both_inputs_fail_the_resume_error_is_reported_so_the_result_is_predictable():
    with pytest.raises(PipelineError) as e:
        run_pipeline(deps(FakeResumeExtractor(error=ExtractionError("truncated")),
                          FakeJDExtractor(error=ExtractionError("invalid"))), request())

    assert (e.value.stage, e.value.code) == ("resume", "truncated")


@pytest.mark.parametrize("index", [2, -1])
def test_a_role_that_is_not_in_the_jd_is_an_error(index):
    with pytest.raises(PipelineError) as e:
        run_pipeline(deps(), request(role_index=index))

    assert (e.value.stage, e.value.code) == ("role", "no_such_role")


def test_the_inputs_are_not_modified():
    req = request()
    before = (req.resume_file, req.jd_file, req.template)

    run_pipeline(deps(), req)

    assert (req.resume_file, req.jd_file, req.template) == before

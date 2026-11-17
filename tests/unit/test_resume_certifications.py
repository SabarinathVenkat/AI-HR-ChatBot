"""Certifications: kept with their source like every other line, offered when the resume has none, and given a section in the
Word file when the template has none (but only when there is something to show)."""
import io

import pytest
from docx import Document

from app.rmg.resume.conformance import check_conformance
from app.rmg.resume.edit import EditError, add_certification_as, remove_item, set_text
from app.rmg.resume.extract import ExtractedResume, to_resume
from app.rmg.resume.match import build_match_plan
from app.rmg.resume.model import MAX_CERTIFICATIONS, Education, Item, Origin, Resume
from app.rmg.resume.render import render_resume, template_gaps
from app.rmg.resume.template import W, paragraph_text
from tests.unit.resume_fakes import JD
from tests.unit.resume_templates import make_template


def orig(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


def resume(*certs) -> Resume:
    return Resume(name="Anil Verma", education=[Education(degree="B.E.", institution="Anna University", year="2015")],
                  highlights=[orig("A highlight.", "highlights.0")], certifications=[orig(c, f"certifications.{i}") for i, c in enumerate(certs)])


BASE = resume("Oracle Certified Professional, Java SE 11", "AWS Certified Developer")
PLAN = build_match_plan(BASE, JD.roles[0])


def template(**kw) -> bytes:
    out = io.BytesIO()
    make_template(highlights_subheading="Professional summary and Key highlights", **kw).save(out)
    return out.getvalue()


def lines(docx: bytes) -> list[str]:
    return [paragraph_text(p) for p in Document(io.BytesIO(docx)).element.body.iter(W + "p")]


# --- as lines with a source ---------------------------------------------------------------------------------------------

def test_certifications_saved_before_this_change_as_plain_text_are_still_read():
    old = '{"name": "A", "certifications": ["AWS Certified Developer", "Scrum Master"]}'

    certs = Resume.model_validate_json(old).certifications

    assert [(c.text, c.origin, c.source) for c in certs] == [
        ("AWS Certified Developer", Origin.ORIGINAL, "certifications.0"), ("Scrum Master", Origin.ORIGINAL, "certifications.1")]


def test_the_certifications_a_resume_lists_are_kept_as_its_own():
    result = to_resume(ExtractedResume(name="A", certifications=["AWS Certified Developer", "Scrum Master"]))

    assert [(c.text, c.source) for c in result.certifications] == [("AWS Certified Developer", "certifications.0"), ("Scrum Master", "certifications.1")]


def test_certifications_are_listed_with_the_resumes_other_items_by_path():
    assert ("certifications.1", BASE.certifications[1]) in list(BASE.all_items())


# --- adding, editing, removing ----------------------------------------------------------------------------------------------

def test_the_associate_can_add_a_certification_and_it_is_marked_as_theirs():
    result = add_certification_as(resume(), "Azure Fundamentals", by="user")

    cert = result.certifications[0]
    assert (cert.text, cert.origin, cert.source) == ("Azure Fundamentals", Origin.USER_ADDED, None)


def test_the_assistant_may_not_add_a_certification_because_it_is_a_claim():
    with pytest.raises(EditError) as e:
        add_certification_as(resume(), "Azure Fundamentals", by="assistant")
    assert e.value.code == "not_allowed"


@pytest.mark.parametrize("text,code", [("   ", "empty_text"), ("x" * 300, "too_long"), ("aws certified developer", "duplicate")])
def test_a_blank_oversized_or_repeated_certification_is_refused(text, code):
    with pytest.raises(EditError) as e:
        add_certification_as(BASE, text, by="user")
    assert e.value.code == code


def test_no_more_than_the_limit_can_be_added():
    full = resume(*[f"Certification {i}" for i in range(MAX_CERTIFICATIONS)])
    with pytest.raises(EditError) as e:
        add_certification_as(full, "One more", by="user")
    assert e.value.code == "full"


def test_a_certification_can_be_edited_and_removed_like_any_line():
    edited = set_text(BASE, BASE, PLAN, "certifications.1", "AWS Certified Solutions Architect 2025", by="user")
    removed = remove_item(BASE, "certifications.0")

    assert edited.certifications[1].origin is Origin.USER_ADDED
    assert [c.text for c in removed.certifications] == ["AWS Certified Developer"]


# --- in the Word file ---------------------------------------------------------------------------------------------------------

def test_a_template_that_has_a_certifications_section_gets_the_entries_in_it():
    out = render_resume(template(certifications=True), BASE).docx

    text = lines(out)
    assert text.count("CERTIFICATIONS") == 1 and "Oracle Certified Professional, Java SE 11" in text and "AWS Certified Developer" in text
    assert "Sample Certificate" not in text


def test_a_template_with_no_certifications_section_is_given_one_after_education_when_the_resume_has_certifications():
    out = render_resume(template(), BASE)

    text = lines(out.docx)
    assert "CERTIFICATIONS" in text and text.index("CERTIFICATIONS") > text.index("EDUCATION")
    assert text[text.index("CERTIFICATIONS") + 1:text.index("CERTIFICATIONS") + 3] == ["Oracle Certified Professional, Java SE 11", "AWS Certified Developer"]
    assert not any("certifications" in p.lower() and "no" in p.lower() for p in out.problems)


def test_the_added_section_looks_like_the_education_section_it_copies():
    doc = Document(io.BytesIO(render_resume(template(), BASE).docx))
    heading = {paragraph_text(p): p for p in doc.element.body.iter(W + "p")}
    education, certs = heading["EDUCATION"], heading["CERTIFICATIONS"]

    style = lambda p: p.find(f"{W}pPr/{W}pStyle").get(W + "val")  # noqa: E731
    assert style(education) == style(certs)


def test_a_resume_with_no_certifications_shows_no_certifications_section_at_all():
    for tpl in (template(), template(certifications=True)):
        assert "CERTIFICATIONS" not in lines(render_resume(tpl, resume()).docx)


def test_the_word_file_has_no_note_about_certifications_the_template_cannot_hold():
    assert template_gaps(template(), BASE) == []


def test_the_section_added_to_a_template_is_not_flagged_as_a_heading_the_template_does_not_have():
    tpl = template()
    out = render_resume(tpl, BASE).docx

    report = check_conformance(tpl, out, BASE)

    assert {c.name: c.status for c in report.checks}["sections"] == "pass", [(c.name, c.message) for c in report.checks if c.status != "pass"]
    assert {c.name: c.status for c in report.checks}["complete"] == "pass"


def test_a_resume_with_certifications_but_no_education_gets_the_section_after_skills():
    from app.rmg.resume.model import SkillGroup

    no_education = Resume(name="Nora", skill_groups=[SkillGroup(category="Backend", items=[orig("Java", "skills.0.0")])],
                          highlights=[orig("A highlight.", "highlights.0")], certifications=[orig("AWS Certified Developer", "certifications.0")])

    text = lines(render_resume(template(), no_education).docx)

    assert "EDUCATION" not in text and "CERTIFICATIONS" in text and text.index("CERTIFICATIONS") > text.index("SKILLS")

"""The years on the role line follow the template's own pattern: "Technical Analyst (10+ years exp)" gives
"Senior Java Developer (12+ years exp)", rounded down to whole years, not "12 years 5 months"."""
import io

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.rmg.resume.model import Item, Origin, Resume
from app.rmg.resume.render import render_resume, years_like_template
from app.rmg.resume.template import W, paragraph_text
from tests.unit.resume_templates import make_template


def resume(title="Senior Java Developer") -> Resume:
    return Resume(name="Ananya", role_title=Item(text=title, origin=Origin.ORIGINAL, source="title"),
                  highlights=[Item(text="A highlight.", origin=Origin.ORIGINAL, source="h.0")])


def template_with_role(*parts: str) -> bytes:
    """A template whose role line is made of these runs, like the company's: "Technical Analyst " and "(10+ years exp)"."""
    doc = make_template()
    role = next(p for p in doc.element.body.iter(W + "p") if paragraph_text(p) == "Sample Role 5 years")
    for run in list(role.iter(W + "r")):
        run.getparent().remove(run)
    for part in parts:
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = part
        text.set(qn("xml:space"), "preserve")
        run.append(text)
        role.append(run)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def role_runs(docx: bytes, start: str = "Senior Java Developer") -> list[str]:
    doc = Document(io.BytesIO(docx))
    role = next(p for p in doc.element.body.iter(W + "p") if paragraph_text(p).startswith(start))
    return ["".join(t.text or "" for t in r.iter(W + "t")) for r in role.iter(W + "r")]


# --- the pattern is the template's ---------------------------------------------------------------------------------------------

def test_the_company_pattern_gives_whole_years_rounded_down_with_the_templates_wording():
    out = render_resume(template_with_role("Technical Analyst ", "(10+ years exp)"), resume(), years_text="12 years 5 months").docx

    assert role_runs(out) == ["Senior Java Developer ", "(12+ years exp)"]  # still two parts, so the template's styling is kept


def test_the_pattern_also_works_when_the_template_writes_the_whole_role_line_as_one_run():
    out = render_resume(template_with_role("Technical Analyst (10+ years exp)"), resume(), years_text="12 years 5 months").docx

    assert role_runs(out) == ["Senior Java Developer (12+ years exp)"]


def test_a_template_without_a_plus_gets_no_plus():
    out = render_resume(template_with_role("Sample Role ", "(10 years)"), resume(), years_text="12 years 5 months").docx

    assert role_runs(out) == ["Senior Java Developer ", "(12 years)"]


def test_a_template_with_no_years_in_its_role_line_gets_whole_years_with_a_plus():
    out = render_resume(template_with_role("Sample Role"), resume(), years_text="12 years 5 months").docx

    assert role_runs(out) == ["Senior Java Developer 12+ years"]


def test_under_a_year_is_still_said_in_months():
    out = render_resume(template_with_role("Technical Analyst ", "(10+ years exp)"), resume(), years_text="8 months").docx

    assert role_runs(out) == ["Senior Java Developer ", "8 months"]


def test_no_years_at_all_leaves_just_the_title():
    out = render_resume(template_with_role("Technical Analyst ", "(10+ years exp)"), resume(), years_text="").docx

    assert role_runs(out)[0].startswith("Senior Java Developer")
    assert not any("years" in part for part in role_runs(out))


# --- a long role line is made compact -------------------------------------------------------------------------------------------

def test_a_long_title_gets_the_compact_form_so_the_banner_does_not_wrap():
    long_title = "Senior Data Scientist | ML Engineering & MLOps"
    out = render_resume(template_with_role("Technical Analyst ", "(10+ years exp)"), resume(long_title), years_text="10 years 3 months").docx

    assert role_runs(out, "Senior Data Scientist") == [long_title + " ", "(10+ yrs)"]


# --- the helper on its own -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sample,years,compact,expected", [
    ("(10+ years exp)", "12 years 5 months", False, "(12+ years exp)"),
    ("(10+ years exp)", "12 years 5 months", True, "(12+ yrs)"),
    ("10+ years", "9 years", False, "9+ years"),
    ("5 years", "8 years 2 months", False, "8 years"),
    ("5 years", "8 years 2 months", True, "8 yrs"),
    (None, "12 years 5 months", False, "12+ years"),
    (None, "12 years 5 months", True, "12+ yrs"),
    ("(10+ years exp)", "8 months", False, "8 months"),
    ("(10+ years exp)", "1 year", False, "(1+ years exp)"),
    ("(10+ years exp)", "", False, ""),
])
def test_years_like_template(sample, years, compact, expected):
    assert years_like_template(sample, years, compact=compact) == expected

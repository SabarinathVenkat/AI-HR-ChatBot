"""Rendering a Resume into a template by cloning the template's own paragraphs.

Templates are synthetic and built in memory. The output is read back and compared with what went in.
"""
import io

import pytest
from docx import Document
from lxml import etree
from docx.oxml import OxmlElement

from app.rmg.resume.model import Education, Item, Origin, Project, Resume, SkillGroup
from app.rmg.resume.render import TemplateError, render_resume
from app.rmg.resume.template import W, analyse, has_numbering, paragraph_text
from tests.unit.resume_templates import make_template


def save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def orig(text, n=0):
    return Item(text=text, origin=Origin.ORIGINAL, source=f"s.{n}")


def project(name, bullets, description="About it."):
    return Project(name=name, description=orig(description) if description else None, bullets=[orig(b) for b in bullets])


RESUME = Resume(
    name="Anil Verma", role_title=orig("Senior Backend Engineer"), summary=orig("Backend engineer who builds payment systems."),
    skill_groups=[SkillGroup(category="Backend", items=[orig("Java"), orig("Spring Boot")]),
                  SkillGroup(category="Cloud", items=[orig("AWS")]), SkillGroup(category="Data", items=[orig("SQL")])],
    education=[Education(degree="B.E. Computer Science", institution="Anna University", year="2015")],
    certifications=["AWS Certified Developer"],
    highlights=[orig(f"Highlight number {i}") for i in range(5)],
    projects=[project("Payments", ["One bullet only"]), project("Billing", ["First", "Second"], description=None),
              project("Reports", [f"Bullet {i}" for i in range(5)])],
)


def render(resume=RESUME, template=None, **kw):
    return render_resume(save(template or make_template(certifications=True)), resume, **kw)


def texts(result) -> list[str]:
    doc = Document(io.BytesIO(result.docx))
    return [paragraph_text(p) for p in doc.element.body.iter(W + "p")]


def paragraphs(result):
    return list(Document(io.BytesIO(result.docx)).element.body.iter(W + "p"))


# --- content ---------------------------------------------------------------------------------------

def test_the_header_is_filled_and_the_sample_text_is_gone():
    lines = texts(render(years_text="8 years"))

    assert "Anil Verma" in lines and "Senior Backend Engineer 8 years" in lines
    assert "Backend engineer who builds payment systems." in lines
    assert not [t for t in lines if "Sample" in t]


def test_skills_are_rebuilt_one_label_line_and_one_value_line_per_group():
    lines = texts(render())

    start = lines.index("Backend: ")
    assert lines[start:start + 6] == ["Backend: ", "Java, Spring Boot", "Cloud: ", "AWS", "Data: ", "SQL"]


def test_the_label_line_is_bold_and_the_value_line_is_not():
    paras = paragraphs(render())
    label = next(p for p in paras if paragraph_text(p) == "Backend: ")
    value = next(p for p in paras if paragraph_text(p) == "Java, Spring Boot")

    assert label.find(f".//{W}b") is not None and value.find(f".//{W}b") is None


def test_education_and_certifications_are_rendered_in_their_sections():
    lines = texts(render())

    assert "B.E. Computer Science Anna University 2015" in lines and "AWS Certified Developer" in lines


def test_highlights_become_one_bullet_each():
    result = render()
    bullets = [paragraph_text(p) for p in paragraphs(result) if has_numbering(p) and "Highlight" in paragraph_text(p)]

    assert bullets == [f"Highlight number {i}" for i in range(5)]


def test_projects_are_rebuilt_in_order_with_name_description_and_bullets():
    lines = texts(render())

    i = lines.index("Payments")
    assert lines[i:i + 3] == ["Payments", "About it.", "One bullet only"]
    j = lines.index("Billing")
    assert lines[j:j + 3] == ["Billing", "First", "Second"]  # no description: no description line
    k = lines.index("Reports")
    assert lines[k + 2:k + 7] == [f"Bullet {n}" for n in range(5)]


def test_a_project_name_stays_bold():
    name = next(p for p in paragraphs(render()) if paragraph_text(p) == "Reports")

    assert name.find(f".//{W}b") is not None


def spacing_after(p) -> str | None:
    e = p.find(f"{W}pPr/{W}spacing")
    return e.get(f"{W}after") if e is not None else None


def test_bullets_use_the_first_middle_and_last_prototype_formatting_of_the_template():
    template = make_template(certifications=True)
    first, _, mid, last = analyse(template).projects.blocks[0].bullets  # the template's richest block has four bullets
    for proto, after in ((first, "10"), (mid, "20"), (last, "30")):
        spacing = OxmlElement("w:spacing")
        spacing.set(f"{W}after", after)
        proto.find(f"{W}pPr").append(spacing)

    bullets = [p for p in paragraphs(render(template=template)) if paragraph_text(p).startswith("Bullet ")]

    assert all(has_numbering(p) for p in bullets)
    assert [spacing_after(p) for p in bullets] == ["10", "20", "20", "20", "30"]


def test_a_resume_with_no_projects_still_renders_and_the_sample_projects_are_removed():
    lines = texts(render(RESUME.model_copy(update={"projects": []})))

    assert not [t for t in lines if "Sample" in t]


def test_the_output_is_a_template_again_so_it_can_be_analysed():
    result = render()
    m = analyse(Document(io.BytesIO(result.docx)))

    assert m.missing() == [] and len(m.projects.blocks) == 3 and len(m.highlights.region) == 5


# --- safety: resume text is untrusted -----------------------------------------------------------------

def test_markup_characters_in_the_text_are_shown_as_they_are_never_turned_into_formatting():
    risky = RESUME.model_copy(update={"highlights": [orig("Led **critical** migration")]})

    paras = paragraphs(render(risky))
    bullet = next(p for p in paras if "critical" in paragraph_text(p))

    assert paragraph_text(bullet) == "Led **critical** migration" and bullet.find(f".//{W}b") is None


def test_control_characters_that_would_corrupt_the_file_are_removed():
    risky = RESUME.model_copy(update={"name": "Anil\x00 Ver\x0bma"})

    assert "Anil Verma" in texts(render(risky))


# --- layout care ---------------------------------------------------------------------------------------

def test_the_projects_heading_is_kept_with_the_first_project():
    heading = next(p for p in paragraphs(render()) if paragraph_text(p) == "PROJECT DETAILS")

    assert heading.find(f"{W}pPr/{W}keepNext") is not None


# --- no draft mark inside the document ------------------------------------------------------------------------------------

def header_text(result) -> str:
    doc = Document(io.BytesIO(result.docx))
    return " ".join(p.text for s in doc.sections for p in s.header.paragraphs)


def test_the_document_carries_no_draft_mark_in_its_header_or_body():
    """RMG asked for the word DRAFT not to appear in the resume itself; the file name says draft or final instead."""
    result = render()

    assert "DRAFT" not in header_text(result)
    assert not [t for t in texts(result) if "DRAFT" in t.upper()]


# --- content the template cannot hold, and bad templates ---------------------------------------------------

def test_content_the_template_has_no_place_for_is_reported_not_silently_lost():
    result = render(template=make_template(certifications=False))

    assert result.problems == ("certifications: the template has no such section, so they were not included",)


def test_a_template_with_everything_reports_no_problems():
    assert render().problems == ()


def test_a_template_with_missing_slots_is_refused_with_the_list():
    with pytest.raises(TemplateError) as e:
        render(template=make_template(numbered_bullets=False))

    assert e.value.code == "incomplete" and "projects" in e.value.missing


def test_something_that_is_not_a_docx_is_refused():
    with pytest.raises(TemplateError) as e:
        render_resume(b"not a docx", RESUME)

    assert e.value.code == "unreadable"


# --- spacing: the template's own pattern is reproduced, old spacers do not pile up ---------------------------------------

def highlight_block(result):
    """The paragraphs between the KEY HIGHLIGHTS heading and the PROJECT DETAILS heading, as text ('' for a blank line)."""
    lines = [paragraph_text(p) for p in paragraphs(result)]
    return lines[lines.index("KEY HIGHLIGHTS") + 1:lines.index("PROJECT DETAILS")]


def test_highlights_keep_one_blank_line_between_bullets_as_the_template_does():
    result = render(template=make_template(certifications=True, spaced_highlights=True))

    assert highlight_block(result) == ["Highlight number 0", "", "Highlight number 1", "", "Highlight number 2", "",
                                       "Highlight number 3", "", "Highlight number 4"]


def test_fewer_highlights_than_the_template_had_leave_no_leftover_blank_lines():
    two = RESUME.model_copy(update={"highlights": RESUME.highlights[:2]})

    assert highlight_block(render(two, template=make_template(certifications=True, spaced_highlights=True))) == [
        "Highlight number 0", "", "Highlight number 1"]


def test_a_template_without_spacers_gets_no_spacers():
    assert "" not in highlight_block(render())


# --- page layout: page 1 is a fixed block, projects start on page 2 ----------------------------------------------------

def test_the_projects_always_start_on_a_new_page_so_they_never_sit_on_the_first_page_sidebar():
    heading = next(p for p in paragraphs(render()) if paragraph_text(p) == "PROJECT DETAILS")
    order = [child.tag.split("}")[1] for child in heading.find(f"{W}pPr")]

    assert "pageBreakBefore" in order
    assert order.index("pStyle") < order.index("keepNext") < order.index("pageBreakBefore")  # the order Word requires


def test_spacer_lines_right_before_the_projects_heading_are_removed_so_no_blank_page_can_appear():
    result = render(template=make_template(certifications=True, spaced_highlights=True, blanks_before_projects=3))

    block = highlight_block(result)

    assert block[-1] == "Highlight number 4"  # no trailing blank lines


# --- the draft mark ---------------------------------------------------------------------------------------------------

def header_xml(result) -> str:
    doc = Document(io.BytesIO(result.docx))
    return " ".join(etree.tostring(s.header._element).decode() for s in doc.sections)


def test_there_is_no_watermark_in_the_document():
    assert "textpath" not in header_xml(render()) and "WaterMark" not in header_xml(render())


def test_a_degree_without_an_institution_renders_cleanly_with_no_none_or_double_spaces():
    thin = RESUME.model_copy(update={"education": [Education(degree="B.Tech Information Technology", year="2021")]})

    lines = texts(render(thin))

    assert "B.Tech Information Technology 2021" in lines
    assert not [t for t in lines if "None" in t or "  " in t]


def test_an_institution_without_a_degree_renders_too():
    thin = RESUME.model_copy(update={"education": [Education(institution="Anna University", year="2014")]})

    assert "Anna University 2014" in texts(render(thin))


# --- a long role line: the years are shortened so the banner does not wrap onto the summary ------------------------------

def test_a_long_role_line_gets_short_years_so_it_stays_on_one_line():
    long_title = RESUME.model_copy(update={"role_title": orig("Senior Data Scientist | ML Engineering & MLOps")})

    assert "Senior Data Scientist | ML Engineering & MLOps 10 yrs" in texts(render(long_title, years_text="10 years 3 months"))


def test_a_short_role_line_keeps_the_full_years():
    assert "Senior Backend Engineer 10 years 3 months" in texts(render(years_text="10 years 3 months"))


@pytest.mark.parametrize("given,short", [("10 years 3 months", "10 yrs"), ("1 year", "1 yr"), ("8 months", "8 months"), ("12 years", "12 yrs")])
def test_years_can_be_shortened(given, short):
    from app.rmg.resume.render import shorten_years

    assert shorten_years(given) == short


# --- work history: shown under the highlights, in the template's own styles, instead of being dropped -----------------------

from app.rmg.resume.model import Job  # noqa: E402
from app.rmg.resume.render import template_gaps  # noqa: E402

JOBS = [Job(company="Ideas2IT", title="Senior Data Scientist", start="May 2025", end="Present"),
        Job(company="Photon", title="Lead Data Scientist", start="Jan 2024", end="May 2025"),
        Job(title="Freelance developer", start="2020"), Job(company="Acme")]
WITH_JOBS = RESUME.model_copy(update={"jobs": JOBS})
SUB = "Professional summary and Key highlights"


def right_column(result):
    """The paragraphs from the KEY HIGHLIGHTS heading to the PROJECT DETAILS heading."""
    lines = [paragraph_text(p) for p in paragraphs(result)]
    return lines[lines.index("KEY HIGHLIGHTS") + 1:lines.index("PROJECT DETAILS")]


def test_work_history_follows_the_highlights_under_its_own_subheading_in_the_templates_styles():
    result = render(WITH_JOBS, template=make_template(certifications=True, highlights_subheading=SUB))

    column = right_column(result)
    assert column[0] == SUB  # the template's own subheading is still first
    start = column.index("Work history")
    assert column[start - 2:start] == ["Highlight number 4", ""]  # a blank line sets the new block apart
    assert column[start + 1:start + 5] == ["Senior Data Scientist, Ideas2IT (May 2025 – Present)", "Lead Data Scientist, Photon (Jan 2024 – May 2025)",
                                           "Freelance developer (from 2020)", "Acme"]
    bullets = [p for p in paragraphs(result) if paragraph_text(p).startswith(("Senior Data Scientist, Ideas2IT", "Acme"))]
    assert all(has_numbering(p) for p in bullets)  # the same bullet style as the highlights


def test_the_template_spacing_between_bullets_is_kept_in_the_work_history():
    result = render(WITH_JOBS, template=make_template(certifications=True, spaced_highlights=True, highlights_subheading=SUB))

    column = right_column(result)
    first = column.index("Senior Data Scientist, Ideas2IT (May 2025 – Present)")
    assert column[first + 1] == "" and column[first + 2].startswith("Lead Data Scientist")


def test_a_resume_with_no_highlights_still_shows_its_work_history():
    bare = WITH_JOBS.model_copy(update={"highlights": []})

    column = right_column(render(bare, template=make_template(certifications=True, highlights_subheading=SUB)))

    assert "Work history" in column and any(t.startswith("Senior Data Scientist, Ideas2IT") for t in column)


def test_a_template_with_no_subheading_cannot_hold_work_history_and_says_so():
    result = render(WITH_JOBS)

    assert "Work history" not in texts(result)
    assert any(p.startswith("work history:") for p in result.problems)


def test_no_jobs_means_no_work_history_block():
    assert "Work history" not in texts(render(RESUME, template=make_template(certifications=True, highlights_subheading=SUB)))


def test_the_gaps_say_in_plain_words_what_the_template_has_no_place_for():
    thin = RESUME.model_copy(update={"jobs": JOBS, "certifications": ["AWS Certified"]})

    gaps = template_gaps(save(make_template()), thin)

    assert any("Certifications" in g for g in gaps) and any("Work history" in g for g in gaps)
    assert template_gaps(save(make_template(certifications=True, highlights_subheading=SUB)), thin) == []

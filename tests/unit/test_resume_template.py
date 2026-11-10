"""Reading the structure of a resume template (a .docx) so a renderer can rebuild it.

The analyser finds where each slot lives (name, role line, summary, skills, education, highlights, projects) and keeps
one prototype paragraph for each kind of line, so new content can be made by cloning the template's own formatting.
The templates here are built in memory and are synthetic; the real template is not in the repository.
"""
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from app.rmg.resume.template import W, analyse, paragraph_text

SUMMARY = "A long sample summary sentence that describes the person in the template and goes on for a while so it is clearly the summary and not a heading."


def bullet(doc_or_cell, text):
    p = doc_or_cell.add_paragraph(text)
    ppr = p._p.get_or_add_pPr()
    num = OxmlElement("w:numPr")
    for tag, val in (("w:ilvl", "0"), ("w:numId", "1")):
        e = OxmlElement(tag)
        e.set(qn("w:val"), val)
        num.append(e)
    ppr.append(num)
    return p


def bold_para(container, text):
    p = container.add_paragraph()
    p.add_run(text).bold = True
    return p


def label_value(container, label, value):
    p = container.add_paragraph()
    p.add_run(label + ": ").bold = True
    container.add_paragraph(value)
    return p


def make_template(*, education_first=False, header_in_table=False, numbered_bullets=True, certifications=False, title_style=True):
    doc = Document()
    holder = doc
    if header_in_table:
        table = doc.add_table(rows=1, cols=1)
        holder = table.cell(0, 0)
    style = "Title" if title_style else "Normal"
    holder.add_paragraph("Sample Name", style=style)
    holder.add_paragraph("Sample Role 5 years", style=style)
    doc.add_paragraph(SUMMARY)

    def skills():
        doc.add_paragraph("SKILLS", style="Heading 1")
        label_value(doc, "Backend", "Java, Spring")
        label_value(doc, "Cloud", "AWS")

    def education():
        doc.add_paragraph("EDUCATION", style="Heading 1")
        p = doc.add_paragraph()
        p.add_run("B.E. Sample").bold = True
        p.add_run(" Sample University 2010")

    sections = [education, skills] if education_first else [skills, education]
    for section in sections:
        section()
    if certifications:
        doc.add_paragraph("CERTIFICATIONS", style="Heading 1")
        doc.add_paragraph("Sample Certificate")

    add = bullet if numbered_bullets else (lambda d, t: d.add_paragraph("• " + t))
    doc.add_paragraph("KEY HIGHLIGHTS", style="Heading 1")
    for i in range(3):
        add(doc, f"Sample highlight {i}")
    doc.add_paragraph("PROJECT DETAILS", style="Heading 1")
    for n in range(2):
        bold_para(doc, f"Sample Project {n}")
        doc.add_paragraph(f"Sample description {n}.")
        for i in range(4 if n == 0 else 2):
            add(doc, f"Sample bullet {n}.{i}")
        doc.add_paragraph("")
    return doc


def text_of(element):
    return paragraph_text(element) if element is not None else None


def test_the_header_lines_are_found_by_their_title_style():
    m = analyse(make_template())

    assert text_of(m.name) == "Sample Name" and text_of(m.role) == "Sample Role 5 years" and text_of(m.summary) == SUMMARY


def test_a_header_inside_a_table_cell_is_found_too():
    m = analyse(make_template(header_in_table=True))

    assert text_of(m.name) == "Sample Name" and text_of(m.summary) == SUMMARY


def test_skills_keep_a_label_prototype_and_a_value_prototype():
    m = analyse(make_template())

    assert text_of(m.skills.proto_label) == "Backend: " and text_of(m.skills.proto_value) == "Java, Spring"
    assert [paragraph_text(p) for p in m.skills.region] == ["Backend: ", "Java, Spring", "Cloud: ", "AWS"]


def test_sections_are_found_in_whatever_order_the_template_uses():
    m = analyse(make_template(education_first=True))

    assert text_of(m.skills.proto_label) == "Backend: " and [paragraph_text(p) for p in m.education.region] == ["B.E. Sample Sample University 2010"]


def test_an_optional_section_the_template_does_not_have_is_simply_absent():
    assert analyse(make_template()).certifications is None
    assert [paragraph_text(p) for p in analyse(make_template(certifications=True)).certifications.region] == ["Sample Certificate"]


def test_highlights_are_the_numbered_bullets_after_their_heading():
    m = analyse(make_template())

    assert [paragraph_text(p) for p in m.highlights.region] == [f"Sample highlight {i}" for i in range(3)]
    assert text_of(m.highlights.proto) == "Sample highlight 0"


def test_projects_are_split_into_blocks_with_prototypes_for_each_kind_of_line():
    m = analyse(make_template())
    projects = m.projects

    assert [paragraph_text(b.name) for b in projects.blocks] == ["Sample Project 0", "Sample Project 1"]
    assert [len(b.bullets) for b in projects.blocks] == [4, 2]
    assert text_of(projects.proto_name) == "Sample Project 0" and text_of(projects.proto_desc) == "Sample description 0."
    assert (text_of(projects.proto_first), text_of(projects.proto_mid), text_of(projects.proto_last)) == (
        "Sample bullet 0.0", "Sample bullet 0.2", "Sample bullet 0.3")
    assert projects.proto_blank is not None and paragraph_text(projects.proto_blank) == ""


def test_a_complete_template_has_nothing_missing():
    assert analyse(make_template()).missing() == []


def test_a_template_without_title_styles_reports_the_header_as_missing_instead_of_guessing():
    assert "name" in analyse(make_template(title_style=False)).missing()


def test_bullets_typed_as_a_character_are_not_recognised_so_highlights_and_projects_are_reported_missing():
    missing = analyse(make_template(numbered_bullets=False)).missing()

    assert "highlights" in missing and "projects" in missing


def test_analysing_does_not_change_the_document():
    doc = make_template()
    before = etree.tostring(doc.element.body)

    analyse(doc)

    assert etree.tostring(doc.element.body) == before


def test_the_notes_say_what_was_found_in_plain_words():
    notes = " ".join(analyse(make_template()).notes)

    assert "projects: 2 blocks" in notes and "highlights: 3 bullets" in notes


@pytest.mark.parametrize("tag", ["p"])
def test_the_word_namespace_helper_is_exported_for_the_renderer(tag):
    assert W + tag == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"

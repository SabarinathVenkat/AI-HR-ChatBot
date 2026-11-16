"""Finding the name, role and summary in a template: the summary must be the banner text, never a paragraph from below."""
from docx import Document

from app.rmg.resume.template import analyse, paragraph_text
from tests.unit.resume_templates import SUMMARY

PROJECT_TEXT = ("Led a large-scale modernization initiative by transitioning the platform from a traditional architecture to "
                "microservices and event-driven workflows on the cloud.")


def sections(doc):
    doc.add_paragraph("SKILLS", style="Heading 1")
    p = doc.add_paragraph()
    p.add_run("Backend: ").bold = True
    doc.add_paragraph("Java, Spring")
    doc.add_paragraph("EDUCATION", style="Heading 1")
    doc.add_paragraph("B.E. Sample University 2010")
    doc.add_paragraph("KEY HIGHLIGHTS", style="Heading 1")
    for i in range(2):
        bullet = doc.add_paragraph(f"Sample highlight {i}")
        bullet.paragraph_format.left_indent = 360
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        num = OxmlElement("w:numPr")
        for tag in ("w:ilvl", "w:numId"):
            e = OxmlElement(tag)
            e.set(qn("w:val"), "0" if tag == "w:ilvl" else "1")
            num.append(e)
        bullet._p.get_or_add_pPr().append(num)
    doc.add_paragraph("PROJECT DETAILS", style="Heading 1")
    p = doc.add_paragraph()
    p.add_run("Project Name").bold = True
    doc.add_paragraph(PROJECT_TEXT)


def header_table(doc, *, style="Normal", summary=True):
    """A banner like the company template's: name and role in one cell, a logo cell, the summary in a cell below."""
    table = doc.add_table(rows=2, cols=2)
    left = table.cell(0, 0)
    left.paragraphs[0].text = "Sample Profile"
    left.paragraphs[0].style = doc.styles[style]
    role = left.add_paragraph("Technical Analyst (10+ years exp)")
    role.style = doc.styles[style]
    if summary:
        table.cell(1, 0).paragraphs[0].text = SUMMARY
    return table


def test_a_summary_in_another_cell_of_the_header_table_is_found_when_the_header_has_no_title_style():
    doc = Document()
    header_table(doc)
    sections(doc)

    m = analyse(doc)

    assert paragraph_text(m.name) == "Sample Profile" and paragraph_text(m.role).startswith("Technical Analyst")
    assert paragraph_text(m.summary) == SUMMARY


def test_a_long_paragraph_further_down_the_page_is_never_taken_as_the_summary():
    doc = Document()
    header_table(doc, summary=False)  # this banner has no summary text at all
    sections(doc)

    m = analyse(doc)

    assert m.summary is None or paragraph_text(m.summary) != PROJECT_TEXT


def test_a_header_in_the_body_with_a_summary_still_works():
    doc = Document()
    doc.add_paragraph("Sample Name", style="Title")
    doc.add_paragraph("Sample Role", style="Title")
    doc.add_paragraph(SUMMARY)
    sections(doc)

    assert paragraph_text(analyse(doc).summary) == SUMMARY


def test_with_no_title_style_the_summary_below_the_name_is_found_before_any_section():
    doc = Document()
    doc.add_paragraph("Sample Name")
    doc.add_paragraph("Sample Role")
    doc.add_paragraph(SUMMARY)
    sections(doc)

    assert paragraph_text(analyse(doc).summary) == SUMMARY

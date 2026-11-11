"""Synthetic resume templates built in memory for the template and render tests (the real template is not in the repo)."""
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

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


def make_template(*, education_first=False, header_in_table=False, numbered_bullets=True, certifications=False, title_style=True,
                  spaced_highlights=False, blanks_before_projects=0):
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
        if spaced_highlights and i < 2:
            doc.add_paragraph("")  # the real template puts a blank line between highlight bullets
    for _ in range(blanks_before_projects):
        doc.add_paragraph("")  # spacer lines the real template puts before the projects heading
    doc.add_paragraph("PROJECT DETAILS", style="Heading 1")
    for n in range(2):
        bold_para(doc, f"Sample Project {n}")
        doc.add_paragraph(f"Sample description {n}.")
        for i in range(4 if n == 0 else 2):
            add(doc, f"Sample bullet {n}.{i}")
        doc.add_paragraph("")
    return doc

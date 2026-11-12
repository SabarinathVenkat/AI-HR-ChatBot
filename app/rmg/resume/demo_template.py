"""A small generic resume template (.docx), for trying the resume builder without the company template.

It is made up for demonstration and has the same kinds of parts a real template needs (a Title-style name and role line,
a summary, skills, education, key highlights with bullets, and projects). Create the file with:

    python -m app.rmg.resume.demo_template demo_template.docx

and upload it on the Setup tab as the RMG Head.
"""
import io
import sys

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

SAMPLE_SUMMARY = (
    "Sample summary: an experienced engineer who builds reliable software and works well with clients and teammates. "
    "This text is replaced with the associate's own summary."
)


def _bullet(doc, text: str) -> None:
    p = doc.add_paragraph(text)
    num = OxmlElement("w:numPr")
    for tag, value in (("w:ilvl", "0"), ("w:numId", "1")):
        element = OxmlElement(tag)
        element.set(qn("w:val"), value)
        num.append(element)
    p._p.get_or_add_pPr().append(num)


def make_demo_template() -> bytes:
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.add_paragraph("Sample Name", style="Title")
    doc.add_paragraph("Sample Role 5 years", style="Title")
    doc.add_paragraph(SAMPLE_SUMMARY)

    doc.add_paragraph("SKILLS", style="Heading 1")
    for label, values in (("Backend", "Java, Spring Boot"), ("Cloud", "AWS, Docker")):
        p = doc.add_paragraph()
        p.add_run(f"{label}: ").bold = True
        doc.add_paragraph(values)

    doc.add_paragraph("EDUCATION", style="Heading 1")
    p = doc.add_paragraph()
    p.add_run("B.E. Sample Degree").bold = True
    p.add_run(" Sample University 2010")

    doc.add_paragraph("KEY HIGHLIGHTS", style="Heading 1")
    doc.add_paragraph().add_run("Professional summary and Key highlights").bold = True  # the work history goes under this
    for i in range(3):
        _bullet(doc, f"Sample highlight {i + 1}")

    doc.add_paragraph("PROJECT DETAILS", style="Heading 1")
    for n in range(2):
        name = doc.add_paragraph()
        name.add_run(f"Sample Project {n + 1}").bold = True
        doc.add_paragraph("Sample project description.")
        for i in range(3):
            _bullet(doc, f"Sample project bullet {i + 1}")
        doc.add_paragraph("")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "demo_template.docx"
    with open(target, "wb") as f:
        f.write(make_demo_template())
    print(f"Wrote {target}")

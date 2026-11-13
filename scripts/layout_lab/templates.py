"""Made-up resume templates for the layout lab: some tidy, some with the kinds of mistakes real templates have.

Each builder returns (docx bytes, list of the mistakes it contains). The mistakes are the point: the renderer should
still produce a good resume from every one of them.
"""
import io

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

SUMMARY = ("A long sample summary sentence that describes the person in the template and goes on for a while so it is "
           "clearly the summary and not a heading.")


def _bullet_numbered(container, text):
    p = container.add_paragraph(text)
    num = OxmlElement("w:numPr")
    for tag, val in (("w:ilvl", "0"), ("w:numId", "1")):
        e = OxmlElement(tag)
        e.set(qn("w:val"), val)
        num.append(e)
    p._p.get_or_add_pPr().append(num)
    return p


def _bullet_typed(container, text):
    return container.add_paragraph("• " + text)


def _bold(container, text):
    p = container.add_paragraph()
    p.add_run(text).bold = True
    return p


def _label_value(container, label, value):
    p = container.add_paragraph()
    p.add_run(label + ": ").bold = True
    container.add_paragraph(value)


def _spacing(p, *, line=None, rule=None, before=None, after=None):
    sp = p._p.get_or_add_pPr().find(qn("w:spacing"))
    if sp is None:
        sp = OxmlElement("w:spacing")
        p._p.get_or_add_pPr().append(sp)
    if line is not None:
        sp.set(qn("w:line"), str(line))
        sp.set(qn("w:lineRule"), rule or "auto")
    if before is not None:
        sp.set(qn("w:before"), str(before))
    if after is not None:
        sp.set(qn("w:after"), str(after))


def _page_break(container):
    container.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _head(c, text, *, caps=False, blanks=0):
    for _ in range(blanks):
        c.add_paragraph("")
    if caps:
        _bold(c, text)
    else:
        c.add_paragraph(text, style="Heading 1")


def _side(c, *, caps=False, blanks=0, order=("skills", "education")):
    def skills():
        _head(c, "SKILLS", caps=caps, blanks=blanks)
        _label_value(c, "Backend", "Java, Spring Boot")
        _label_value(c, "Cloud", "AWS, Docker")

    def education():
        _head(c, "EDUCATION", caps=caps, blanks=blanks)
        p = c.add_paragraph()
        p.add_run("B.E. Sample Degree").bold = True
        p.add_run(" Sample University 2010")

    for name in order:
        {"skills": skills, "education": education}[name]()


def _body(c, *, bullet, caps=False, blanks=0, subheading=True, projects_desc=True):
    _head(c, "KEY HIGHLIGHTS", caps=caps, blanks=blanks)
    if subheading:
        _bold(c, "Professional summary and Key highlights")
    for i in range(3):
        bullet(c, f"Sample highlight {i + 1}")
    _head(c, "PROJECT DETAILS", caps=caps, blanks=blanks)
    for n in range(2):
        _bold(c, f"Sample Project {n + 1}")
        if projects_desc:
            c.add_paragraph("Sample project description.")
        for i in range(3):
            bullet(c, f"Sample project bullet {i + 1}")
        c.add_paragraph("")


def _banner(c):
    c.add_paragraph("Sample Name", style="Title")
    c.add_paragraph("Sample Role 5 years", style="Title")
    c.add_paragraph(SUMMARY)


def _save(doc) -> bytes:
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _margins(doc, left=1.0, right=1.0, top=1.0, bottom=1.0, a4=False):
    s = doc.sections[0]
    if a4:
        s.page_width, s.page_height = Inches(8.27), Inches(11.69)
    s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = (Inches(x) for x in (left, right, top, bottom))


def _two_columns(doc, *, left_width, right_width, row_height, exact=False):
    table = doc.add_table(rows=1, cols=2)
    table.autofit = False
    left, right = table.rows[0].cells
    left.width, right.width = Inches(left_width), Inches(right_width)
    height = OxmlElement("w:trHeight")
    height.set(qn("w:val"), str(int(row_height * 1440)))
    height.set(qn("w:hRule"), "exact" if exact else "atLeast")
    table.rows[0]._tr.get_or_add_trPr().append(height)
    return left, right


def _drop_first_blank(cell):
    first = cell.paragraphs[0]
    if not first.text:
        first._p.getparent().remove(first._p)


# --- the templates ----------------------------------------------------------------------------------------

def classic():
    doc = Document()
    doc.styles["Normal"].font.size = Pt(10.5)
    _banner(doc)
    _side(doc)
    _body(doc, bullet=_bullet_numbered)
    return _save(doc), []


def typed_bullets_caps_headings():
    doc = Document()
    _banner(doc)
    _side(doc, caps=True)
    _body(doc, bullet=_bullet_typed, caps=True)
    return _save(doc), ["headings are bold text, bullets are typed characters"]


def blank_lines_everywhere():
    doc = Document()
    _banner(doc)
    _side(doc, blanks=3)
    for _ in range(4):
        doc.add_paragraph("")
    _body(doc, bullet=_bullet_numbered, blanks=3)
    for _ in range(6):
        doc.add_paragraph("")
    return _save(doc), ["three or more blank lines before every heading", "trailing blank lines"]


def manual_page_breaks():
    doc = Document()
    _banner(doc)
    _side(doc)
    _page_break(doc)
    _body(doc, bullet=_bullet_numbered)
    _page_break(doc)
    return _save(doc), ["a typed page break in the middle", "a page break at the end (a blank last page)"]


def two_column_table():
    doc = Document()
    _margins(doc, 0.5, 0.5, 0.5, 0.5)
    _banner(doc)
    left, right = _two_columns(doc, left_width=2.3, right_width=5.2, row_height=7.0)
    _side(left)
    _body(right, bullet=_bullet_numbered)
    _drop_first_blank(left)
    _drop_first_blank(right)
    return _save(doc), []


def two_column_exact_row_height():
    doc = Document()
    _margins(doc, 0.5, 0.5, 0.5, 0.5)
    _banner(doc)
    left, right = _two_columns(doc, left_width=2.3, right_width=5.2, row_height=4.2, exact=True)
    _side(left)
    _body(right, bullet=_bullet_numbered)
    _drop_first_blank(left)
    _drop_first_blank(right)
    return _save(doc), ["the two-column row has a fixed height, so long content is cut off"]


def exact_line_spacing_too_tight():
    doc = Document()
    doc.styles["Normal"].font.size = Pt(12)
    _banner(doc)
    _side(doc)
    _body(doc, bullet=_bullet_numbered)
    for p in doc.paragraphs:
        _spacing(p, line=200, rule="exact")
    return _save(doc), ["line height is fixed smaller than the font, so text is clipped"]


def narrow_sidebar_big_font():
    doc = Document()
    _margins(doc, 0.4, 0.4, 0.4, 0.4, a4=True)
    _banner(doc)
    left, right = _two_columns(doc, left_width=1.5, right_width=6.0, row_height=6.0)
    _side(left)
    _body(right, bullet=_bullet_numbered)
    _drop_first_blank(left)
    _drop_first_blank(right)
    for p in left.paragraphs:
        for r in p.runs:
            r.font.size = Pt(13)
    return _save(doc), ["a very narrow sidebar with large text"]


def inconsistent_fonts():
    doc = Document()
    _banner(doc)
    _side(doc)
    _body(doc, bullet=_bullet_numbered)
    fonts = ["Arial", "Times New Roman", "Courier New", "Verdana"]
    sizes = [9, 11, 14, 8]
    for i, p in enumerate(doc.paragraphs):
        for r in p.runs:
            r.font.name = fonts[i % 4]
            r.font.size = Pt(sizes[i % 4])
            r.font.color.rgb = RGBColor(0x20 * (i % 7), 0x10 * (i % 5), 0x30 * (i % 3))
    return _save(doc), ["mixed fonts, sizes and colours from paragraph to paragraph"]


def education_first_a4_wide_margins():
    doc = Document()
    _margins(doc, 1.6, 1.6, 1.0, 1.0, a4=True)
    _banner(doc)
    _side(doc, order=("education", "skills"))
    _body(doc, bullet=_bullet_numbered, subheading=False, projects_desc=False)
    return _save(doc), ["education before skills", "no subheading and no project descriptions", "very wide margins"]


def header_in_table_tight():
    doc = Document()
    _margins(doc, 0.7, 0.7, 0.6, 0.6)
    t = doc.add_table(rows=1, cols=1)
    _banner(t.cell(0, 0))
    _drop_first_blank(t.cell(0, 0))
    _side(doc)
    _body(doc, bullet=_bullet_numbered)
    for p in doc.paragraphs:
        _spacing(p, before=0, after=0)
    return _save(doc), ["the header is inside a table", "no spacing at all between paragraphs"]


def missing_sections():
    doc = Document()
    _banner(doc)
    doc.add_paragraph("SKILLS", style="Heading 1")
    _label_value(doc, "Backend", "Java")
    doc.add_paragraph("KEY HIGHLIGHTS", style="Heading 1")
    for i in range(2):
        _bullet_numbered(doc, f"Sample highlight {i}")
    return _save(doc), ["there is no projects section and no education section"]


def plain_text_only():
    doc = Document()
    for line in ("Jane Doe", "Engineer", "Worked on many things.", "Java Python", "Did stuff at Acme."):
        doc.add_paragraph(line)
    return _save(doc), ["no headings or structure at all"]


TEMPLATES = {
    "classic": classic,
    "typed_bullets_caps_headings": typed_bullets_caps_headings,
    "blank_lines_everywhere": blank_lines_everywhere,
    "manual_page_breaks": manual_page_breaks,
    "two_column_table": two_column_table,
    "two_column_exact_row_height": two_column_exact_row_height,
    "exact_line_spacing_too_tight": exact_line_spacing_too_tight,
    "narrow_sidebar_big_font": narrow_sidebar_big_font,
    "inconsistent_fonts": inconsistent_fonts,
    "education_first_a4_wide_margins": education_first_a4_wide_margins,
    "header_in_table_tight": header_in_table_tight,
    "missing_sections": missing_sections,
    "plain_text_only": plain_text_only,
}

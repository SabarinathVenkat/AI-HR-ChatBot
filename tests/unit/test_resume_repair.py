"""Mistakes that real templates contain are repaired in the finished document, and no text is ever removed."""
from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.rmg.resume.repair import repair_layout
from app.rmg.resume.template import W, is_blank, paragraph_text


def texts(doc):
    return [paragraph_text(p) for p in doc.element.body.iter(W + "p") if paragraph_text(p)]


def test_a_fixed_table_row_height_becomes_a_minimum_so_long_content_is_not_cut_off():
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    height = OxmlElement("w:trHeight")
    height.set(qn("w:val"), "3000")
    height.set(qn("w:hRule"), "exact")
    table.rows[0]._tr.get_or_add_trPr().append(height)

    repair_layout(doc)

    assert doc.element.body.find(f".//{W}trHeight").get(W + "hRule") == "atLeast"
    assert doc.element.body.find(f".//{W}trHeight").get(W + "val") == "3000"


def test_a_fixed_line_height_becomes_a_minimum_so_letters_are_not_clipped():
    doc = Document()
    p = doc.add_paragraph("Some text")
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:line"), "200")
    spacing.set(qn("w:lineRule"), "exact")
    p._p.get_or_add_pPr().append(spacing)

    repair_layout(doc)

    assert p._p.find(f"{W}pPr/{W}spacing").get(W + "lineRule") == "atLeast"


def test_typed_page_breaks_are_removed_and_the_text_around_them_stays():
    doc = Document()
    doc.add_paragraph("Before")
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    mixed = doc.add_paragraph("Same line ")
    mixed.add_run().add_break(WD_BREAK.PAGE)
    mixed.add_run("after break")

    repair_layout(doc)

    assert "".join(doc.element.body.xml).count('w:type="page"') == 0
    assert texts(doc) == ["Before", "Same line after break"]


def test_runs_of_blank_lines_become_one_and_trailing_blank_lines_go():
    doc = Document()
    doc.add_paragraph("One")
    for _ in range(4):
        doc.add_paragraph("")
    doc.add_paragraph("Two")
    for _ in range(3):
        doc.add_paragraph("")

    repair_layout(doc)

    body = [p for p in doc.element.body.iter(W + "p")]
    assert [paragraph_text(p) for p in body] == ["One", "", "Two"]


def test_a_heading_is_kept_with_what_follows_and_a_bullet_is_not_split():
    doc = Document()
    heading = doc.add_paragraph("SKILLS", style="Heading 1")
    bullet = doc.add_paragraph("A bullet")
    num = OxmlElement("w:numPr")
    bullet._p.get_or_add_pPr().append(num)

    repair_layout(doc)

    assert heading._p.find(f"{W}pPr/{W}keepNext") is not None
    assert bullet._p.find(f"{W}pPr/{W}keepLines") is not None


def test_repairing_twice_changes_nothing_more():
    doc = Document()
    doc.add_paragraph("A")
    doc.add_paragraph("")
    doc.add_paragraph("")
    doc.add_paragraph("B", style="Heading 1")
    repair_layout(doc)
    once = doc.element.body.xml

    repair_layout(doc)

    assert doc.element.body.xml == once
    assert not is_blank(next(iter(doc.element.body.iter(W + "p"))))


def test_inside_a_table_cell_keep_with_next_is_switched_off_so_the_row_is_not_moved_to_the_next_page():
    doc = Document()
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    heading = cell.add_paragraph("SKILLS", style="Heading 1")  # the style itself says keep with next
    plain = cell.add_paragraph("Java")

    repair_layout(doc)

    for p in (heading, plain):
        assert p._p.find(f"{W}pPr/{W}keepNext").get(W + "val") == "0"


def test_inside_a_cell_only_headings_after_the_first_keep_with_next():
    doc = Document()
    cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    first = cell.add_paragraph("SKILLS", style="Heading 1")
    text = cell.add_paragraph("Java")
    second = cell.add_paragraph("EDUCATION", style="Heading 1")

    repair_layout(doc)

    assert first._p.find(f"{W}pPr/{W}keepNext").get(W + "val") == "0"
    assert text._p.find(f"{W}pPr/{W}keepNext").get(W + "val") == "0"
    assert second._p.find(f"{W}pPr/{W}keepNext").get(W + "val") is None  # no value means "on"

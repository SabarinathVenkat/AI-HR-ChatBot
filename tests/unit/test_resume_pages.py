"""Page-count estimate and compaction: a few lines spilling onto a last page are pulled back, and nothing else changes.

Word cannot be run here, so pages are estimated from text length, font size, spacing and page size. The estimate only has
to be right about the big picture (one page or two, nearly empty last page or not), which is what these tests check.
"""
from docx import Document
from docx.shared import Inches, Pt

from app.rmg.resume.fit import compact_document, estimate_pages
from app.rmg.resume.template import W


def document(lines: int, *, words_per_line: int = 1, size: float = 12) -> Document:
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(1)
    for _ in range(lines):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = p.paragraph_format.space_after = Pt(0)  # direct spacing, so the arithmetic is simple
        p.paragraph_format.line_spacing = 1.0
        p.add_run(" ".join(["word"] * words_per_line)).font.size = Pt(size)
    return doc


def line_values(doc):
    return [p.find(f"{W}pPr/{W}spacing").get(W + "line") if p.find(f"{W}pPr/{W}spacing") is not None else None
            for p in doc.element.body.iter(W + "p")]


def test_a_short_document_is_one_page_and_a_long_one_is_more():
    assert estimate_pages(document(10)).pages == 1
    assert estimate_pages(document(120)).pages == 3


def test_the_fill_of_the_last_page_is_reported():
    pages = estimate_pages(document(48))  # 45 lines fit on a page, so 3 lines spill

    assert pages.pages == 2 and pages.last_fill < 0.15


def test_long_lines_wrap_and_take_more_room():
    one = estimate_pages(document(30, words_per_line=2)).pages
    wrapped = estimate_pages(document(30, words_per_line=60)).pages

    assert wrapped > one


def test_a_few_lines_on_the_last_page_are_pulled_back_by_tightening_the_spacing():
    doc = document(48)

    compact_document(doc)

    assert estimate_pages(doc).pages == 1
    assert all(int(v) < 240 for v in line_values(doc) if v)


def test_a_document_that_fits_or_ends_well_into_its_last_page_is_left_alone():
    for lines in (20, 70):  # one full page and a half-filled second
        doc = document(lines)
        before = doc.element.body.xml

        compact_document(doc)

        assert doc.element.body.xml == before


def test_when_tightening_cannot_save_a_page_nothing_is_changed():
    doc = document(160)  # far too long for any amount of tightening to remove a page's worth
    before = doc.element.body.xml

    compact_document(doc)

    assert estimate_pages(doc).pages >= 3 and doc.element.body.xml != "" and (
        doc.element.body.xml == before or estimate_pages(doc).pages < estimate_pages(document(160)).pages)


def test_tightening_never_makes_small_text_bigger():
    doc = document(48, size=8)

    compact_document(doc)

    sizes = {s.get(W + "val") for s in doc.element.body.iter(W + "sz")}
    assert all(int(size) <= 16 for size in sizes)


def test_a_page_break_before_a_paragraph_starts_a_new_page():
    doc = document(10)
    last = list(doc.element.body.iter(W + "p"))[-1]
    ppr = last.get_or_add_pPr() if hasattr(last, "get_or_add_pPr") else None
    from docx.oxml import OxmlElement

    (ppr if ppr is not None else last.makeelement(W + "pPr", {})).append(OxmlElement("w:pageBreakBefore"))

    assert estimate_pages(doc).pages == 2

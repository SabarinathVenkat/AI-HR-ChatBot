"""Measuring a finished resume's pages: the mistakes a person would see (blank page, cut-off text, text off the edge, a heading
left alone at the bottom, too many pages), found in code from the pages as they were drawn.
"""
import io

from docx import Document

from app.rmg.resume.layout_check import LibreOfficeRenderer, measure, soffice_binary
from tests.unit.pdf_fakes import lines_down, make_pdf
from tests.unit.resume_templates import make_template


def docx_with(*texts: str) -> bytes:
    doc = Document()
    for text in texts:
        doc.add_paragraph(text)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def sectioned_docx() -> bytes:
    out = io.BytesIO()
    make_template(highlights_subheading="Professional summary and Key highlights").save(out)
    return out.getvalue()


FULL = lines_down(700, 30)  # a page with plenty of text on it


def problems(pdf: bytes, docx: bytes | None = None, **kw) -> list[str]:
    return list(measure(pdf, docx or docx_with(*(t for _, _, t in FULL)), **kw).problems)


# --- what is fine --------------------------------------------------------------------------------------------------------

def test_a_full_page_of_text_that_is_all_there_has_no_problems():
    assert problems(make_pdf([FULL])) == []


def test_the_number_of_pages_is_reported_and_the_first_pages_come_back_as_pictures():
    result = measure(make_pdf([FULL, FULL, FULL, FULL]), docx_with(*(t for _, _, t in FULL)), want_images=3)

    assert result.pages == 4 and len(result.images) == 3 and all(img[:8] == b"\x89PNG\r\n\x1a\n" for img in result.images)


# --- what is wrong -------------------------------------------------------------------------------------------------------------

def test_a_blank_page_in_the_middle_is_a_problem():
    found = problems(make_pdf([FULL, [(60, 700, "Just two words")], FULL]))

    assert any("page 2" in p and "blank" in p for p in found)


def test_a_last_page_with_only_a_stray_word_or_two_is_a_problem_but_a_short_real_last_page_is_not():
    assert any("page 2" in p for p in problems(make_pdf([FULL, [(60, 700, "end")]])))
    assert problems(make_pdf([FULL, lines_down(700, 4)]), docx_with(*(t for _, _, t in FULL + lines_down(700, 4)))) == []


def test_text_that_runs_off_the_page_edge_is_a_problem():
    found = problems(make_pdf([FULL + [(600, 300, "pushed off the right edge of the page")]]))

    assert any("edge" in p for p in found)


def test_a_heading_left_alone_at_the_bottom_of_a_page_is_a_problem_and_one_with_content_is_not():
    alone = make_pdf([lines_down(700, 30) + [(60, 40, "SKILLS")], lines_down(700, 20)])
    with_content = make_pdf([lines_down(700, 30) + [(60, 300, "SKILLS")] + [(60, 280 - 14 * n, f"Java and Kafka number {n}") for n in range(3)]])

    docx = sectioned_docx()
    assert any("SKILLS" in p and "nothing under" in p for p in measure(alone, docx).problems)
    assert not any("nothing under" in p for p in measure(with_content, docx).problems)


def test_text_that_is_in_the_file_but_missing_from_the_drawn_pages_is_reported_as_cut_off():
    wanted = docx_with(*(t for _, _, t in FULL), "A whole paragraph that Word never drew because a fixed height hid it " * 3)

    found = problems(make_pdf([FULL]), wanted)

    assert any("cut off" in p for p in found)


def test_more_pages_than_the_limit_is_a_problem():
    found = problems(make_pdf([FULL] * 4), max_pages=3)

    assert any("4 pages" in p for p in found)


# --- the renderer ----------------------------------------------------------------------------------------------------------------

def test_with_no_office_program_installed_there_is_simply_no_renderer(monkeypatch):
    monkeypatch.setattr("app.rmg.resume.layout_check.shutil.which", lambda name: None)

    assert soffice_binary() is None


def test_a_renderer_that_fails_returns_nothing_instead_of_raising(tmp_path):
    renderer = LibreOfficeRenderer(str(tmp_path / "does-not-exist"), timeout=5)

    assert renderer(docx_with("hello")) is None

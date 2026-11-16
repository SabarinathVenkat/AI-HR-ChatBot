"""A banner with a fixed-size background keeps its size: a short summary must not pull the page up under it, and a long
one must not run out of it."""
import io

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.rmg.resume.fit import height_of
from app.rmg.resume.model import Item, Origin, Resume
from app.rmg.resume.render import render_resume
from app.rmg.resume.template import W, analyse, paragraph_text
from tests.unit.resume_templates import make_template

LONG_SUMMARY = ("A sample banner summary that runs over several lines so the banner has a real height to keep. " * 4).strip()


def banner_template(row_min_twips: int = 224) -> bytes:
    doc = make_template(highlights_subheading="Professional summary and Key highlights")
    # move the name, role and summary into a two-row table like the company banner
    body = doc.element.body
    paragraphs = [p for p in body.iter(W + "p")][:3]
    table = doc.add_table(rows=2, cols=1)
    cell0, cell1 = table.cell(0, 0)._tc, table.cell(1, 0)._tc
    for p in paragraphs[:2]:
        cell0.insert(len(cell0) - 1, p)
    paragraphs[2].find(W + "r").find(W + "t").text = LONG_SUMMARY
    cell1.insert(len(cell1) - 1, paragraphs[2])
    for cell in (cell0, cell1):  # a cell starts with one empty paragraph: take it out
        first = cell.findall(W + "p")[0]
        if not paragraph_text(first):
            cell.remove(first)
    height = OxmlElement("w:trHeight")
    height.set(qn("w:val"), str(row_min_twips))
    height.set(qn("w:hRule"), "atLeast")
    table.rows[1]._tr.get_or_add_trPr().append(height)
    body.remove(table._tbl)
    body.insert(0, table._tbl)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def resume(summary: str) -> Resume:
    return Resume(name="A B", summary=Item(text=summary, origin=Origin.ORIGINAL, source="summary"),
                  highlights=[Item(text="A highlight.", origin=Origin.ORIGINAL, source="h.0")])


def summary_row_height_twips(docx: bytes) -> int:
    doc = Document(io.BytesIO(docx))
    row = next(p for p in doc.element.body.iter(W + "p") if paragraph_text(p).startswith(("Short", "A sample banner"))).getparent().getparent()
    return int(row.find(f"{W}trPr/{W}trHeight").get(W + "val"))


def test_a_shorter_summary_keeps_the_banner_row_as_tall_as_the_samples_text_made_it():
    template = banner_template()
    sample_points = height_of(analyse(Document(io.BytesIO(template))).summary, Document(io.BytesIO(template)))

    out = render_resume(template, resume("Short summary.")).docx

    assert summary_row_height_twips(out) >= int(sample_points * 20) - 20


def test_a_summary_that_fits_the_samples_height_changes_nothing_else_about_the_row():
    template = banner_template(row_min_twips=224)

    out = render_resume(template, resume(LONG_SUMMARY)).docx

    assert summary_row_height_twips(out) >= 224


def test_a_summary_longer_than_the_sample_is_tightened_so_it_stays_inside_the_banner():
    template = banner_template()
    sample_doc = Document(io.BytesIO(template))
    sample_points = height_of(analyse(sample_doc).summary, sample_doc)
    longer = LONG_SUMMARY + " " + LONG_SUMMARY

    out = render_resume(template, resume(longer)).docx

    doc = Document(io.BytesIO(out))
    summary = next(p for p in doc.element.body.iter(W + "p") if paragraph_text(p) == longer)
    assert height_of(summary, doc) <= sample_points * 1.05 or any(s.get(W + "lineRule") for s in summary.iter(W + "spacing"))


def test_a_header_that_is_not_in_a_table_is_left_alone():
    doc = make_template()
    buf = io.BytesIO()
    doc.save(buf)

    out = render_resume(buf.getvalue(), resume("Short summary.")).docx

    assert "trHeight" not in Document(io.BytesIO(out)).element.xml


def test_a_long_summary_in_a_plain_template_is_not_tightened_because_nothing_limits_it():
    doc = make_template()
    buf = io.BytesIO()
    doc.save(buf)

    out = render_resume(buf.getvalue(), resume(LONG_SUMMARY * 3))

    summary = next(p for p in Document(io.BytesIO(out.docx)).element.body.iter(W + "p") if paragraph_text(p).startswith("A sample banner"))
    assert not any(s.get(W + "lineRule") for s in summary.iter(W + "spacing")) and not any("banner" in p for p in out.problems)

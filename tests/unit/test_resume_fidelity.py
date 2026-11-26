"""The finished resume keeps the template's page setup, alignment, indents and fonts.

A resume is poured into a copy of the template, so it normally matches. These tests damage the finished file in the ways that
happen in practice (a margin changed, a bullet centred, a stray font) and check that the template's settings come back, that
the words never change, and that what a template does on purpose is left alone.
"""
import io

from docx import Document
from docx.shared import Inches, Pt
from lxml import etree

from app.rmg.resume.fidelity import format_differences, restore_format
from app.rmg.resume.render import render_resume
from app.rmg.resume.template import W, is_bullet, paragraph_text
from tests.unit.resume_templates import make_template
from tests.unit.test_resume_badges import picture
from tests.unit.test_resume_render import RESUME


def template_bytes(**options) -> bytes:
    out = io.BytesIO()
    make_template(**options).save(out)
    return out.getvalue()


def template_and_output(**options):
    template = template_bytes(**options)
    return Document(io.BytesIO(template)), Document(io.BytesIO(render_resume(template, RESUME).docx)), template


def words(doc) -> list[str]:
    return [paragraph_text(p) for p in doc.element.body.iter(W + "p")]


def jc_of(p):
    node = p.find(f"{W}pPr/{W}jc")
    return node.get(W + "val") if node is not None else None


def test_a_normal_render_already_matches_so_nothing_is_changed():
    template, output, _ = template_and_output()

    assert format_differences(template, output) == []
    assert restore_format(template, output) == []


def test_margins_page_size_and_orientation_are_put_back():
    template, output, _ = template_and_output()
    section = output.sections[0]
    section.left_margin, section.top_margin = Inches(0.2), Inches(2)
    section.page_width = Inches(5)

    assert any("margins" in d for d in format_differences(template, output)) and any("page size" in d for d in format_differences(template, output))
    fixed = restore_format(template, output)

    assert any("margins" in f for f in fixed) and any("page size" in f for f in fixed)
    assert format_differences(template, output) == []
    assert output.sections[0].left_margin == template.sections[0].left_margin
    assert output.sections[0].page_width == template.sections[0].page_width


def test_a_centred_or_justified_or_indented_bullet_goes_back_to_the_templates_look():
    template, output, _ = template_and_output()
    bullets = [p for p in output.element.body.iter(W + "p") if is_bullet(p) and paragraph_text(p)]
    assert len(bullets) >= 3
    from docx.text.paragraph import Paragraph

    first = Paragraph(bullets[0], output._body)
    first.alignment = 1  # centre
    first.paragraph_format.left_indent = Inches(1.5)
    Paragraph(bullets[1], output._body).alignment = 3  # justified

    assert any("bullet" in d for d in format_differences(template, output))
    fixed = restore_format(template, output)

    assert any("bullet" in f for f in fixed)
    assert format_differences(template, output) == []
    assert jc_of(bullets[0]) is None and jc_of(bullets[1]) is None
    assert first.paragraph_format.left_indent in (None, 0) or first.paragraph_format.left_indent == Paragraph(bullets[2], output._body).paragraph_format.left_indent


def test_a_font_or_size_the_template_does_not_use_is_removed_and_the_words_are_untouched():
    template, output, _ = template_and_output()
    before = words(output)
    run = next(r for p in output.paragraphs if is_bullet(p._p) and p.text for r in p.runs)
    run.font.name = "Comic Sans MS"
    run.font.size = Pt(40)

    assert any("fonts" in d for d in format_differences(template, output))
    fixed = restore_format(template, output)

    assert any("font" in f for f in fixed) and any("size" in f for f in fixed)
    assert run.font.name is None and run.font.size is None
    assert words(output) == before


def test_a_text_size_a_little_smaller_than_the_template_for_fitting_is_left_alone():
    template, output, _ = template_and_output()
    run = next(r for p in output.paragraphs if is_bullet(p._p) and p.text for r in p.runs)
    run.font.size = Pt(9.5)  # the fit step shrinks text to make a page limit

    assert restore_format(template, output) == []
    assert run.font.size == Pt(9.5)


def test_what_the_template_does_on_purpose_is_kept():
    template, output, _ = template_and_output()
    from docx.text.paragraph import Paragraph

    heading = next(p for p in template.paragraphs if p.text == "Projects" or p.style.name.lower().startswith("heading"))
    Paragraph(heading._p, template._body).alignment = 1  # the template centres its headings
    for p in output.element.body.iter(W + "p"):
        if paragraph_text(p) == heading.text:
            Paragraph(p, output._body).alignment = 1

    assert format_differences(template, output) == []


def test_the_badge_paragraph_stays_right_aligned():
    template = template_bytes(header_in_table=True, header_cols=2)
    from app.rmg.resume.badges import clean_picture

    output = Document(io.BytesIO(render_resume(template, RESUME, badges=[(clean_picture(picture()), "A")]).docx))

    cell = output.tables[0].cell(0, 1)
    assert cell.paragraphs[0].alignment == 2  # right
    assert restore_format(Document(io.BytesIO(template)), output) == []
    assert cell.paragraphs[0].alignment == 2


def test_a_render_reports_what_it_fixed_and_the_check_sees_no_difference_afterwards(monkeypatch):
    import app.rmg.resume.render as render

    template = template_bytes()
    original = render.repair_layout

    def damaging(doc):
        original(doc)
        doc.sections[0].right_margin = Inches(0.1)

    monkeypatch.setattr(render, "repair_layout", damaging)
    result = render_resume(template, RESUME)

    assert any("margins" in f for f in result.format_fixes)
    assert format_differences(Document(io.BytesIO(template)), Document(io.BytesIO(result.docx))) == []


def test_pPr_children_stay_in_the_order_word_expects():
    template, output, _ = template_and_output()
    bullet = next(p for p in output.element.body.iter(W + "p") if is_bullet(p) and paragraph_text(p))
    from docx.text.paragraph import Paragraph

    Paragraph(bullet, output._body).alignment = 1
    restore_format(template, output)

    tags = [c.tag.replace(W, "") for c in bullet.find(W + "pPr")]
    from app.rmg.resume.fidelity import _PPR_ORDER as order
    assert tags == sorted(tags, key=lambda t: order.index(t) if t in order else len(order))
    etree.tostring(bullet)  # still well formed

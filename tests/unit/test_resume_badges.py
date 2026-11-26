"""Badges: small pictures in the header of an uploaded resume (certification badges). They are found in the uploaded Word file,
cleaned (the file is untrusted), offered to the associate, and placed in the template's empty header cell on download.
"""
import base64
import io
import zipfile

import pytest
from docx import Document
from docx.shared import Inches
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.rmg.resume import badges as badge_module
from app.rmg.resume.badges import MAX_BADGES, clean_picture, extract_badges, thumbnail_data_url
from app.rmg.resume.model import Item, Origin, Project, Resume, SkillGroup
from app.rmg.resume.render import render_resume
from tests.unit.resume_templates import make_template

WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def picture(side=80, color=(200, 30, 30), fmt="PNG", info=None) -> bytes:
    out = io.BytesIO()
    image = Image.new("RGB", (side, side), color)
    if fmt == "PNG" and info:
        meta = PngInfo()
        for key, value in info.items():
            meta.add_text(key, value)
        image.save(out, "PNG", pnginfo=meta)
    else:
        image.save(out, fmt)
    return out.getvalue()


def docx_with(pictures, *, inches=0.86, labels=None, in_table=True, body_picture=None) -> bytes:
    """A Word file whose first table has two cells; `pictures` go inline into the second (the right-hand cell)."""
    doc = Document()
    doc.add_paragraph("Anil Verma, backend engineer")  # a resume has text; the reader refuses a file with none
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).paragraphs[0].add_run("Anil Verma")
    holder = table.cell(0, 1).paragraphs[0] if in_table else doc.add_paragraph()
    for n, data in enumerate(pictures):
        run = holder.add_run()
        run.add_picture(io.BytesIO(data), width=Inches(inches))
        if labels:
            for props in run._r.iter(f"{{{WP}}}docPr"):
                props.set("descr", labels[n])
    if body_picture:
        doc.add_paragraph().add_run().add_picture(io.BytesIO(body_picture), width=Inches(0.86))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def rewrite(docx: bytes, changes: dict[str, bytes] | None = None, replace_xml: tuple[str, str] | None = None) -> bytes:
    """The same Word file with some parts replaced (to make a damaged, floating or hostile picture)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if changes and item.filename in changes:
                data = changes[item.filename]
            if replace_xml and item.filename == "word/document.xml":
                data = data.decode("utf-8").replace(*replace_xml).encode("utf-8")
            target.writestr(item, data)
    return out.getvalue()


# --- finding the badges ----------------------------------------------------------------------------------------

def test_inline_pictures_in_the_header_table_are_found_in_order_cleaned_and_labelled():
    docx = docx_with([picture(color=(200, 30, 30)), picture(color=(30, 30, 200))], labels=["AWS Certified AI Practitioner", "Databricks GenAI"])

    found = extract_badges(docx)

    assert [b.label for b in found] == ["AWS Certified AI Practitioner", "Databricks GenAI"]
    assert all(Image.open(io.BytesIO(b.png)).format == "PNG" for b in found)
    assert Image.open(io.BytesIO(found[0].png)).convert("RGB").getpixel((5, 5)) == (200, 30, 30)  # the right picture, not another


def test_a_jpeg_is_kept_as_a_png():
    found = extract_badges(docx_with([picture(fmt="JPEG")]))

    assert len(found) == 1 and Image.open(io.BytesIO(found[0].png)).format == "PNG"


def test_pictures_outside_the_header_table_are_not_badges():
    found = extract_badges(docx_with([], body_picture=picture()))

    assert found == []
    assert extract_badges(docx_with([picture()], in_table=False)) == []  # a picture in a body paragraph, not in the table


def test_pictures_that_are_too_small_or_too_large_on_the_page_are_not_badges():
    assert extract_badges(docx_with([picture()], inches=0.1)) == []  # about 10 pixels: a bullet or a spacer
    assert extract_badges(docx_with([picture(300)], inches=3.0)) == []  # about 290 pixels: a banner or a photo


def test_a_floating_picture_such_as_the_banner_or_the_company_logo_is_not_a_badge():
    docx = rewrite(docx_with([picture()]), replace_xml=("wp:inline", "wp:anchor"))

    assert extract_badges(docx) == []


def test_the_same_picture_twice_is_one_badge_and_the_count_is_capped():
    assert len(extract_badges(docx_with([picture(), picture()]))) == 1
    many = [picture(color=(n * 30, 10, 10)) for n in range(MAX_BADGES + 3)]

    assert len(extract_badges(docx_with(many, inches=0.5))) == MAX_BADGES


def test_a_picture_with_a_hostile_label_gets_a_clean_short_one():
    found = extract_badges(docx_with([picture()], labels=["Badge" + chr(10) + chr(9) + "x" * 500]))

    assert "\x00" not in found[0].label and "\n" not in found[0].label and len(found[0].label) <= badge_module.LABEL_CHARS


# --- the file is untrusted -----------------------------------------------------------------------------------

def test_something_that_is_not_a_real_picture_is_skipped_not_passed_on():
    docx = rewrite(docx_with([picture()]), changes={"word/media/image1.png": b"this is not a picture"})

    assert extract_badges(docx) == []
    assert clean_picture(b"GIF89a" + b"x" * 50) is None  # not a PNG or a JPEG
    assert clean_picture(b"") is None


def test_a_picture_with_too_many_pixels_is_refused_before_it_is_decoded(monkeypatch):
    monkeypatch.setattr(badge_module, "MAX_PIXELS", 100)

    assert clean_picture(picture(20)) is None  # 400 pixels
    assert clean_picture(picture(10)) is not None  # 100 pixels


def test_a_picture_stored_larger_than_the_limit_is_skipped(monkeypatch):
    monkeypatch.setattr(badge_module, "MAX_SOURCE_BYTES", 100)

    assert extract_badges(docx_with([picture()])) == []


def test_the_stored_picture_is_bounded_and_has_no_hidden_data():
    big = picture(1200, info={"Comment": "secret note", "Author": "someone"})

    cleaned = Image.open(io.BytesIO(clean_picture(big)))

    assert max(cleaned.size) <= badge_module.STORE_SIDE
    assert "Comment" not in cleaned.info and "Author" not in cleaned.info


def test_a_file_that_cannot_be_read_has_no_badges_and_never_raises():
    assert extract_badges(b"not a zip at all") == []
    assert extract_badges(b"") == []
    assert extract_badges(rewrite(docx_with([picture()]), changes={"word/document.xml": b"<broken"})) == []


def test_a_relationship_that_points_outside_the_media_folder_is_ignored():
    docx = docx_with([picture()])
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    hostile = rels.replace("media/image1.png", "../docProps/core.xml")

    assert extract_badges(rewrite(docx, changes={"word/_rels/document.xml.rels": hostile.encode("utf-8")})) == []


def test_the_thumbnail_is_a_small_data_address_or_nothing():
    url = thumbnail_data_url(clean_picture(picture(300)))

    assert url.startswith("data:image/png;base64,")
    assert max(Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size) <= badge_module.THUMB_SIDE
    assert thumbnail_data_url(b"nope") is None


# --- placing them in the template ------------------------------------------------------------------------------

def orig(text, n=0):
    return Item(text=text, origin=Origin.ORIGINAL, source=f"s.{n}")


RESUME = Resume(
    name="Anil Verma", role_title=orig("Backend Engineer"), summary=orig("Builds payment systems."),
    skill_groups=[SkillGroup(category="Backend", items=[orig("Java")])],
    highlights=[orig(f"Highlight {i}") for i in range(3)],
    projects=[Project(name="Payments", description=orig("About it."), bullets=[orig("One"), orig("Two")])])


def render_with(badges, **template_options):
    doc = make_template(header_in_table=True, **template_options)
    out = io.BytesIO()
    doc.save(out)
    result = render_resume(out.getvalue(), RESUME, badges=badges)
    return Document(io.BytesIO(result.docx)), result


def pictures_in(cell) -> list:
    return list(cell._tc.iter(f"{{{WP}}}inline"))


def test_badges_are_placed_in_the_empty_header_cell_right_aligned_with_their_labels():
    png = clean_picture(picture())

    doc, result = render_with([(png, "AWS Certified AI Practitioner"), (png, "Databricks GenAI")], header_cols=2)

    cell = doc.tables[0].cell(0, 1)
    found = pictures_in(cell)
    assert len(found) == 2 and [p.find(f"{{{WP}}}docPr").get("descr") for p in found] == ["AWS Certified AI Practitioner", "Databricks GenAI"]
    assert cell.paragraphs[0].alignment == 2  # right
    assert not [p for p in result.problems if p.startswith("badges")]
    assert "Anil Verma" in doc.tables[0].cell(0, 0).text  # the name is still where it was


def test_badges_are_sized_to_fit_the_cell_even_when_there_are_many():
    png = clean_picture(picture())

    doc, _ = render_with([(png, None)] * 6, header_cols=2)

    widths = [int(p.find(f"{{{WP}}}extent").get("cx")) / 914400 for p in pictures_in(doc.tables[0].cell(0, 1))]
    assert len(widths) == 6 and all(0.4 <= w <= 0.86 for w in widths) and sum(widths) < 3.5


def test_no_badges_means_nothing_is_added():
    doc, result = render_with([], header_cols=2)

    assert pictures_in(doc.tables[0].cell(0, 1)) == [] and not [p for p in result.problems if p.startswith("badges")]


def test_a_template_with_no_empty_header_cell_says_so_instead_of_losing_the_pictures_silently():
    png = clean_picture(picture())

    doc, result = render_with([(png, "AWS")], header_cols=1)

    assert any(p.startswith("badges: the template has no empty cell") for p in result.problems)
    assert sum(len(pictures_in(c)) for t in doc.tables for row in t.rows for c in row.cells) == 0


def test_a_header_cell_that_already_has_text_is_not_used():
    png = clean_picture(picture())
    template = make_template(header_in_table=True, header_cols=2)
    template.tables[0].cell(0, 1).paragraphs[0].add_run("Already something here")
    out = io.BytesIO()
    template.save(out)

    result = render_resume(out.getvalue(), RESUME, badges=[(png, "AWS")])

    assert any(p.startswith("badges: the template has no empty cell") for p in result.problems)


@pytest.mark.parametrize("spaces", ["      ", ""])
def test_leading_spaces_in_the_empty_cell_do_not_push_the_pictures_aside(spaces):
    png = clean_picture(picture())
    template = make_template(header_in_table=True, header_cols=2)
    template.tables[0].cell(0, 1).paragraphs[0].add_run(spaces)
    out = io.BytesIO()
    template.save(out)

    result = render_resume(out.getvalue(), RESUME, badges=[(png, "AWS")])

    cell = Document(io.BytesIO(result.docx)).tables[0].cell(0, 1)
    assert len(pictures_in(cell)) == 1 and "".join(t.text or "" for t in cell._tc.iter(W + "t")).strip() == ""


# --- where they go: side by side, fitted to the cell, and under the logo -------------------------------------------

def build_template(*, grid_inches=None, top_margin=None, logo=None, behind=False):
    """A template with a two-cell header. `grid_inches` sets the right column's width; `logo` is (offset, height) in inches of a
    picture floating on the page, placed in front of the text (or behind it if `behind`)."""
    doc = make_template(header_in_table=True, header_cols=2)
    if grid_inches is not None:
        doc.tables[0].columns[1].width = Inches(grid_inches)
    if top_margin is not None:
        doc.sections[0].top_margin = Inches(top_margin)
    if logo is not None:
        from lxml import etree

        offset, height = logo
        xml = (f'<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:wp="{WP}"><w:r><w:drawing>'
               f'<wp:anchor behindDoc="{1 if behind else 0}"><wp:positionH relativeFrom="page"><wp:posOffset>6107000</wp:posOffset></wp:positionH>'
               f'<wp:positionV relativeFrom="page"><wp:posOffset>{int(offset * 914400)}</wp:posOffset></wp:positionV>'
               f'<wp:extent cx="1197864" cy="{int(height * 914400)}"/></wp:anchor></w:drawing></w:r></w:p>')
        doc.element.body.insert(0, etree.fromstring(xml))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def rendered_cell(template: bytes, badges):
    result = render_resume(template, RESUME, badges=badges)
    return Document(io.BytesIO(result.docx)).tables[0].cell(0, 1)


def test_badges_sit_side_by_side_with_no_text_between_them_and_zero_picture_margins():
    png = clean_picture(picture())

    cell = rendered_cell(build_template(), [(png, "A"), (png, "B"), (png, "C")])

    paragraph = cell._tc.find(W + "p")
    runs = paragraph.findall(W + "r")
    drawings = [r for r in runs if r.find(W + "drawing") is not None]
    assert len(drawings) == 3
    assert not [r for r in runs if r.find(W + "drawing") is None and "".join(t.text or "" for t in r.iter(W + "t")).strip(" ")]  # nothing typed between
    assert not [r for r in runs if r.find(W + "drawing") is None and "".join(t.text or "" for t in r.iter(W + "t"))]  # not even spaces: they are wide in this template
    for inline in cell._tc.iter(f"{{{WP}}}inline"):
        assert [inline.get(side) for side in ("distT", "distB", "distL", "distR")] == ["0", "0", "0", "0"]  # without these LibreOffice adds 0.125 inch each side


def test_the_picture_size_comes_from_the_columns_width_in_the_tables_grid():
    png = clean_picture(picture())

    narrow = rendered_cell(build_template(grid_inches=2.56), [(png, None)] * 3)  # the company template's right column
    wide = rendered_cell(build_template(grid_inches=4.0), [(png, None)] * 3)

    def widths(cell):
        return [int(i.find(f"{{{WP}}}extent").get("cx")) / 914400 for i in cell._tc.iter(f"{{{WP}}}inline")]

    assert all(w < 0.68 for w in widths(narrow)) and sum(widths(narrow)) <= (2.56 - 0.14) * 0.8 + 0.01  # fits with room to spare
    assert all(abs(w - 0.68) < 0.01 for w in widths(wide))  # a wide cell gets the full size


def test_badges_start_below_the_company_logo_when_one_floats_in_front_of_the_header():
    png = clean_picture(picture())
    template = build_template(top_margin=0.4, logo=(0.43, 0.49))  # the logo reaches 0.92 inch down the page

    cell = rendered_cell(template, [(png, "A")])

    before = Document(io.BytesIO(render_resume(template, RESUME, badges=[(png, "A")]).docx)).tables[0].cell(0, 1).paragraphs[0].paragraph_format.space_before
    assert before is not None and 22 <= before.pt <= 30  # about 0.36 inch, so the first badge starts at about 1.0 inch
    assert len(pictures_in(cell)) == 1


def test_no_space_is_added_when_there_is_no_logo_or_it_floats_behind_the_text_or_is_above_the_cell():
    png = clean_picture(picture())

    for template in (build_template(top_margin=0.4), build_template(top_margin=0.4, logo=(0.43, 0.49), behind=True),
                     build_template(top_margin=2.0, logo=(0.43, 0.49))):
        paragraph = rendered_cell(template, [(png, "A")]).paragraphs[0]
        assert paragraph.paragraph_format.space_before in (None, 0) or paragraph.paragraph_format.space_before.pt == 0

"""Put the badge pictures RMG chose into the header of the finished Word resume.

The template's header is a table: the name on the left and an EMPTY cell on the right. The pictures go in that cell,
right-aligned, side by side, under the company logo. Do this on the finished file, after the text is filled in.

Usage:
  python place_badges.py <finished.docx> <output.docx> <badge1.png> [<badge2.png> ...]
Pass only the pictures RMG chose to keep. Prints what it did. If the header has no empty cell on the right it changes nothing
and says so (then tell RMG the pictures were not included).
Needs python-docx.

Two details that matter, because Word and LibreOffice draw inline pictures differently:
- every picture gets distT/distB/distL/distR = 0, otherwise LibreOffice adds about 0.125 inch on each side and wraps the row;
- no spaces are typed between pictures (they are wide in this template), so the pictures touch. That is intended.
"""
import io
import sys

BADGE_INCHES = 0.68  # tall enough to read, small enough not to make the banner row grow
BADGE_FLOOR_INCHES = 0.4
BADGE_ROOM = 0.8  # use at most this share of the cell width, so the row never wraps
LOGO_GAP_INCHES = 0.08
FIRST_LINE_INCHES = 0.17  # the template's first (empty) paragraph, above the header table
EMU_PER_INCH = 914400
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"


def text_of(element) -> str:
    return "".join(t.text or "" for t in element.iter(W + "t")).strip()


def find_cell(doc):
    """The empty last cell of the header table's first row (with text in an earlier cell), or None."""
    if not doc.tables:
        return None
    row = doc.tables[0]._tbl.find(W + "tr")
    cells = row.findall(W + "tc") if row is not None else []
    if len(cells) < 2 or text_of(cells[-1]) or not any(text_of(c) for c in cells[:-1]):
        return None
    return cells[-1]


def margins(cell) -> tuple[float, float]:
    """(left + right, top) cell margins in inches."""
    def one(side: str, default: int) -> float:
        node = cell.find(f"{W}tcPr/{W}tcMar/{W}{side}")
        try:
            return int(node.get(W + "w")) / 1440 if node is not None else default / 1440
        except (TypeError, ValueError):
            return default / 1440

    return one("left", 115) + one("right", 115), one("top", 100)


def cell_inches(cell) -> float:
    """The cell's width from the table's column grid; 3 inches if unknown."""
    row = cell.getparent()
    grid = row.getparent().find(W + "tblGrid")
    try:
        position = row.findall(W + "tc").index(cell)
        return int(grid.findall(W + "gridCol")[position].get(W + "w")) / 1440
    except (AttributeError, TypeError, ValueError, IndexError):
        return 3.0


def logo_bottom_inches(doc):
    """How far down the page the lowest picture floating in front of the text reaches (the company logo), or None."""
    bottom = None
    for anchor in doc.element.body.iter(f"{{{WP_NS}}}anchor"):
        if anchor.get("behindDoc") == "1":  # the banner background floats behind the text
            continue
        top = anchor.find(f"{{{WP_NS}}}positionV")
        offset = top.find(f"{{{WP_NS}}}posOffset") if top is not None else None
        extent = anchor.find(f"{{{WP_NS}}}extent")
        if top is None or top.get("relativeFrom") != "page" or offset is None or extent is None:
            continue
        try:
            end = (int(offset.text) + int(extent.get("cy"))) / EMU_PER_INCH
        except (TypeError, ValueError):
            continue
        bottom = end if bottom is None else max(bottom, end)
    return bottom


def space_below_logo_points(doc, cell) -> float:
    bottom = logo_bottom_inches(doc)
    if bottom is None or not doc.sections:
        return 0.0
    content_top = doc.sections[0].top_margin / EMU_PER_INCH + FIRST_LINE_INCHES + margins(cell)[1]
    return round(min(72.0, max(0.0, (bottom + LOGO_GAP_INCHES - content_top) * 72)), 1)


def place(source: str, target: str, pictures: list[str]) -> str:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt
    from docx.text.paragraph import Paragraph

    doc = Document(source)
    cell = find_cell(doc)
    if cell is None:
        return "not placed: the header has no empty cell on the right for the pictures"
    paragraph_element = cell.find(W + "p")
    if paragraph_element is None:
        return "not placed: the empty header cell has no paragraph"
    for t in paragraph_element.iter(W + "t"):  # leading spaces would push right-aligned pictures off the edge
        t.text = ""
    paragraph = Paragraph(paragraph_element, doc._body)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    before = space_below_logo_points(doc, cell)
    if before:
        paragraph.paragraph_format.space_before = Pt(before)
    available = cell_inches(cell) - margins(cell)[0] - 0.04
    width = max(BADGE_FLOOR_INCHES, min(BADGE_INCHES, available * BADGE_ROOM / len(pictures)))
    for path in pictures:
        run = paragraph.add_run()
        with open(path, "rb") as handle:
            run.add_picture(io.BytesIO(handle.read()), width=Inches(width))
        for inline in run._r.iter(f"{{{WP_NS}}}inline"):
            for side in ("distT", "distB", "distL", "distR"):
                inline.set(side, "0")
    doc.save(target)
    return f"placed {len(pictures)} picture(s), {width:.2f} inch wide each, in the header's right cell"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 3:
        print("Usage: python place_badges.py <finished.docx> <output.docx> <badge1.png> [...]", file=sys.stderr)
        return 2
    print(place(args[0], args[1], args[2:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

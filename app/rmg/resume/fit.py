"""Keep the layout from spilling: the side column onto a second page, and a few stray lines onto a last page.

Word is not available here, so heights are estimated from text length, font size, line spacing and page size. Two uses:
  fit()               the side column (skills and education) is compared with what the template's own sample text took
  compact_document()  the whole document: if a few lines spill onto an almost empty last page, or it is too long, the
                      spacing is tightened in steps (line spacing first, then the font a little)
Nothing is ever dropped, and text is never made bigger.
"""
import math
from dataclasses import dataclass

from app.rmg.resume.template import W

DEFAULT_PT = 10.0
CHARS_ACROSS_AT_10PT = 32  # how many characters fit across the side column at 10pt (measured on the real template)
HEADROOM = 1.1  # the template's sample does not fill the column, so the new text may take a little more than it
PAGE_SHARE = 0.55  # a column may always use at least this share of the usable page height
LEVELS = ((1.0, 0.0), (0.85, 0.0), (0.77, 1.0), (0.7, 2.0))  # (line spacing scale, points to take off the font)
MIN_PT = 9.0
MAX_PAGES = 10  # the limit RMG asked for on resumes
LAST_PAGE_MIN_FILL = 0.25  # a last page less full than this looks like a mistake
LAST_PAGE_MAX_FILL = 0.88  # a last page fuller than this may really spill by a line or two, so it is given room
ROOMY_FILL = 0.8
AVERAGE_CHAR_EM = 0.5   # an average character is about this wide, in ems
CELL_PADDING_PT = 10.8  # Word's default: 5.4pt of padding on each side of a table cell
SAFETY = 0.95  # the estimate is not exact, so a page is treated as this full when it is deciding whether text fits


class Styles:
    """What a paragraph's style says about its font size and spacing, following "based on" and the document defaults.
    Without this a template that sets its spacing in styles (most do) would be measured as if it had none."""

    def __init__(self, doc):
        root = doc.styles.element
        self._by_id = {s.get(W + "styleId"): s for s in root.findall(W + "style")}
        defaults = root.find(W + "docDefaults")
        self._default_spacing = self._attrs(defaults.find(f"{W}pPrDefault/{W}pPr/{W}spacing")) if defaults is not None else {}
        size = defaults.find(f"{W}rPrDefault/{W}rPr/{W}sz") if defaults is not None else None
        self._default_pt = _half_points(size) or DEFAULT_PT
        self._normal = next((s for s in self._by_id.values() if s.get(W + "type") == "paragraph" and s.get(W + "default") in ("1", "true")), None)

    @staticmethod
    def _attrs(spacing) -> dict:
        return {k.split("}")[1]: v for k, v in spacing.attrib.items()} if spacing is not None else {}

    def _chain(self, p):
        ref = p.find(f"{W}pPr/{W}pStyle")
        style = self._by_id.get(ref.get(W + "val")) if ref is not None else self._normal
        seen = 0
        while style is not None and seen < 10:
            yield style
            based = style.find(W + "basedOn")
            style = self._by_id.get(based.get(W + "val")) if based is not None else None
            seen += 1

    def spacing(self, p) -> dict:
        merged = dict(self._default_spacing)
        for style in reversed(list(self._chain(p))):
            merged.update(self._attrs(style.find(f"{W}pPr/{W}spacing")))
        merged.update(self._attrs(_spacing(p)))
        return merged

    def size(self, p) -> float:
        for style in self._chain(p):
            found = _half_points(style.find(f"{W}rPr/{W}sz"))
            if found:
                return found
        return self._default_pt


def _half_points(size) -> float | None:
    try:
        return int(size.get(W + "val")) / 2 if size is not None else None
    except (TypeError, ValueError):
        return None


def _font_pt(p, styles: "Styles | None" = None) -> float:
    for size in p.iter(W + "sz"):
        found = _half_points(size)
        if found:
            return found
    return styles.size(p) if styles is not None else DEFAULT_PT


def _spacing(p):
    return p.find(f"{W}pPr/{W}spacing")


def _number(spacing, name: str) -> float:
    try:
        return float(spacing.get(W + name)) if spacing is not None and spacing.get(W + name) is not None else 0.0
    except ValueError:
        return 0.0


def _text(p) -> str:
    return "".join(t.text or "" for t in p.iter(W + "t"))


def _smaller(pt: float, drop: float) -> float:
    """The font size after taking `drop` points off, but never below the minimum and never bigger than it was."""
    return min(pt, max(pt - drop, MIN_PT)) if drop else pt


def _parts(p, scale: float, drop: float, width: float | None = None, styles: "Styles | None" = None) -> tuple[float, float, float]:
    """(space before, the lines themselves, space after) in points."""
    pt = _smaller(_font_pt(p, styles), drop)
    chars = max(width / (pt * AVERAGE_CHAR_EM), 1) if width else max(CHARS_ACROSS_AT_10PT * 10 / pt, 1)
    lines = max(1, math.ceil(len(_text(p)) / chars))
    spacing = styles.spacing(p) if styles is not None else Styles._attrs(_spacing(p))
    line = _value(spacing, "line")
    pitch = line / 20 if (line and spacing.get("lineRule") == "exact") else pt * 1.2 * ((line or 240) / 240)
    return _value(spacing, "before") / 20 * scale, lines * pitch * scale, _value(spacing, "after") / 20 * scale


def _height(p, scale: float, drop: float, width: float | None = None, styles: "Styles | None" = None) -> float:
    return sum(_parts(p, scale, drop, width, styles))


def _value(spacing: dict, name: str) -> float:
    try:
        return float(spacing.get(name, 0) or 0)
    except ValueError:
        return 0.0


def estimate(paragraphs, level: int = 0, styles: "Styles | None" = None) -> float:
    scale, drop = LEVELS[level]
    return sum(_height(p, scale, drop, None, styles) for p in paragraphs)


def capacity(sample: list, doc) -> float:
    """How tall the column may be: what the template's sample text took, a little more, and never less than a share of the page."""
    try:
        section = doc.sections[0]
        usable = (section.page_height - section.top_margin - section.bottom_margin) / 12700
    except Exception:
        usable = 700.0
    return max(estimate(sample, 0, Styles(doc)) * HEADROOM, usable * PAGE_SHARE) * SAFETY


def _tighten(p, scale: float, drop: float) -> None:
    ppr = p.find(W + "pPr")
    if ppr is None:
        ppr = p.makeelement(W + "pPr")
        p.insert(0, ppr)
    spacing = _spacing(p)
    if spacing is None:
        spacing = ppr.makeelement(W + "spacing")
        insert_spacing(ppr, spacing)
    rule = spacing.get(W + "lineRule")
    line = _number(spacing, "line") or 240.0
    spacing.set(W + "line", str(round(line * scale)))
    if rule is None:
        spacing.set(W + "lineRule", "auto")
    for name in ("before", "after"):
        if spacing.get(W + name) is not None:
            spacing.set(W + name, str(round(_number(spacing, name) * scale)))
    if drop:
        for size in p.iter(W + "sz", W + "szCs"):
            try:
                half = int(size.get(W + "val"))
            except (TypeError, ValueError):
                continue
            size.set(W + "val", str(round(_smaller(half / 2, drop) * 2)))


_AFTER_SPACING = ("ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
                  "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")


def insert_spacing(ppr, spacing) -> None:
    """w:spacing has a fixed place inside w:pPr (Word rejects the file otherwise): before indentation, alignment and the rest."""
    for index, child in enumerate(ppr):
        if child.tag.split("}")[-1] in _AFTER_SPACING:
            ppr.insert(index, spacing)
            return
    ppr.append(spacing)


def fit(new: list, limit: float, doc) -> bool:
    """Tighten `new` paragraphs until their estimated height is within `limit`. Returns False if even the tightest is too tall."""
    styles = Styles(doc)
    for level in range(len(LEVELS)):
        if estimate(new, level, styles) <= limit or level == len(LEVELS) - 1:
            scale, drop = LEVELS[level]
            if level:
                for p in new:
                    _tighten(p, scale, drop)
            return estimate(new, level, styles) <= limit
    return True


# --- the whole document ------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PageEstimate:
    pages: int
    last_fill: float  # how full the last page is, 0 to 1
    forced_start: bool = False  # the last page begins at a deliberate page break (so a short page is by design)


def _geometry(doc) -> tuple[float, float]:
    """(usable width, usable height) in points."""
    try:
        s = doc.sections[0]
        return ((s.page_width - s.left_margin - s.right_margin) / 12700,
                (s.page_height - s.top_margin - s.bottom_margin) / 12700)
    except Exception:
        return 468.0, 648.0


def _indent(p) -> float:
    ind = p.find(f"{W}pPr/{W}ind")
    return _number(ind, "left") / 20 if ind is not None else 0.0


def _parts_of(p, width: float, level: int, styles) -> tuple[float, float, float]:
    scale, drop = LEVELS[level]
    return _parts(p, scale, drop, max(width - _indent(p), 40.0), styles)


def _stack(paragraphs, width: float, level: int, styles) -> float:
    """Height of paragraphs one under another. Between two of them Word leaves the larger of the first one's space
    after and the second one's space before, not both added together."""
    total, previous_after = 0.0, None
    for p in paragraphs:
        before, content, after = _parts_of(p, width, level, styles)
        total += content + after + (before if previous_after is None else max(before - previous_after, 0.0))
        previous_after = after
    return total


def _table_height(table, width: float, level: int, styles) -> float:
    total = 0.0
    for row in table.findall(W + "tr"):
        cells = row.findall(W + "tc")
        minimum = 0.0
        height = row.find(f"{W}trPr/{W}trHeight")
        if height is not None:
            minimum = _number(height, "val") / 20
        tallest = 0.0
        for cell in cells:
            cell_width = _number(cell.find(f"{W}tcPr/{W}tcW"), "w") / 20 or width / max(len(cells), 1)
            inner = _stack(cell.findall(W + "p"), cell_width - CELL_PADDING_PT, level, styles)
            tallest = max(tallest, inner)
        total += max(minimum, tallest)
    return total


def estimate_pages(doc, level: int = 0) -> PageEstimate:
    width, capacity_pt = _geometry(doc)
    capacity_pt *= SAFETY
    styles = Styles(doc)
    pages, y, previous_after, forced = 1, 0.0, None, False

    def add(height: float) -> None:
        nonlocal pages, y, forced
        y += height
        while y > capacity_pt:
            pages += 1
            y -= capacity_pt
            forced = False

    for child in doc.element.body:
        if child.tag == W + "p":
            before = child.find(f"{W}pPr/{W}pageBreakBefore")
            if before is not None and before.get(W + "val") not in ("0", "false") and y > 0:
                pages, y, previous_after, forced = pages + 1, 0.0, None, True
            space_before, content, space_after = _parts_of(child, width, level, styles)
            add(content + space_after + (space_before if previous_after is None else max(space_before - previous_after, 0.0)))
            previous_after = space_after
        elif child.tag == W + "tbl":
            add(_table_height(child, width, level, styles))
            previous_after = None
    return PageEstimate(pages=pages, last_fill=y / capacity_pt, forced_start=forced)


def compact_document(doc) -> PageEstimate:
    """Tighten the spacing of the whole document if that saves a page worth saving. Returns the estimate afterwards."""
    base = estimate_pages(doc)
    too_long = base.pages > MAX_PAGES
    stray_last_page = base.pages > 1 and base.last_fill < LAST_PAGE_MIN_FILL
    nearly_full = base.last_fill > LAST_PAGE_MAX_FILL
    if not (too_long or stray_last_page or nearly_full):
        return base
    options = [(level, estimate_pages(doc, level)) for level in range(1, len(LEVELS))]
    if too_long:
        chosen = next((o for o in options if o[1].pages <= MAX_PAGES), min(options, key=lambda o: o[1].pages))
    elif stray_last_page:
        chosen = next((o for o in options if o[1].pages < base.pages), None)
    else:  # fewer pages, or the same number with room to spare on the last one
        chosen = next((o for o in options if o[1].pages < base.pages or o[1].last_fill <= ROOMY_FILL), None)
    if chosen is None or (chosen[1].pages >= base.pages and not nearly_full):
        return base
    scale, drop = LEVELS[chosen[0]]
    for p in doc.element.body.iter(W + "p"):
        _tighten(p, scale, drop)
    return chosen[1]


# --- a banner that keeps its size ---------------------------------------------------------------------------------------

def height_of(p, doc, level: int = 0) -> float:
    """Estimated height in points of one paragraph, at the width of the table cell or page it sits in."""
    width, _ = _geometry(doc)
    parent = p.getparent()
    if parent is not None and parent.tag == W + "tc":
        row = parent.getparent()
        cells = row.findall(W + "tc") if row is not None else [parent]
        width = (_number(parent.find(f"{W}tcPr/{W}tcW"), "w") / 20 or width / max(len(cells), 1)) - CELL_PADDING_PT
    return _stack([p], width, level, Styles(doc))


def keep_row_height(p, points: float) -> bool:
    """Make the table row holding paragraph `p` at least `points` tall. Returns False if `p` is not in a table row."""
    cell = p.getparent()
    row = cell.getparent() if cell is not None and cell.tag == W + "tc" else None
    if row is None or row.tag != W + "tr":
        return False
    properties = row.find(W + "trPr")
    if properties is None:
        properties = row.makeelement(W + "trPr", {})
        row.insert(1 if row.find(W + "tblPrEx") is not None else 0, properties)
    height = properties.find(W + "trHeight")
    if height is None:
        height = properties.makeelement(W + "trHeight", {})
        properties.append(height)
    height.set(W + "val", str(max(round(points * 20), round(_number(height, "val")))))
    height.set(W + "hRule", "atLeast")
    return True

"""Keep the side column (skills and education) on the first page.

Word is not available here, so the height of the new text is estimated from its length, font size and line spacing, and
compared with what the template's own sample text took up. If it is too tall, the new paragraphs are tightened in steps:
first the line spacing, then the font a little. Only the new paragraphs change, never the template's, and nothing is dropped.
"""
import math

from app.rmg.resume.template import W

DEFAULT_PT = 10.0
CHARS_ACROSS_AT_10PT = 32  # how many characters fit across the side column at 10pt (measured on the real template)
HEADROOM = 1.1  # the template's sample does not fill the column, so the new text may take a little more than it
PAGE_SHARE = 0.55  # a column may always use at least this share of the usable page height
LEVELS = ((1.0, 0.0), (0.85, 0.0), (0.77, 1.0), (0.7, 2.0))  # (line spacing scale, points to take off the font)
MIN_PT = 9.0


def _font_pt(p) -> float:
    for size in p.iter(W + "sz"):
        try:
            return int(size.get(W + "val")) / 2
        except (TypeError, ValueError):
            continue
    return DEFAULT_PT


def _spacing(p):
    return p.find(f"{W}pPr/{W}spacing")


def _number(spacing, name: str) -> float:
    try:
        return float(spacing.get(W + name)) if spacing is not None and spacing.get(W + name) is not None else 0.0
    except ValueError:
        return 0.0


def _text(p) -> str:
    return "".join(t.text or "" for t in p.iter(W + "t"))


def _height(p, scale: float, drop: float) -> float:
    pt = max(_font_pt(p) - drop, MIN_PT) if drop else _font_pt(p)
    chars = max(CHARS_ACROSS_AT_10PT * 10 / pt, 1)
    lines = max(1, math.ceil(len(_text(p)) / chars))
    spacing = _spacing(p)
    line = _number(spacing, "line")
    rule = spacing.get(W + "lineRule") if spacing is not None else None
    pitch = line / 20 if (line and rule == "exact") else pt * 1.2 * ((line or 240) / 240)
    return lines * pitch * scale + (_number(spacing, "before") + _number(spacing, "after")) / 20 * scale


def estimate(paragraphs, level: int = 0) -> float:
    scale, drop = LEVELS[level]
    return sum(_height(p, scale, drop) for p in paragraphs)


def capacity(sample: list, doc) -> float:
    """How tall the column may be: what the template's sample text took, a little more, and never less than a share of the page."""
    try:
        section = doc.sections[0]
        usable = (section.page_height - section.top_margin - section.bottom_margin) / 12700
    except Exception:
        usable = 700.0
    return max(estimate(sample) * HEADROOM, usable * PAGE_SHARE)


def _tighten(p, scale: float, drop: float) -> None:
    ppr = p.find(W + "pPr")
    if ppr is None:
        ppr = p.makeelement(W + "pPr")
        p.insert(0, ppr)
    spacing = _spacing(p)
    if spacing is None:
        spacing = ppr.makeelement(W + "spacing")
        _insert_spacing(ppr, spacing)
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
            size.set(W + "val", str(max(half - round(drop * 2), round(MIN_PT * 2))))


_AFTER_SPACING = ("ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
                  "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")


def _insert_spacing(ppr, spacing) -> None:
    """w:spacing has a fixed place inside w:pPr (Word rejects the file otherwise): before indentation, alignment and the rest."""
    for index, child in enumerate(ppr):
        if child.tag.split("}")[-1] in _AFTER_SPACING:
            ppr.insert(index, spacing)
            return
    ppr.append(spacing)


def fit(new: list, limit: float) -> bool:
    """Tighten `new` paragraphs until their estimated height is within `limit`. Returns False if even the tightest is too tall."""
    for level in range(len(LEVELS)):
        if estimate(new, level) <= limit or level == len(LEVELS) - 1:
            scale, drop = LEVELS[level]
            if level:
                for p in new:
                    _tighten(p, scale, drop)
            return estimate(new, level) <= limit
    return True

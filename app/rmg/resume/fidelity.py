"""Keep the finished resume's format the same as the template's: page setup, alignment, indents, fonts and sizes.

The resume is poured into a copy of the company template, so it normally keeps the template's look. This is the safety net for
when it does not: a template whose own paragraphs are inconsistent, text carried in with its own fonts or alignment, or a step
that changed the page setup. It compares the finished file with the template and puts the template's settings back.

What it checks and restores (nothing in the resume's words is ever changed):
  page setup   page size, orientation, margins and columns of every section: copied back from the template
  alignment    left, centre, right or justified, per kind of paragraph (heading, bullet, text): the template's own choice
  indents      left, right, hanging and first-line indent of those paragraphs
  fonts        a font the template does not use is dropped from a run, so the template's font shows through
  sizes        a size far outside the template's range is dropped the same way (the fit step may shrink text a little: that stays)

Kinds are told apart in the same way for the template and the file, and a paragraph is only changed when the template has no
paragraph of the same kind and place (inside a table or not) formatted like it, so a template's deliberate variety is kept.
"""
from collections import Counter
from copy import deepcopy

from app.rmg.resume.template import W, is_blank, is_bullet, is_heading

TOLERANCE = 30  # twips (1/20 point) of difference in an indent that is not worth fixing
MIN_ALLOWED_HALF_POINTS = 18  # the fit step may shrink text, but never below 9 pt
PAGE_PARTS = ("pgSz", "pgMar", "cols")


def _sections(doc) -> list:
    return list(doc.element.body.iter(W + "sectPr"))


def _page_signature(sect) -> dict[str, dict[str, str]]:
    signature = {}
    for part in PAGE_PARTS:
        node = sect.find(W + part)
        signature[part] = {k.replace(W, ""): v for k, v in node.attrib.items()} if node is not None else {}
    return signature


def _kind(p) -> str:
    return "heading" if is_heading(p) else "bullet" if is_bullet(p) else "text"


def _in_table(p) -> bool:
    return any(True for _ in p.iterancestors(W + "tc"))


def _twips(node, *names: str) -> int | None:
    for name in names:
        value = node.get(W + name) if node is not None else None
        if value is not None and value.lstrip("-").isdigit():
            return int(value)
    return None


def _look(p) -> tuple:
    """How a paragraph is aligned and indented: (alignment, left, right, hanging, first line)."""
    properties = p.find(W + "pPr")
    jc = properties.find(W + "jc") if properties is not None else None
    ind = properties.find(W + "ind") if properties is not None else None
    align = {"start": "left", "end": "right", "both": "justify"}.get(jc.get(W + "val"), jc.get(W + "val")) if jc is not None else None
    return (align or "left", _twips(ind, "left", "start") or 0, _twips(ind, "right", "end") or 0, _twips(ind, "hanging") or 0,
            _twips(ind, "firstLine") or 0)


def _same_look(a: tuple, b: tuple) -> bool:
    return a[0] == b[0] and all(abs(x - y) <= TOLERANCE for x, y in zip(a[1:], b[1:], strict=True))


def _real(doc) -> list:
    """Paragraphs that carry words, in the body. Blank spacer paragraphs are not judged, and neither are paragraphs holding a
    picture (the badges are right-aligned on purpose)."""
    return [p for p in doc.element.body.iter(W + "p") if not is_blank(p) and p.find(f".//{W}drawing") is None]


def _template_looks(tdoc) -> dict[tuple[str, bool], list[tuple]]:
    """For each (kind, in a table) the looks the template uses, most common first."""
    counts: dict[tuple[str, bool], Counter] = {}
    for p in _real(tdoc):
        counts.setdefault((_kind(p), _in_table(p)), Counter())[_look(p)] += 1
    return {key: [look for look, _ in counter.most_common()] for key, counter in counts.items()}


def _fonts_and_sizes(doc) -> tuple[set[str], set[int]]:
    """The fonts and sizes a document uses: written on its runs, or set by its styles and defaults."""
    fonts, sizes = set(), set()
    run_properties = [r for r in doc.element.body.iter(W + "rPr") if r.getparent() is not None and r.getparent().tag == W + "r"]
    for rpr in [*run_properties, *doc.styles.element.iter(W + "rPr")]:
        font = rpr.find(W + "rFonts")
        if font is not None and font.get(W + "ascii"):
            fonts.add(font.get(W + "ascii"))
        size = rpr.find(W + "sz")
        if size is not None and (size.get(W + "val") or "").isdigit():
            sizes.add(int(size.get(W + "val")))
    return fonts, sizes


def _allowed_sizes(sizes: set[int]) -> tuple[int, int] | None:
    return (min(min(sizes), MIN_ALLOWED_HALF_POINTS), max(sizes)) if sizes else None


def _apply_look(p, look: tuple) -> None:
    """Set a paragraph's alignment and indents to `look`, leaving every other setting (spacing, numbering, keep-with-next) alone."""
    from lxml import etree

    properties = p.find(W + "pPr")
    if properties is None:
        properties = etree.SubElement(p, W + "pPr")
        p.insert(0, properties)
    for tag in ("jc", "ind"):
        for node in properties.findall(W + tag):
            properties.remove(node)
    align, left, right, hanging, first = look
    if left or right or hanging or first:
        ind = etree.SubElement(properties, W + "ind")
        for name, value in (("left", left), ("right", right), ("hanging", hanging), ("firstLine", first)):
            if value:
                ind.set(W + name, str(value))
    if align != "left":
        etree.SubElement(properties, W + "jc").set(W + "val", {"justify": "both"}.get(align, align))
    _order_properties(properties)


_PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr", "suppressLineNumbers", "pBdr",
              "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE",
              "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
              "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId", "cnfStyle",
              "rPr", "sectPr", "pPrChange"]


def _order_properties(properties) -> None:
    """Word is strict about the order of paragraph properties; put ours where the file format wants them."""
    rank = {W + name: n for n, name in enumerate(_PPR_ORDER)}
    children = sorted(properties, key=lambda c: rank.get(c.tag, len(rank)))
    for child in children:
        properties.remove(child)
    for child in children:
        properties.append(child)


def format_differences(template, output) -> list[str]:
    """What in the finished file differs from the template's format, as short sentences. Empty when the format is the template's."""
    found: list[str] = []
    t_sections, o_sections = _sections(template), _sections(output)
    for n, (t_sect, o_sect) in enumerate(zip(t_sections, o_sections, strict=False), 1):
        t_sig, o_sig = _page_signature(t_sect), _page_signature(o_sect)
        for part, label in (("pgSz", "page size"), ("pgMar", "margins"), ("cols", "columns")):
            if t_sig[part] != o_sig[part]:
                found.append(f"{label} of section {n} differ from the template")
    looks = _template_looks(template)
    odd = Counter()
    for p in _real(output):
        key = (_kind(p), _in_table(p))
        allowed = looks.get(key)
        if allowed and not any(_same_look(_look(p), a) for a in allowed):
            odd[key[0]] += 1
    for kind, count in sorted(odd.items()):
        found.append(f"{count} {kind} paragraph(s) are aligned or indented differently from the template")
    t_fonts, t_sizes = _fonts_and_sizes(template)
    o_fonts, o_sizes = _fonts_and_sizes(output)
    if o_fonts - t_fonts:
        found.append("fonts the template does not use: " + ", ".join(sorted(o_fonts - t_fonts)))
    bounds = _allowed_sizes(t_sizes)
    if bounds and any(s < bounds[0] or s > bounds[1] for s in o_sizes):
        found.append("text sizes outside the template's range")
    return found


def restore_format(template, output) -> list[str]:
    """Put the template's page setup, alignment, indents, fonts and sizes back in `output` (a python-docx Document, changed in
    place). Returns what was fixed, as short sentences: empty when nothing needed fixing."""
    fixed: list[str] = []
    t_sections, o_sections = _sections(template), _sections(output)
    for n, (t_sect, o_sect) in enumerate(zip(t_sections, o_sections, strict=False), 1):
        t_sig, o_sig = _page_signature(t_sect), _page_signature(o_sect)
        for part, label in (("pgSz", "page size"), ("pgMar", "margins"), ("cols", "columns")):
            if t_sig[part] == o_sig[part]:
                continue
            old = o_sect.find(W + part)
            new = t_sect.find(W + part)
            position = list(o_sect).index(old) if old is not None else len(o_sect)
            if old is not None:
                o_sect.remove(old)
            if new is not None:
                o_sect.insert(position, deepcopy(new))
            fixed.append(f"restored the {label} of section {n}")

    looks = _template_looks(template)
    changed = Counter()
    for p in _real(output):
        key = (_kind(p), _in_table(p))
        allowed = looks.get(key)
        if allowed and not any(_same_look(_look(p), a) for a in allowed):
            _apply_look(p, allowed[0])
            changed[key[0]] += 1
    for kind, count in sorted(changed.items()):
        fixed.append(f"set the alignment and indents of {count} {kind} paragraph(s) to the template's")

    t_fonts, t_sizes = _fonts_and_sizes(template)
    bounds = _allowed_sizes(t_sizes)
    fonts_dropped = sizes_dropped = 0
    for rpr in list(output.element.body.iter(W + "rPr")):
        if rpr.getparent() is None or rpr.getparent().tag != W + "r":
            continue
        font = rpr.find(W + "rFonts")
        if font is not None and font.get(W + "ascii") and font.get(W + "ascii") not in t_fonts:
            rpr.remove(font)
            fonts_dropped += 1
        size = rpr.find(W + "sz")
        if bounds and size is not None and (size.get(W + "val") or "").isdigit() and not bounds[0] <= int(size.get(W + "val")) <= bounds[1]:
            rpr.remove(size)
            for complex_size in rpr.findall(W + "szCs"):
                rpr.remove(complex_size)
            sizes_dropped += 1
    if fonts_dropped:
        fixed.append(f"removed a font the template does not use from {fonts_dropped} run(s)")
    if sizes_dropped:
        fixed.append(f"removed a text size outside the template's range from {sizes_dropped} run(s)")
    return fixed

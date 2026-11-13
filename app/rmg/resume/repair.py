"""Fix the layout mistakes that templates commonly contain, in the finished document.

A template is somebody's Word file, so it can hold mistakes that only show up once real content is poured in: a table
row of fixed height (anything longer is cut off), a line height smaller than the text (letters are clipped), typed
page breaks (a blank page appears), piles of blank lines, headings left alone at the bottom of a page. These are
repaired after rendering, so the resume that comes out is clean whatever the template was like. Content is never
removed, only the empty space and the settings that hide or break it.
"""
from app.rmg.resume.fit import insert_spacing
from app.rmg.resume.template import W, is_blank, is_bullet, is_heading

PAGE_BREAK = f"{W}br"


def _paragraphs(body) -> list:
    return list(body.iter(W + "p"))


def _free_fixed_heights(body) -> None:
    """A fixed row height or line height cuts text off; "at least" keeps the look and lets content grow."""
    for height in body.iter(W + "trHeight"):
        if height.get(W + "hRule") == "exact":
            height.set(W + "hRule", "atLeast")
    for spacing in body.iter(W + "spacing"):
        if spacing.get(W + "lineRule") == "exact":
            spacing.set(W + "lineRule", "atLeast")


def _remove_typed_page_breaks(body) -> None:
    """A page break typed into the template lands in the middle of the new content and leaves a blank page."""
    for br in list(body.iter(PAGE_BREAK)):
        if br.get(W + "type") != "page":
            continue
        run = br.getparent()
        paragraph = run.getparent()
        run.remove(br)
        if len(run) == 0 or all(child.tag == W + "rPr" for child in run):
            paragraph.remove(run)
        if paragraph.tag == W + "p" and not any(True for _ in paragraph.iter(W + "t", W + "drawing")) and paragraph.getparent() is not None:
            if all(child.tag == W + "pPr" for child in paragraph):
                paragraph.getparent().remove(paragraph)


def _remove_trailing_blanks(body) -> None:
    """Empty paragraphs at the very end only add a blank page."""
    children = [c for c in body if c.tag != W + "sectPr"]
    while children and children[-1].tag == W + "p" and is_blank(children[-1]) and not children[-1].find(f".//{W}sectPr") is not None:
        body.remove(children.pop())


def _collapse_blank_runs(body) -> None:
    """Two or more empty paragraphs in a row become one; the template meant a gap, not a hole."""
    for parent in {p.getparent() for p in _paragraphs(body)}:
        previous_blank = False
        for child in list(parent):
            if child.tag != W + "p":
                previous_blank = False
                continue
            blank = is_blank(child) and child.find(f".//{W}sectPr") is None
            if blank and previous_blank:
                parent.remove(child)
            else:
                previous_blank = blank


def _trim_cell_ends(body) -> None:
    """Blank lines at the bottom of a table cell can push the table over the page edge and leave a blank page.
    A cell must still end with a paragraph, so one stays, as thin as it can be."""
    for cell in body.iter(W + "tc"):
        children = [c for c in cell if c.tag == W + "p"]
        while len(children) > 1 and is_blank(children[-1]) and is_blank(children[-2]):
            cell.remove(children.pop())
        last = children[-1] if children else None
        if last is None or not is_blank(last) or cell[-1] is not last:
            continue
        ppr = last.find(W + "pPr")
        if ppr is None:
            ppr = last.makeelement(W + "pPr", {})
            last.insert(0, ppr)
        spacing = ppr.find(W + "spacing")
        if spacing is None:
            spacing = ppr.makeelement(W + "spacing", {})
            insert_spacing(ppr, spacing)
        for name, value in (("before", "0"), ("after", "0"), ("line", "20"), ("lineRule", "atLeast")):
            spacing.set(W + name, value)
        mark = ppr.find(W + "rPr")
        if mark is None:
            mark = ppr.makeelement(W + "rPr", {})
            ppr.append(mark)
        for tag in ("sz", "szCs"):
            size = mark.find(W + tag)
            if size is None:  # (an element with no children is "falsy" in lxml, so test for None explicitly)
                size = mark.makeelement(W + tag, {})
                mark.append(size)
            size.set(W + "val", "2")


def _keep_together(body) -> None:
    """A heading stays with what follows it, and a bullet is not split across two pages.

    Inside a table cell this is done carefully: Word holds a whole table row together if its first paragraphs say
    "keep with next" and moves the row to the next page, leaving the page before it empty. So in a cell every paragraph
    switches keep-with-next off (overriding what the style says), except headings after the first one in that cell."""
    seen_heading: set = set()
    for p in _paragraphs(body):
        cell = p.getparent() if p.getparent().tag == W + "tc" else None
        ppr = p.find(W + "pPr")
        if ppr is None and cell is not None:
            ppr = p.makeelement(W + "pPr", {})
            p.insert(0, ppr)
        if ppr is None:
            continue
        heading = is_heading(p)
        if cell is not None:
            keep = _ensure(ppr, "keepNext")
            if heading and cell in seen_heading:
                keep.attrib.pop(W + "val", None)
            else:
                keep.set(W + "val", "0")
            seen_heading.add(cell) if heading else None
        elif heading:
            _ensure(ppr, "keepNext")
        if is_bullet(p):
            _ensure(ppr, "keepLines")
            _ensure(ppr, "widowControl")


_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl"]


def _ensure(ppr, name: str):
    found = ppr.find(W + name)
    if found is not None:
        return found
    earlier = _ORDER[:_ORDER.index(name)]
    position = 0
    for index, child in enumerate(ppr):
        if child.tag.split("}")[1] in earlier:
            position = index + 1
    element = ppr.makeelement(W + name, {})
    ppr.insert(position, element)
    return element


def repair_layout(doc) -> None:
    body = doc.element.body
    _free_fixed_heights(body)
    _remove_typed_page_breaks(body)
    _collapse_blank_runs(body)
    _remove_trailing_blanks(body)
    _trim_cell_ends(body)
    _keep_together(body)

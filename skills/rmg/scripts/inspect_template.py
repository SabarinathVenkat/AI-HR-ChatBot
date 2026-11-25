"""Show the structure of a Word template, so you can fill it without breaking its look.

Prints, in order, every paragraph (its style, whether it is a list item, and the start of its text) and every table (rows,
columns and the start of each cell). Read it before filling the template: it tells you which paragraph to copy for one more
bullet, which style a heading uses, and where the banner or the columns are.

Usage:
  python inspect_template.py assets/template.docx
Needs python-docx.
"""
import sys


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def is_list_item(paragraph) -> bool:
    """A bullet or numbered paragraph: numbering set on the paragraph itself, or on its style (or a style it is based on)."""
    if paragraph._p.find(f"{W}pPr/{W}numPr") is not None:
        return True
    style = paragraph.style
    while style is not None:
        if style.element.find(f"{W}pPr/{W}numPr") is not None:
            return True
        style = style.base_style
    return False


def describe(path: str) -> list[str]:
    from docx import Document

    doc = Document(path)
    w = W
    lines: list[str] = []
    paragraphs = {id(p._p): p for p in doc.paragraphs}
    tables = {id(t._tbl): t for t in doc.tables}
    for element in doc.element.body:
        if element.tag == w + "p":
            p = paragraphs.get(id(element))
            if p is None:
                continue
            kind = "list item" if is_list_item(p) else "paragraph"
            text = p.text.strip().replace("\n", " ")
            lines.append(f"{kind:<10} style={p.style.name!r:<22} {text[:70]!r}" if text else f"{kind:<10} style={p.style.name!r:<22} (empty)")
        elif element.tag == w + "tbl":
            t = tables.get(id(element))
            if t is None:
                continue
            lines.append(f"table      {len(t.rows)} row(s) x {len(t.columns)} column(s)")
            for r, row in enumerate(t.rows):
                for c, cell in enumerate(row.cells):
                    text = " / ".join(p.text.strip() for p in cell.paragraphs if p.text.strip())
                    lines.append(f"    cell[{r}][{c}] {text[:70]!r}")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Usage: python inspect_template.py <template.docx>", file=sys.stderr)
        return 2
    try:
        print("\n".join(describe(args[0])))
    except Exception as error:  # noqa: BLE001 - a clear message beats a traceback for a person at a prompt
        print(f"Could not read the template: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

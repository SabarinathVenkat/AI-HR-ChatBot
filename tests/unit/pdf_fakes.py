"""A tiny PDF writer for tests: pages of positioned text, so layout checks can be tested without Word or LibreOffice."""


def make_pdf(pages: list[list[tuple[float, float, str]]], size: tuple[int, int] = (612, 792)) -> bytes:
    """`pages` is a list of pages; a page is a list of (x, y, text), with y counted up from the bottom edge, in points."""
    def escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages))) + f"] /Count {len(pages)} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for i, items in enumerate(pages):
        stream = "\n".join(f"BT /F1 10 Tf {x} {y} Td ({escape(text)}) Tj ET" for x, y, text in items)
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {size[0]} {size[1]}] /Contents {5 + 2 * i} 0 R "
                       f"/Resources << /Font << /F1 3 0 R >> >> >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def lines_down(first_y: float, count: int, text: str = "A line of ordinary resume text that fills the page", x: float = 60) -> list:
    """`count` lines of text, one under the other, starting at first_y and going down the page."""
    return [(x, first_y - 14 * n, f"{text} {n}") for n in range(count)]

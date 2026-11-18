"""Look at a finished resume the way a person would: draw its pages, then measure them.

The Word file is turned into a PDF by LibreOffice (headless), and the pages are read back with pdfium. What is looked for is what
a person would call a layout mistake:
  - a blank or nearly blank page, or a last page with only a stray word or two
  - text in the file that was never drawn (cut off, hidden by a fixed height)
  - text running off the page edge
  - a section heading left alone at the bottom of a page
  - more pages than the limit
The same checks run in the layout lab against Word's own output, so the two agree.

Nothing here can stop a download: with no LibreOffice installed, or if it fails, the renderer gives nothing back and the caller
carries on with the file as it is.
"""
import io
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from docx import Document

from app.rmg.resume.conformance import _slot_headings
from app.rmg.resume.fit import MAX_PAGES
from app.rmg.resume.template import W, analyse, paragraph_text

MIN_WORDS_PER_PAGE = 12
STRAY_LAST_PAGE_WORDS = 6  # a last page with fewer words than this is a stray line, not a real page
EDGE = 8  # points from the page edge that text must stay inside
MISSING_ALLOWED = 0.02  # share of the file's letters that may be absent from the drawn pages
IMAGE_WIDTH = 900  # pictures sent to a model are this wide (enough to read, cheap to send)


Renderer = Callable[[bytes], bytes | None]  # a Word file in, the drawn PDF out (None if it could not be drawn)


def soffice_binary() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


class LibreOfficeRenderer:
    """Word file in, PDF out, or None if it could not be done. Each run uses its own profile, so runs never block each other."""

    def __init__(self, binary: str, timeout: int = 90):
        self.binary, self.timeout = binary, timeout

    def __call__(self, docx: bytes) -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "resume.docx"
            source.write_bytes(docx)
            command = [self.binary, f"-env:UserInstallation={(Path(tmp) / 'profile').as_uri()}", "--headless", "--convert-to", "pdf",
                       "--outdir", tmp, str(source)]
            try:
                subprocess.run(command, capture_output=True, timeout=self.timeout, check=True)
                return (Path(tmp) / "resume.pdf").read_bytes()
            except (subprocess.SubprocessError, OSError):
                return None


def default_renderer() -> LibreOfficeRenderer | None:
    binary = soffice_binary()
    return LibreOfficeRenderer(binary) if binary else None


@dataclass(frozen=True)
class Measured:
    pages: int
    problems: tuple[str, ...]
    images: tuple[bytes, ...]  # the first pages, as PNG


def _letters(text: str) -> Counter:
    return Counter(re.findall(r"\w", text.lower()))


def _words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def _png(page, scale: float = 1.0) -> bytes:
    image = page.render(scale=scale).to_pil()
    if image.width > IMAGE_WIDTH:
        image = image.resize((IMAGE_WIDTH, round(image.height * IMAGE_WIDTH / image.width)))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def measure(pdf: bytes, docx: bytes, *, max_pages: int = MAX_PAGES, want_images: int = 3) -> Measured:
    """The pages of `pdf` (the drawn version of `docx`) checked for layout mistakes."""
    document = Document(io.BytesIO(docx))
    expected = " ".join(paragraph_text(p) for p in document.element.body.iter(W + "p"))
    headings = list(dict.fromkeys(text for _, text in _slot_headings(document, analyse(document)) if text))
    pages = pdfium.PdfDocument(pdf)
    problems: list[str] = []
    drawn = ""
    images: list[bytes] = []
    if len(pages) > max_pages:
        problems.append(f"{len(pages)} pages (the limit is {max_pages})")
    for n in range(len(pages)):
        page = pages[n]
        width, _ = page.get_size()
        textpage = page.get_textpage()
        text = textpage.get_text_range()
        drawn += " " + text
        count = textpage.count_chars()
        words = _words(text)
        last = n == len(pages) - 1
        if (last and len(pages) > 1 and words < STRAY_LAST_PAGE_WORDS) or (not last and words < MIN_WORDS_PER_PAGE) or (len(pages) == 1 and words < 1):
            problems.append(f"page {n + 1} is blank or nearly blank")
        boxes = [textpage.get_charbox(i) for i in range(count) if text[i].strip()] if count == len(text) else []
        if boxes and (min(b[0] for b in boxes) < EDGE - 4 or max(b[2] for b in boxes) > width - EDGE + 4):
            problems.append(f"page {n + 1}: text reaches the page edge")
        for heading in headings:
            start = text.find(heading)
            if start < 0 or count != len(text):
                continue
            left, bottom, _, _ = textpage.get_charbox(start)
            if not [b for b in boxes if b[3] < bottom - 2 and left - 4 <= b[0] <= left + 160]:
                problems.append(f"page {n + 1}: heading '{heading}' has nothing under it")
        if n < want_images:
            images.append(_png(page))
    wanted, shown = _letters(expected), _letters(drawn)
    total, lost = sum(wanted.values()), sum((wanted - shown).values())
    if total and lost / total > MISSING_ALLOWED:
        problems.append(f"{lost} of {total} letters in the file were never drawn (text is cut off or hidden)")
    return Measured(pages=len(pages), problems=tuple(problems), images=tuple(images))

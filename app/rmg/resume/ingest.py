"""Read an uploaded document safely.

A file's name, size and type are claims made by whoever uploaded it, so none is trusted. read_document checks the
cheap things first (name, extension, size, the file's real type), then opens the file with limits, and returns plain
text (plus the PDF bytes, which can be sent to the model as they are). Every rejection is an IngestError with a short
machine-readable code and a friendly message that does not reveal internals.
"""
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from typing import Literal

from docx import Document
from pypdf import PasswordType, PdfReader

MAX_BYTES = 5_000_000
MAX_UNCOMPRESSED = 50_000_000
MAX_ENTRIES = 1000
MAX_PAGES = 10  # an RMG decision: a resume is at most ten pages
MAX_TEXT_CHARS = 40_000  # about ten dense pages; the real limit for a docx, whose page count is only a claim

EXTENSIONS = {".docx": "docx", ".pdf": "pdf", ".txt": "txt"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

MESSAGES = {
    "unsupported_type": "Please upload a Word (.docx), PDF or text file.",
    "too_large": "That file is too large.",
    "type_mismatch": "The file's contents do not match its extension. Please upload a real .docx, .pdf or .txt file.",
    "too_large_uncompressed": "That document is far larger than a resume should be once opened.",
    "too_many_parts": "That document has too many internal parts to be a normal resume.",
    "macros_not_allowed": "Documents with macros are not accepted. Please save a copy without macros and upload that.",
    "password_protected": "That PDF is password-protected. Please remove the password and upload it again.",
    "corrupt": "That file could not be read. Please check that it opens normally and upload it again.",
    "too_many_pages": f"That document is longer than {MAX_PAGES} pages. Please upload a resume of at most {MAX_PAGES} pages.",
    "text_too_long": "That document has far more text than a resume should.",
    "empty": "That document has no readable text.",
}


class IngestError(Exception):
    """A document was rejected. `code` is for programs and tests; the message is for the person who uploaded it."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(MESSAGES[code])


@dataclass(frozen=True)
class SourceDocument:
    kind: Literal["docx", "pdf", "txt"]
    filename: str
    text: str  # may be empty for a scanned PDF, which has no text layer
    pdf_bytes: bytes | None = None  # the PDF itself, for sending to the model as it is
    pages: int | None = None  # a PDF's real page count; a docx's own claim; None for text


def read_document(
    filename: str,
    data: bytes,
    *,
    max_bytes: int = MAX_BYTES,
    max_uncompressed: int = MAX_UNCOMPRESSED,
    max_entries: int = MAX_ENTRIES,
    max_pages: int = MAX_PAGES,
    max_text_chars: int = MAX_TEXT_CHARS,
) -> SourceDocument:
    name = _safe_name(filename)
    kind = EXTENSIONS.get(posixpath.splitext(name)[1].lower())
    if kind is None:
        raise IngestError("unsupported_type")
    if len(data) > max_bytes:  # before any parsing
        raise IngestError("too_large")
    _check_real_type(kind, data)

    pdf_bytes, pages = None, None
    if kind == "docx":
        text, pages = _read_docx(data, max_uncompressed, max_entries, max_pages)
    elif kind == "pdf":
        text, pages = _read_pdf(data, max_pages)
        pdf_bytes = data
    else:
        text = _read_txt(data)

    if len(text) > max_text_chars:
        raise IngestError("text_too_long")
    if kind != "pdf" and not text.strip():  # a PDF may legitimately have no text layer (a scan)
        raise IngestError("empty")
    return SourceDocument(kind=kind, filename=name, text=text, pdf_bytes=pdf_bytes, pages=pages)


def _safe_name(filename: str) -> str:
    """Only the last part of the name: no directories, so a crafted name cannot point elsewhere."""
    name = posixpath.basename((filename or "").replace("\\", "/")).strip()
    return name or "document"


def _check_real_type(kind: str, data: bytes) -> None:
    is_pdf, is_zip = data.startswith(b"%PDF-"), data.startswith(b"PK\x03\x04")
    ok = (kind == "pdf" and is_pdf) or (kind == "docx" and is_zip) or (kind == "txt" and not is_pdf and not is_zip)
    if not ok:
        raise IngestError("type_mismatch")


def _claimed_pages(archive: zipfile.ZipFile) -> int | None:
    """The page count Word stored in the file's metadata. It is the sender's claim, so it is only a hint."""
    try:
        xml = archive.open("docProps/app.xml").read(65_536).decode("utf-8", "ignore")
    except Exception:
        return None
    match = re.search(r"<Pages>\s*(\d{1,4})\s*</Pages>", xml)
    return int(match.group(1)) if match else None


def _read_docx(data: bytes, max_uncompressed: int, max_entries: int, max_pages: int) -> tuple[str, int | None]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = archive.infolist()
    except Exception:
        raise IngestError("corrupt") from None
    if len(infos) > max_entries:
        raise IngestError("too_many_parts")
    if sum(i.file_size for i in infos) > max_uncompressed:  # a "zip bomb": tiny on disk, huge when unpacked
        raise IngestError("too_large_uncompressed")
    names = {i.filename.lower() for i in infos}
    if any(n.endswith("vbaproject.bin") for n in names):
        raise IngestError("macros_not_allowed")
    if "word/document.xml" not in names:
        raise IngestError("corrupt")
    pages = _claimed_pages(archive)
    if pages is not None and pages > max_pages:  # an early, cheap rejection; the text cap below is the real limit
        raise IngestError("too_many_pages")
    try:
        doc = Document(io.BytesIO(data))
        headers = [_paragraph_text(p._p) for section in doc.sections for p in section.header.paragraphs]
        body = list(_body_lines(doc.element.body))
    except Exception:
        raise IngestError("corrupt") from None
    # A name is often in the page header. Headers repeat across sections, so de-duplicate those lines only:
    # a repeated line in the body is real content.
    header_lines = list(dict.fromkeys(line for line in headers if line.strip()))
    return "\n".join(header_lines + [line for line in body if line.strip()]), pages


def _paragraph_text(p) -> str:
    """The text of a paragraph. A line break inside it starts a new line and a tab is a space, so words are never glued."""
    parts = []
    for element in p.iter():
        if element.tag == W + "t":
            parts.append(element.text or "")
        elif element.tag in (W + "br", W + "cr"):
            parts.append("\n")
        elif element.tag == W + "tab":
            parts.append(" ")
    return "".join(parts)


def _body_lines(container):
    """Paragraphs and tables in the order they appear, one paragraph per line (a body, a table cell, a content control)."""
    for child in container.iterchildren():
        if child.tag == W + "p":
            yield _paragraph_text(child)
        elif child.tag == W + "tbl":
            yield from _table_lines(child)
        elif child.tag == W + "sdt":  # a content control wraps ordinary content
            content = child.find(W + "sdtContent")
            if content is not None:
                yield from _body_lines(content)


def _table_lines(table):
    """A simple row ("Skills" | "Java, Kafka") becomes one line, 'cell | cell'. A cell with several paragraphs (a layout
    table that holds a whole resume) gives one line per paragraph, so its text is not run together into one giant line.
    Tables inside cells are read once, by their own rows."""
    for row in table.findall(W + "tr"):
        cells = [[line for line in _body_lines(cell) if line.strip()] for cell in row.findall(W + "tc")]
        if all(len(lines) <= 1 for lines in cells):
            yield " | ".join(lines[0].strip() for lines in cells if lines)
        else:
            for lines in cells:
                yield from lines


def _read_pdf(data: bytes, max_pages: int) -> tuple[str, int]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            raise IngestError("password_protected")
        count = len(reader.pages)
    except IngestError:
        raise
    except Exception:
        raise IngestError("corrupt") from None
    if count > max_pages:
        raise IngestError("too_many_pages")
    try:
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip(), count
    except Exception:
        return "", count  # the PDF can still be sent to the model as it is


def _read_txt(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if "\x00" in text:  # binary content with a .txt name
        raise IngestError("corrupt")
    return text

"""Reading uploaded documents safely.

An upload's name, size and type are all claims by whoever sent it, so each is checked against the real bytes.
All files here are built in memory; nothing is a real document.
"""
import dataclasses
import io
import zipfile

import pytest
from docx import Document
from pypdf import PdfWriter

from app.rmg.resume.ingest import IngestError, SourceDocument, read_document


# --- tiny file builders ------------------------------------------------------------------------

def docx_bytes(paragraphs=(), table=None, header=None) -> bytes:
    doc = Document()
    for text in paragraphs:
        doc.add_paragraph(text)
    if table:
        t = doc.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
    if header:
        doc.sections[0].header.paragraphs[0].text = header
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def pdf_with_text(text="Hello resume") -> bytes:
    """A small, valid one-page PDF with a line of text, built by hand."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return out


def blank_pdf(pages=1, password=None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if password:
        writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def with_extra_entry(docx: bytes, name: str, payload: bytes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            z.writestr(item, src.read(item.filename))
        z.writestr(name, payload)
    return out.getvalue()


def code_of(exc_info) -> str:
    return exc_info.value.code


# --- reading the three supported kinds ---------------------------------------------------------

def test_a_docx_is_read_in_document_order_including_tables():
    data = docx_bytes(paragraphs=["Anil Verma", "Senior Engineer"], table=[["Skills", "Java, Kafka"], ["Cloud", "AWS"]])

    doc = read_document("cv.docx", data)

    assert doc.kind == "docx" and doc.pdf_bytes is None
    assert doc.text.index("Anil Verma") < doc.text.index("Java, Kafka") < doc.text.index("AWS")
    assert "Skills | Java, Kafka" in doc.text


def test_text_in_a_docx_header_is_included_because_names_often_live_there():
    doc = read_document("cv.docx", docx_bytes(paragraphs=["Body text"], header="Meera Krishnan"))

    assert "Meera Krishnan" in doc.text


def test_a_line_that_repeats_in_the_body_is_kept_because_it_is_real_content():
    doc = read_document("cv.docx", docx_bytes(paragraphs=["Responsible for testing", "Java", "Responsible for testing"]))

    assert doc.text.count("Responsible for testing") == 2


def test_a_plain_text_file_is_read():
    doc = read_document("cv.txt", "Anil Verma\nJava, Kafka".encode("utf-8"))

    assert doc.kind == "txt" and doc.text == "Anil Verma\nJava, Kafka" and doc.pdf_bytes is None


def test_a_pdf_keeps_its_bytes_so_it_can_be_sent_to_the_model_as_it_is():
    data = pdf_with_text("Hello resume")

    doc = read_document("cv.pdf", data)

    assert doc.kind == "pdf" and doc.pdf_bytes == data and "Hello resume" in doc.text


def test_a_pdf_with_no_text_layer_is_allowed_because_a_scanned_resume_looks_like_this():
    doc = read_document("scan.pdf", blank_pdf())

    assert doc.kind == "pdf" and doc.text == "" and doc.pdf_bytes


# --- the file's claims are checked against its bytes -------------------------------------------

@pytest.mark.parametrize("name", ["cv.exe", "cv.doc", "cv.docm", "cv.zip", "cv", "cv.pdf.exe"])
def test_unsupported_types_are_rejected_by_extension(name):
    with pytest.raises(IngestError) as e:
        read_document(name, b"anything")
    assert code_of(e) == "unsupported_type"


def test_the_extension_must_match_the_content():
    with pytest.raises(IngestError) as e:
        read_document("cv.docx", pdf_with_text())
    assert code_of(e) == "type_mismatch"
    with pytest.raises(IngestError) as e:
        read_document("cv.pdf", docx_bytes(["hi"]))
    assert code_of(e) == "type_mismatch"


def test_a_directory_path_in_the_filename_is_removed():
    doc = read_document("..\\..\\windows\\system32\\cv.docx", docx_bytes(["hi"]))

    assert doc.filename == "cv.docx"
    assert read_document("/etc/passwd/../cv.txt", b"hi").filename == "cv.txt"


# --- limits (cheap checks first) ----------------------------------------------------------------

def test_a_file_over_the_size_limit_is_rejected_before_it_is_parsed():
    with pytest.raises(IngestError) as e:
        read_document("cv.docx", b"x" * 101, max_bytes=100)
    assert code_of(e) == "too_large"


def test_a_docx_that_expands_enormously_is_rejected_as_a_zip_bomb():
    bomb = with_extra_entry(docx_bytes(["hi"]), "word/media/big.bin", b"\0" * 5_000_000)
    assert len(bomb) < 100_000  # tiny on disk, huge when unpacked

    with pytest.raises(IngestError) as e:
        read_document("cv.docx", bomb, max_uncompressed=1_000_000)
    assert code_of(e) == "too_large_uncompressed"


def test_a_docx_with_too_many_parts_is_rejected():
    many = docx_bytes(["hi"])
    for i in range(30):
        many = with_extra_entry(many, f"extra/part{i}.xml", b"<a/>")

    with pytest.raises(IngestError) as e:
        read_document("cv.docx", many, max_entries=25)
    assert code_of(e) == "too_many_parts"


def test_a_pdf_with_too_many_pages_is_rejected():
    with pytest.raises(IngestError) as e:
        read_document("cv.pdf", blank_pdf(pages=6), max_pages=5)
    assert code_of(e) == "too_many_pages"


def test_extracted_text_that_is_absurdly_long_is_rejected():
    with pytest.raises(IngestError) as e:
        read_document("cv.txt", ("word " * 500).encode(), max_text_chars=1000)
    assert code_of(e) == "text_too_long"


# --- files that are dangerous or unusable -------------------------------------------------------

def test_a_word_file_carrying_macros_is_rejected_even_if_named_docx():
    smuggled = with_extra_entry(docx_bytes(["hi"]), "word/vbaProject.bin", b"macro bytes")

    with pytest.raises(IngestError) as e:
        read_document("cv.docx", smuggled)
    assert code_of(e) == "macros_not_allowed"


def test_a_password_protected_pdf_is_rejected():
    with pytest.raises(IngestError) as e:
        read_document("cv.pdf", blank_pdf(password="secret"))
    assert code_of(e) == "password_protected"


def test_a_corrupt_pdf_is_rejected():
    with pytest.raises(IngestError) as e:
        read_document("cv.pdf", b"%PDF-1.4\nthis is not really a pdf")
    assert code_of(e) == "corrupt"


def test_a_corrupt_docx_is_rejected():
    with pytest.raises(IngestError) as e:
        read_document("cv.docx", b"PK\x03\x04 not really a zip")
    assert code_of(e) == "corrupt"


def test_a_docx_without_any_text_is_rejected_as_empty():
    with pytest.raises(IngestError) as e:
        read_document("cv.docx", docx_bytes([]))
    assert code_of(e) == "empty"


def test_an_empty_text_file_is_rejected():
    with pytest.raises(IngestError) as e:
        read_document("cv.txt", b"   \n  ")
    assert code_of(e) == "empty"


# --- the errors themselves -----------------------------------------------------------------------

def test_errors_carry_a_friendly_message_that_does_not_leak_internals():
    with pytest.raises(IngestError) as e:
        read_document("cv.pdf", b"%PDF-1.4\nthis is not really a pdf")

    message = str(e.value)
    assert message and "Traceback" not in message and "pypdf" not in message and ".py" not in message


def test_a_source_document_is_immutable():
    doc = read_document("cv.txt", b"hello")
    assert isinstance(doc, SourceDocument)
    with pytest.raises(dataclasses.FrozenInstanceError):
        doc.text = "changed"


# --- the five-page limit (RMG decision) ----------------------------------------------------------

def with_page_count(docx: bytes, pages: int) -> bytes:
    """A copy of a docx whose own metadata claims a page count (the file's claim, which we do not fully trust)."""
    src = zipfile.ZipFile(io.BytesIO(docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for item in src.infolist():
            payload = src.read(item.filename)
            if item.filename == "docProps/app.xml":
                payload = f'<Properties><Pages>{pages}</Pages></Properties>'.encode()
            z.writestr(item, payload)
    return out.getvalue()


def test_the_default_limit_is_five_pages_for_a_pdf():
    assert read_document("five.pdf", blank_pdf(pages=5)).pages == 5

    with pytest.raises(IngestError) as e:
        read_document("six.pdf", blank_pdf(pages=6))
    assert code_of(e) == "too_many_pages"


def test_a_docx_that_says_it_is_longer_than_five_pages_is_rejected_early():
    with pytest.raises(IngestError) as e:
        read_document("cv.docx", with_page_count(docx_bytes(["hi"]), 8))
    assert code_of(e) == "too_many_pages"


def test_a_docx_that_says_it_is_five_pages_or_fewer_is_accepted():
    doc = read_document("cv.docx", with_page_count(docx_bytes(["hi"]), 5))

    assert doc.pages == 5


def test_the_page_count_a_docx_claims_is_a_hint_not_the_limit_so_the_text_cap_still_applies():
    understated = with_page_count(docx_bytes(["word " * 5000]), 1)  # claims one page, holds far more than five

    with pytest.raises(IngestError) as e:
        read_document("cv.docx", understated)
    assert code_of(e) == "text_too_long"


def test_about_five_pages_of_text_is_allowed_and_more_is_not_by_default():
    five_pages = ("a" * 99 + " ") * 200  # 20,000 characters

    assert read_document("cv.txt", five_pages.encode()).kind == "txt"
    with pytest.raises(IngestError) as e:
        read_document("cv.txt", (five_pages + "more").encode())
    assert code_of(e) == "text_too_long"


def test_a_text_file_has_no_page_count():
    assert read_document("cv.txt", b"hello").pages is None


# --- found with a real resume: the whole resume sat inside table cells and became one giant line -------------------------

def docx_with_layout_table(paragraphs_in_cell, nested=None):
    doc = Document()
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.paragraphs[0].text = paragraphs_in_cell[0]
    for text in paragraphs_in_cell[1:]:
        cell.add_paragraph(text)
    if nested:
        inner = cell.add_table(rows=len(nested), cols=2)
        for r, (a, b) in enumerate(nested):
            inner.cell(r, 0).text, inner.cell(r, 1).text = a, b
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_a_layout_table_whose_cell_holds_the_whole_resume_is_read_one_paragraph_per_line():
    lines = ["Name Surname", "Senior Data Engineer", "SKILLS", "Python, SQL, Spark", "EXPERIENCE", "Built pipelines that process 2 TB a day."]

    doc = read_document("cv.docx", docx_with_layout_table(lines))

    assert doc.text.splitlines() == lines  # not one long line


def test_a_table_inside_a_table_is_read_once_not_twice():
    doc = read_document("cv.docx", docx_with_layout_table(["Intro paragraph", "Second paragraph"], nested=[("Backend", "Java"), ("Cloud", "AWS")]))

    assert doc.text.count("Backend | Java") == 1 and doc.text.count("Cloud | AWS") == 1
    assert doc.text.count("Intro paragraph") == 1


def test_a_simple_label_and_value_row_is_still_one_line():
    doc = read_document("cv.docx", docx_bytes(table=[["Skills", "Java, Kafka"], ["Cloud", "AWS"]]))

    assert "Skills | Java, Kafka" in doc.text.splitlines() and "Cloud | AWS" in doc.text.splitlines()


def test_a_line_break_inside_a_paragraph_starts_a_new_line_instead_of_gluing_the_words_together():
    doc = Document()
    paragraph = doc.add_paragraph("First line")
    paragraph.add_run().add_break()
    paragraph.add_run("Second line")
    buf = io.BytesIO()
    doc.save(buf)

    assert read_document("cv.docx", buf.getvalue()).text.splitlines() == ["First line", "Second line"]

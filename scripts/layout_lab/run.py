"""Layout lab: render every resume into every template, open the results in Word, and measure what went wrong.

    python -m scripts.layout_lab.run            # everything
    python -m scripts.layout_lab.run classic    # only templates whose name contains "classic"

Needs Microsoft Word (it converts each .docx to PDF the way a person would see it). Results go to var/lab/.
A problem is anything a person would call a layout mistake: text cut off or missing, a blank or nearly blank page,
a heading stranded at the bottom of a page, text running off the page edge, or too many pages.
"""
import io
import re
from collections import Counter
import subprocess
import sys
from pathlib import Path

import pypdfium2 as pdfium
from docx import Document

from app.rmg.resume.conformance import check_conformance
from app.rmg.resume.render import render_best
from app.rmg.resume.template import W, is_heading, paragraph_text
from scripts.layout_lab.resumes import RESUMES
from scripts.layout_lab.templates import TEMPLATES

LAB = Path("var/lab")
REAL_TEMPLATE = Path("app/rmg/doc/resume/Sample Profile_Ideas2it.docx")
MAX_PAGES = 5
CONVERT_TIMEOUT = 90  # seconds Word may take on one file
MIN_WORDS_PER_PAGE = 12
EDGE = 8  # points from the page edge that text must stay inside
MISSING_ALLOWED = 0.02  # share of words that may be absent from the PDF


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _docx_text(data: bytes) -> tuple[str, list[str]]:
    doc = Document(io.BytesIO(data))
    paragraphs = list(doc.element.body.iter(W + "p"))
    headings = [paragraph_text(p).strip() for p in paragraphs if is_heading(p)]
    return "\n".join(paragraph_text(p) for p in paragraphs), headings


def generate() -> dict[str, dict]:
    """Write every docx; returns {case name: info}."""
    (LAB / "docx").mkdir(parents=True, exist_ok=True)
    templates = {name: build()[0] for name, build in TEMPLATES.items()}
    if REAL_TEMPLATE.exists():
        templates["real_ideas2it"] = REAL_TEMPLATE.read_bytes()
    cases = {}
    pick = sys.argv[1] if len(sys.argv) > 1 else ""
    for t_name, t_bytes in templates.items():
        if pick not in t_name:
            continue
        for r_name, resume in RESUMES.items():
            name = f"{t_name}__{r_name}"
            result = render_best(t_bytes, resume, years_text="5 years")
            target = LAB / "docx" / f"{name}.docx"
            if not target.exists() or target.read_bytes() != result.docx:  # unchanged files keep their converted PDF
                target.write_bytes(result.docx)
            report = check_conformance(t_bytes, result.docx, resume, used_standard_layout=result.used_standard_layout)
            cases[name] = {"problems": result.problems, "report": report}
    return cases


def _convert_one(docx: Path, pdf: Path) -> str | None:
    script = ("$w = New-Object -ComObject Word.Application; $w.Visible = $false; $w.DisplayAlerts = 0; "
              f"try {{ $d = $w.Documents.Open('{docx.resolve()}', $false, $true); $d.ExportAsFixedFormat('{pdf.resolve()}', 17); $d.Close($false) }} "
              "catch { Write-Host ('FAILED ' + $_.Exception.Message) } finally { try { $w.Quit() } catch {} }")
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-Command", script], timeout=CONVERT_TIMEOUT, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return "Word hung on this file"
    return done.stdout.strip() or None


def convert() -> dict[str, str]:
    """One fresh Word per file (a second document in one session fails here), each with a time limit."""
    (LAB / "pdf").mkdir(parents=True, exist_ok=True)
    failures = {}
    for docx in sorted((LAB / "docx").glob("*.docx")):
        pdf = LAB / "pdf" / f"{docx.stem}.pdf"
        if pdf.exists() and pdf.stat().st_mtime >= docx.stat().st_mtime:
            continue
        error = _convert_one(docx, pdf)
        if error:
            failures[docx.stem] = error
    return failures


def measure(name: str) -> list[str]:
    docx_text, headings = _docx_text((LAB / "docx" / f"{name}.docx").read_bytes())
    pdf_path = LAB / "pdf" / f"{name}.pdf"
    if not pdf_path.exists():
        return ["Word could not open the file"]
    pdf = pdfium.PdfDocument(str(pdf_path))
    problems, pdf_words = [], []
    if len(pdf) > MAX_PAGES:
        problems.append(f"{len(pdf)} pages")
    for n in range(len(pdf)):
        page = pdf[n]
        width, height = page.get_size()
        tp = page.get_textpage()
        text = tp.get_text_range()
        pdf_words += _words(text)
        count = tp.count_chars()
        if len(_words(text)) < MIN_WORDS_PER_PAGE:
            problems.append(f"page {n + 1} is blank or nearly blank")
        boxes = [tp.get_charbox(i) for i in range(count) if text[i].strip()] if count == len(text) else []
        if boxes and (min(b[0] for b in boxes) < EDGE - 4 or max(b[2] for b in boxes) > width - EDGE + 4):
            problems.append(f"page {n + 1}: text reaches the page edge")
        for heading in dict.fromkeys(headings):
            start = text.find(heading)
            if start < 0 or count != len(text):
                continue
            hl, hb, hr, ht = tp.get_charbox(start)
            below = [b for b in boxes if b[3] < hb - 2 and hl - 4 <= b[0] <= hl + 160]
            if not below:
                problems.append(f"page {n + 1}: heading '{heading}' has nothing under it")
    # compare letters, not words: a long unbroken token wraps in Word and would otherwise count as lost words
    wanted = Counter(re.findall(r"\w", docx_text.lower()))
    shown = Counter(re.findall(r"\w", " ".join(pdf_words)))
    lost = sum((wanted - shown).values())
    total = sum(wanted.values())
    if total and lost / total > MISSING_ALLOWED:
        problems.append(f"{lost} of {total} letters are cut off or hidden in Word")
    return problems


def main() -> int:
    cases = generate()
    failures = convert()
    lines, bad = [], 0
    for name, info in cases.items():
        if "error" in info:
            lines.append(f"REFUSED  {name}: {info['error']}")
            continue
        found = [failures[name]] if name in failures else measure(name)
        bad += bool(found)
        notes = f" | notes: {'; '.join(info['problems'])}" if info["problems"] else ""
        report = info["report"]
        notes += f" | check: {report.status}" + (" (" + ", ".join(c.name + ": " + c.message for c in report.checks if c.status != "pass") + ")" if report.status != "pass" else "")
        lines.append(f"{'PROBLEM' if found else 'ok     '}  {name}: {'; '.join(found) or 'fine'}{notes}")
    statuses = [c["report"].status for c in cases.values() if "report" in c]
    report = "\n".join(lines) + f"\n\n{len(cases)} cases, {bad} with layout problems; conformance: " + ", ".join(f"{n} {s}" for s in ("pass", "warn", "fail") if (n := statuses.count(s))) + "\n"
    (LAB / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

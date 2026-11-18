"""Judge the layout of a finished resume and fix it, without ever touching the words.

    render the Word file to pages -> measure them in code -> a model looks at the pages (next to the template's own sample page)
    -> if it is not right, the model picks fixes from a short list -> apply them -> measure again -> keep the result only if it is better

The model is not trusted with the document. It can only name a formatting change from ALLOWED_FIXES; each change is made by code
and checked: if the letters of the document are different afterwards the change is refused. A fix that does not make the pages
measure better is thrown away. And nothing here can stop a download: with no renderer, or if anything fails, the file is
returned as it was, marked "not_checked".

Status: ok (nothing needed doing), fixed, unfixed (problems remain; the best version is returned) or not_checked.
"""
import base64
import hashlib
import io
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from docx import Document
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.rmg.resume.extract import ExtractionError, ModelFactory, structured_call
from app.rmg.resume.fit import LEVELS, _tighten
from app.rmg.resume.layout_check import Measured, Renderer, measure
from app.rmg.resume.repair import _collapse_blank_runs, _ensure
from app.rmg.resume.template import W, is_blank, is_heading, paragraph_text

MAX_ROUNDS = 2
JUDGE_OUTPUT_TOKENS = 1200
CACHE_SIZE = 64

ALLOWED_FIXES = ("tighten", "keep_next_off", "remove_blank_lines", "break_before", "no_break_before", "grow_header")
HEADER_STEP_TWIPS = 360  # one level of grow_header adds this much (a line and a half) to the banner


class Fix(BaseModel):
    op: Literal["tighten", "keep_next_off", "remove_blank_lines", "break_before", "no_break_before", "grow_header"]
    level: int | None = Field(default=None, ge=1, le=3)  # tighten / grow_header: how much (1 a little, 3 a lot)
    heading: str | None = None  # break_before / no_break_before: the section heading, as written


class Verdict(BaseModel):
    ok: bool
    issues: list[str] = Field(default_factory=list)  # what the judge saw
    fixes: list[Fix] = Field(default_factory=list)  # what to change, from ALLOWED_FIXES only


Judge = Callable[[list[bytes], list[str], bytes | None], Verdict]


# --- the fixes: formatting only ---------------------------------------------------------------------------------------------

def _paragraphs(doc) -> list:
    return list(doc.element.body.iter(W + "p"))


def _tighten_all(doc, fix: Fix) -> None:
    scale, drop = LEVELS[fix.level or 1]
    for p in _paragraphs(doc):
        _tighten(p, scale, drop)


def _keep_next_off(doc, fix: Fix) -> None:
    for p in _paragraphs(doc):
        ppr = p.find(W + "pPr")
        if ppr is None:
            ppr = p.makeelement(W + "pPr", {})
            p.insert(0, ppr)
        _ensure(ppr, "keepNext").set(W + "val", "0")


def _remove_blank_lines(doc, fix: Fix) -> None:
    for p in _paragraphs(doc):
        if not is_heading(p):
            continue
        previous = p.getprevious()
        while previous is not None and previous.tag == W + "p" and is_blank(previous):
            p.getparent().remove(previous)
            previous = p.getprevious()
    _collapse_blank_runs(doc.element.body)


def _heading_named(doc, fix: Fix):
    wanted = " ".join((fix.heading or "").split()).casefold()
    return next((p for p in _paragraphs(doc) if wanted and " ".join(paragraph_text(p).split()).casefold() == wanted
                 and p.getparent().tag == W + "body"), None)


def _break_before(doc, fix: Fix) -> None:
    heading = _heading_named(doc, fix)
    if heading is not None:
        ppr = heading.find(W + "pPr")
        if ppr is None:
            ppr = heading.makeelement(W + "pPr", {})
            heading.insert(0, ppr)
        _ensure(ppr, "keepNext")
        _ensure(ppr, "pageBreakBefore")


def _no_break_before(doc, fix: Fix) -> None:
    heading = _heading_named(doc, fix)
    if heading is not None:
        for element in heading.findall(f"{W}pPr/{W}pageBreakBefore"):
            element.getparent().remove(element)


def _grow_header(doc, fix: Fix) -> None:
    """Make the banner at the top (the first table, if the page starts with one) taller, so what follows it clears it."""
    first = next(iter(doc.element.body), None)
    table = first if first is not None and first.tag == W + "tbl" else None
    if table is None:
        return
    rows = table.findall(W + "tr")
    properties = rows[-1].find(W + "trPr")
    if properties is None:
        properties = rows[-1].makeelement(W + "trPr", {})
        rows[-1].insert(0, properties)
    height = properties.find(W + "trHeight")
    if height is None:
        height = properties.makeelement(W + "trHeight", {W + "val": "0"})
        properties.append(height)
    height.set(W + "val", str(int(float(height.get(W + "val") or 0)) + (fix.level or 1) * HEADER_STEP_TWIPS))
    height.set(W + "hRule", "atLeast")


_OPS = {"grow_header": _grow_header, "tighten": _tighten_all, "keep_next_off": _keep_next_off, "remove_blank_lines": _remove_blank_lines,
        "break_before": _break_before, "no_break_before": _no_break_before}


def _letters(doc) -> Counter:
    return Counter(c for p in _paragraphs(doc) for c in paragraph_text(p))


def apply_fixes(docx: bytes, fixes: list[Fix]) -> bytes | None:
    """The file with these formatting changes made, or None if that would change a single letter of the text."""
    doc = Document(io.BytesIO(docx))
    before = _letters(doc)
    for fix in fixes:
        _OPS[fix.op](doc, fix)
    if _letters(doc) != before:
        return None
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def default_fixes(problems: list[str], round_number: int) -> list[Fix]:
    """What to try when there is no judge to choose: a little at first, more if it was not enough."""
    if round_number == 0:
        return [Fix(op="remove_blank_lines"), Fix(op="tighten", level=1)]
    return [Fix(op="keep_next_off"), Fix(op="tighten", level=2)]


# --- the judge -------------------------------------------------------------------------------------------------------------------

INSTRUCTIONS = """You are checking the layout of a finished resume. You are shown the pages of the resume as pictures{template_note}.
Report only real defects that a person would notice and be bothered by:
- text that overlaps other text, or is cut off, or sticks out of the page or out of its column
- a section heading left alone at the bottom of a page, with its content on the next page
- a blank page, or a page in the middle that is nearly empty while another page is crammed
- a design that is clearly different from the sample page's (colours, banner, columns)
These are NOT defects, so do not report them: empty space at the bottom of the last page (a short resume is normal); a resume that
is shorter or longer than the sample; small differences in spacing, fonts or line breaks. The pictures were drawn by LibreOffice, which
differs a little from Word, so if the sample page shows the same look (for example a heading close to a banner there too), it is the
drawing program and not a defect.

Measured by a program (these are facts, not guesses):
{measured}

If the layout is right, answer ok with no fixes. If not, say what is wrong and choose fixes ONLY from this list:
- tighten (level 1, 2 or 3): reduce line spacing and font size a little, more, or a lot, across the document
- keep_next_off: stop headings being forced to stay with the next paragraph
- remove_blank_lines: remove blank lines before section headings
- break_before (heading): start the section whose heading is given on a new page
- no_break_before (heading): stop that section starting on a new page
- grow_header (level 1, 2 or 3): make the banner at the top taller, a little, more, or a lot (use it when the content under the banner touches or is hidden by it)
You must never change, add or remove any words: you can only choose formatting changes from the list above."""


def build_prompt(problems: list[str], has_template_image: bool) -> str:
    note = " and, first, the template's own sample page, which shows how it should look" if has_template_image else ""
    return INSTRUCTIONS.format(template_note=note, measured="\n".join(f"- {p}" for p in problems) or "- nothing was found")


def _image(png: bytes) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.b64encode(png).decode("ascii")}}


class LLMLayoutJudge:
    def __init__(self, make_model: ModelFactory):
        self._make_model = make_model

    def __call__(self, images: list[bytes], problems: list[str], template_image: bytes | None) -> Verdict:
        content: list[dict] = [{"type": "text", "text": build_prompt(problems, template_image is not None)}]
        if template_image is not None:
            content += [{"type": "text", "text": "The template's sample page:"}, _image(template_image)]
        for n, png in enumerate(images, 1):
            content += [{"type": "text", "text": f"Page {n} of the finished resume:"}, _image(png)]
        return structured_call(self._make_model(JUDGE_OUTPUT_TOKENS), Verdict, [HumanMessage(content=content)])


# --- the loop --------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Polish:
    docx: bytes
    status: str  # ok, fixed, unfixed, not_checked
    rounds: int = 0
    issues: tuple[str, ...] = ()  # what is still wrong
    notes: tuple[str, ...] = ()


def polish(docx: bytes, render: Renderer, *, judge: Judge | None = None, template_image: bytes | None = None,
           measure_fn=measure, apply=apply_fixes, rounds: int = MAX_ROUNDS) -> Polish:
    """The file with its layout checked and, if needed, fixed. Never raises."""
    try:
        return _polish(docx, render, judge, template_image, measure_fn, apply, rounds)
    except Exception:  # noqa: BLE001 - a check on the layout must never stop a download
        return Polish(docx, "not_checked", notes=("The layout could not be checked.",))


def _look(judge: Judge | None, measured: Measured, template_image: bytes | None, notes: list[str]) -> Verdict | None:
    if judge is None:
        return None
    try:
        return judge(list(measured.images), list(measured.problems), template_image)
    except Exception:  # noqa: BLE001 - the judge is an extra pair of eyes: if it fails, the measuring still decides
        if not any("judge" in n.lower() for n in notes):
            notes.append("The layout judge was not available, so the layout was checked by measurement only.")
        return None


def _right(measured: Measured, verdict: Verdict | None) -> bool:
    return not measured.problems and (verdict is None or verdict.ok)


def _polish(docx, render, judge, template_image, measure_fn, apply, rounds) -> Polish:
    notes: list[str] = []
    pdf = render(docx)
    if pdf is None:
        return Polish(docx, "not_checked", notes=("The layout could not be checked on this server.",))
    current = measure_fn(pdf, docx)
    verdict = _look(judge, current, template_image, notes)
    if _right(current, verdict):
        return Polish(docx, "ok", notes=tuple(notes))
    best, best_measured, changed, used = docx, current, False, 0
    for n in range(rounds):
        fixes = verdict.fixes if verdict is not None and verdict.fixes else default_fixes(list(best_measured.problems), n)
        candidate = apply(best, fixes)
        candidate_pdf = render(candidate) if candidate is not None else None
        if candidate is None or candidate_pdf is None:
            break
        measured = measure_fn(candidate_pdf, candidate)
        candidate_verdict = _look(judge, measured, template_image, notes)
        if len(measured.problems) > len(best_measured.problems):
            break  # worse: keep what we had
        if len(measured.problems) == len(best_measured.problems) and not (candidate_verdict and candidate_verdict.ok):
            break  # no better: keep what we had
        best, best_measured, verdict, changed, used = candidate, measured, candidate_verdict, True, n + 1
        if _right(measured, candidate_verdict):
            break
    if not changed and not best_measured.problems:
        # Only the picture judge complained and nothing it suggested helped. Its pictures come from LibreOffice, which draws a
        # little differently from Word, so on its own it is advice, not proof: the file goes out as it was.
        return Polish(docx, "ok", used, (), (*notes, "The layout judge had a remark that the measuring did not confirm."))
    status = "fixed" if changed and _right(best_measured, verdict) else "unfixed"
    return Polish(best, status, used, best_measured.problems, tuple(notes))


class LayoutPolisher:
    """What the service uses: renders, judges and fixes a finished file, and remembers each answer so the same file (a second
    download) is not judged again. `template_image` turns the template into a picture of its sample page."""

    def __init__(self, render: Renderer, judge: Judge | None = None, *, rounds: int = MAX_ROUNDS, measure_fn=measure,
                 template_image: Callable[[bytes], bytes | None] | None = None):
        self._render, self._judge, self._rounds, self._measure = render, judge, rounds, measure_fn
        self._template_image = template_image or self._first_page
        self._answers: dict[str, Polish] = {}
        self._pictures: dict[str, bytes | None] = {}

    def _first_page(self, template: bytes) -> bytes | None:
        pdf = self._render(template)
        if pdf is None:
            return None
        try:
            images = measure(pdf, template, want_images=1).images
        except Exception:  # noqa: BLE001
            return None
        return images[0] if images else None

    def _picture(self, template: bytes) -> bytes | None:
        key = hashlib.sha256(template).hexdigest()
        if key not in self._pictures:
            try:
                self._pictures[key] = self._template_image(template)
            except Exception:  # noqa: BLE001
                self._pictures[key] = None
        return self._pictures[key]

    def __call__(self, docx: bytes, template: bytes) -> Polish:
        key = hashlib.sha256(docx).hexdigest()
        if key not in self._answers:
            result = polish(docx, self._render, judge=self._judge, template_image=self._picture(template) if self._judge else None,
                            measure_fn=self._measure, rounds=self._rounds)
            if len(self._answers) >= CACHE_SIZE:
                self._answers.pop(next(iter(self._answers)))
            if result.status != "not_checked":  # not caching a failure to check: the next try may work
                self._answers[key] = result
            return result
        return self._answers[key]


__all__ = ["ALLOWED_FIXES", "ExtractionError", "Fix", "LLMLayoutJudge", "LayoutPolisher", "Polish", "Verdict", "apply_fixes",
           "build_prompt", "default_fixes", "polish"]

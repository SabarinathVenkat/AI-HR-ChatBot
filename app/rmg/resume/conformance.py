"""Does the finished resume match the setup template, and is it a good resume file?

Plain code, no model: every check reads the template and the output Word file and compares them. A check passes, warns
(worth a look) or fails (something is wrong). The report only informs; it never blocks a download.

Checks:
  template      the company template was used (not the standard layout)
  sections      the same headings as the template, in the same order, and none of its sections missing or invented
  sample_text   no sample text from the template left in the output
  complete      everything in the resume is in the file, unless the template has no place for it
  empty_sections  no heading with nothing under it
  bullets       the template's own bullets, not a different kind
  bold          bold only where the template uses bold for key words
  fonts         only the fonts and sizes the template uses
  format        the template's page size, margins, columns, alignment and indents
  pages         within the page limit, and no nearly empty last page
  breaks        no typed page breaks, runs of blank lines or trailing blank lines
"""
import io
import re
from dataclasses import dataclass

from docx import Document

from app.rmg.resume.fidelity import format_differences
from app.rmg.resume.fit import LAST_PAGE_MIN_FILL, MAX_PAGES, estimate_pages
from app.rmg.resume.model import Resume
from app.rmg.resume.template import (
    W, TemplateMap, analyse, classify_heading, has_emphasis, is_blank, is_bullet, is_heading, paragraph_style, paragraph_text, typed_glyph,
)

PASS, WARN, FAIL = "pass", "warn", "fail"
MIN_SAMPLE_CHARS = 8
MIN_SENTENCE_CHARS = 60  # a paragraph this long that is unchanged in the output is probably sample text
SHOWN = 4  # how many items a message lists before saying "and more"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    message: str


@dataclass(frozen=True)
class Report:
    checks: tuple[Check, ...]

    @property
    def status(self) -> str:
        statuses = {c.status for c in self.checks}
        return FAIL if FAIL in statuses else WARN if WARN in statuses else PASS

    @property
    def summary(self) -> str:
        problems = [c for c in self.checks if c.status != PASS]
        if not problems:
            return "The resume matches the template."
        return f"{len(problems)} of {len(self.checks)} checks need attention: " + ", ".join(c.name for c in problems) + "."

    def to_dict(self) -> dict:
        return {"status": self.status, "summary": self.summary,
                "checks": [{"name": c.name, "status": c.status, "message": c.message} for c in self.checks]}


# --- helpers --------------------------------------------------------------------------------------------------------

_GLYPH = re.compile(r"^\s*[•●▪◦‣·–*-]\s+")


def _norm(text: str) -> str:
    return " ".join(_GLYPH.sub("", text or "").split()).casefold()


def _listed(items: list[str]) -> str:
    shown = ", ".join(f'"{i}"' for i in items[:SHOWN])
    return shown + (f" and {len(items) - SHOWN} more" if len(items) > SHOWN else "")


def _paragraphs(doc) -> list:
    return list(doc.element.body.iter(W + "p"))


def _slots(m: TemplateMap) -> list[tuple[str, object]]:
    return [(kind, slot) for kind, slot in (("skills", m.skills), ("education", m.education), ("certifications", m.certifications),
                                             ("highlights", m.highlights), ("projects", m.projects)) if slot is not None]


def _slot_headings(doc, m: TemplateMap) -> list[tuple[str, str]]:
    """(kind, heading text) of the template's known sections, in the order they sit in the document."""
    order = {id(p): n for n, p in enumerate(_paragraphs(doc))}
    found = [(order[id(slot.heading)], kind, paragraph_text(slot.heading).strip()) for kind, slot in _slots(m) if id(slot.heading) in order]
    return [(kind, text) for _, kind, text in sorted(found)]


def _heading_elements(doc, m: TemplateMap) -> list:
    """Every heading: the template's known sections, and any paragraph with a Heading style, in document order."""
    wanted = {id(slot.heading) for _, slot in _slots(m)}
    return [p for p in _paragraphs(doc) if id(p) in wanted or (paragraph_style(p).lower().startswith("heading") and is_heading(p))]


def _resume_strings(resume: Resume) -> set[str]:
    texts = [resume.name]
    texts += [i.text for _, i in resume.all_items()]
    for group in resume.skill_groups:
        texts += [group.category, ", ".join(i.text for i in group.items), f"{group.category}: "]
    for e in resume.education:
        texts += [e.degree or "", e.institution or "", e.year or ""]
    texts += [p.name for p in resume.projects]
    return {_norm(t) for t in texts if t}


def _sample_texts(m: TemplateMap) -> list[str]:
    elements = [m.name, m.role, m.summary]
    if m.skills:
        elements += m.skills.region
    for slot in (m.education, m.certifications, m.highlights):
        if slot is not None:
            elements += slot.region
    if m.projects:
        for block in m.projects.blocks:
            elements += [block.name, block.desc, *block.bullets]
    return [t for t in (paragraph_text(e).strip() for e in elements if e is not None) if len(t) >= MIN_SAMPLE_CHARS]


# --- the checks -----------------------------------------------------------------------------------------------------

def _template_check(used_standard_layout: bool) -> Check:
    if used_standard_layout:
        return Check("template", WARN, "The company template could not be used, so the standard layout was used instead.")
    return Check("template", PASS, "The company template was used.")


def _sections_check(tdoc, tmap, odoc, omap, resume: Resume) -> Check:
    wanted = _slot_headings(tdoc, tmap)
    template_texts = [text for _, text in wanted]
    known = {paragraph_text(p).strip() for p in _heading_elements(tdoc, tmap)}
    added_certifications = tmap.certifications is None  # such a template is given a certifications section when the resume has some
    invented = [paragraph_text(p).strip() for p in _heading_elements(odoc, omap) if paragraph_text(p).strip() not in known
                and not (added_certifications and classify_heading(paragraph_text(p)) == "certifications")]
    if invented:
        return Check("sections", FAIL, f"Headings that are not in the template: {_listed(invented)}.")
    in_output: list[str] = []  # the template's section headings, in the order they appear in the output
    for p in _paragraphs(odoc):
        text = paragraph_text(p).strip()
        if text in template_texts and text not in in_output:
            in_output.append(text)
    has = {"skills": bool(resume.skill_groups), "education": bool(resume.education), "certifications": bool(resume.certifications),
           "highlights": bool(resume.highlights or resume.jobs), "projects": bool(resume.projects)}
    missing = [text for kind, text in wanted if has[kind] and text not in in_output]
    if missing:
        return Check("sections", FAIL, f"Sections missing from the file: {_listed(missing)}.")
    if in_output != [text for text in template_texts if text in in_output]:
        return Check("sections", FAIL, "The sections are not in the template's order.")
    return Check("sections", PASS, f"All {len(in_output)} sections are there, in the template's order.")


def _sample_check(tdoc, tmap, odoc, resume: Resume) -> Check:
    output = [_norm(paragraph_text(p)) for p in _paragraphs(odoc)]
    present = set(output)
    own = _resume_strings(resume)
    mapped = _sample_texts(tmap)
    left = [t for t in mapped if _norm(t) in present and _norm(t) not in own]
    if left:
        return Check("sample_text", FAIL, f"Sample text from the template is still in the file: {_listed(left)}.")
    # Text the reader did not map to any part of the resume, such as a second banner sentence, may be sample text too.
    mapped_norm = {_norm(t) for t in mapped}
    unmapped = []
    for p in _paragraphs(tdoc):
        text = paragraph_text(p).strip()
        key = _norm(text)
        if len(text) >= MIN_SENTENCE_CHARS and not is_heading(p) and key not in mapped_norm and key in present and key not in own:
            unmapped.append(text)
    if unmapped:
        return Check("sample_text", WARN, f"Text from the template is unchanged in the file and may be sample text: {_listed(unmapped)}.")
    return Check("sample_text", PASS, "No sample text from the template is left.")


def _complete_check(tmap, odoc, resume: Resume) -> Check:
    text = _norm(" ".join(paragraph_text(p) for p in _paragraphs(odoc)))
    expected = [resume.name, resume.role_title.text if resume.role_title else "", resume.summary.text if resume.summary else ""]
    for group in resume.skill_groups:
        expected += [group.category, *(i.text for i in group.items)]
    expected += [h.text for h in resume.highlights]
    if tmap.education is not None:
        for e in resume.education:
            expected += [e.degree or "", e.institution or ""]
    expected += [c.text for c in resume.certifications]  # a template with no such section is given one
    for project in resume.projects:
        expected.append(project.name)
        if project.description and tmap.projects is not None and tmap.projects.proto_desc is not None:
            expected.append(project.description.text)
        expected += [b.text for b in project.bullets]
    missing = [e for e in expected if e and _norm(e) not in text]
    if missing:
        return Check("complete", FAIL, f"Parts of the resume are missing from the file: {_listed(missing)}.")
    return Check("complete", PASS, "Everything in the resume is in the file.")


def _empty_sections_check(odoc, omap, known: set[str]) -> Check:
    """A heading is empty if, before the next known section or the end, there is no text except sub-headings."""
    headings = _heading_elements(odoc, omap)
    ids = {id(h) for h in headings}
    empty = []
    for heading in headings:
        if paragraph_text(heading).strip() not in known and paragraph_style(heading).lower().startswith("heading") is False:
            continue
        has_content, following = False, heading.getnext()
        while following is not None and following.tag != W + "sectPr":
            if following.tag == W + "p":
                text = paragraph_text(following).strip()
                if text in known:  # the next section begins
                    break
                if text and id(following) not in ids:
                    has_content = True
                    break
            elif following.tag == W + "tbl":
                has_content = True
                break
            following = following.getnext()
        if not has_content:
            empty.append(paragraph_text(heading).strip())
    if empty:
        return Check("empty_sections", FAIL, f"Headings with nothing under them: {_listed(empty)}.")
    return Check("empty_sections", PASS, "No heading is left empty.")


def _bullet_ids(doc) -> tuple[set[str], set[str]]:
    numbers, glyphs = set(), set()
    for p in _paragraphs(doc):
        if not is_bullet(p):
            continue
        number = p.find(f"{W}pPr/{W}numPr/{W}numId")
        if number is not None:
            numbers.add(number.get(W + "val"))
        elif (glyph := typed_glyph(p)) is not None:
            glyphs.add(glyph)
    return numbers, glyphs


def _bullets_check(tdoc, odoc) -> Check:
    t_numbers, t_glyphs = _bullet_ids(tdoc)
    o_numbers, o_glyphs = _bullet_ids(odoc)
    other = (o_numbers - t_numbers) if t_numbers else set()
    other_glyphs = (o_glyphs - t_glyphs) if t_glyphs else set()
    if other or other_glyphs:
        return Check("bullets", WARN, "Some bullets are not the template's own bullet style.")
    return Check("bullets", PASS, "Bullets use the template's style.")


def _bold_check(tmap, omap) -> Check:
    problems = []
    kinds = []
    if tmap.highlights is not None and omap.highlights is not None:
        kinds.append(("highlights", tmap.highlights.emphasis, omap.highlights.region))
    if tmap.projects is not None and omap.projects is not None:
        kinds.append(("project bullets", tmap.projects.emphasis, [b for block in omap.projects.blocks for b in block.bullets]))
        kinds.append(("project descriptions", tmap.projects.desc_emphasis, [b.desc for b in omap.projects.blocks if b.desc is not None]))
    for name, allowed, paragraphs in kinds:
        if not allowed and any(has_emphasis([p]) for p in paragraphs):
            problems.append(name)
    if problems:
        return Check("bold", FAIL, f"Words are in bold in {_listed(problems)}, where the template has no bold.")
    return Check("bold", PASS, "Bold is used only where the template uses it.")


def _fonts_and_sizes(doc) -> tuple[set[str], set[int]]:
    fonts, sizes = set(), set()
    for run in doc.element.body.iter(W + "r"):
        font = run.find(f"{W}rPr/{W}rFonts")
        if font is not None and font.get(W + "ascii"):
            fonts.add(font.get(W + "ascii"))
        size = run.find(f"{W}rPr/{W}sz")
        if size is not None and (size.get(W + "val") or "").isdigit():
            sizes.add(int(size.get(W + "val")))
    return fonts, sizes


def _fonts_check(tdoc, odoc) -> Check:
    t_fonts, t_sizes = _fonts_and_sizes(tdoc)
    o_fonts, o_sizes = _fonts_and_sizes(odoc)
    odd_fonts = sorted(o_fonts - t_fonts) if t_fonts else []
    odd_sizes = []
    if t_sizes:
        low, high = min(min(t_sizes), 18), max(t_sizes)  # the fit step may shrink text, but never below 9pt (18 half-points)
        odd_sizes = sorted(s / 2 for s in o_sizes if s < low or s > high)
    if odd_fonts or odd_sizes:
        parts = ([f"fonts {_listed(odd_fonts)}"] if odd_fonts else []) + ([f"sizes {', '.join(f'{s:g}pt' for s in odd_sizes)}"] if odd_sizes else [])
        return Check("fonts", WARN, "The file uses " + " and ".join(parts) + ", which the template does not.")
    return Check("fonts", PASS, "Fonts and sizes are the template's.")


def _format_check(tdoc, odoc) -> Check:
    differences = format_differences(tdoc, odoc)
    if differences:
        return Check("format", WARN, "The file's format differs from the template: " + _listed(differences) + ".")
    return Check("format", PASS, "Page setup, alignment and indents are the template's.")


def _pages_check(odoc) -> Check:
    estimate = estimate_pages(odoc)
    if estimate.pages > MAX_PAGES:
        return Check("pages", WARN, f"The resume will run to about {estimate.pages} pages; the limit is {MAX_PAGES}.")
    if estimate.pages > 1 and estimate.last_fill < LAST_PAGE_MIN_FILL and not estimate.forced_start:
        return Check("pages", WARN, "The last page is almost empty (estimated).")
    return Check("pages", PASS, f"About {estimate.pages} page{'s' if estimate.pages != 1 else ''}.")


def _breaks_check(odoc) -> Check:
    body = odoc.element.body
    typed = sum(1 for br in body.iter(W + "br") if br.get(W + "type") == "page")
    runs_of_blanks = 0
    for parent in {p.getparent() for p in _paragraphs(odoc)}:
        previous = False
        for child in parent:
            blank = child.tag == W + "p" and is_blank(child) and child.find(f".//{W}sectPr") is None
            runs_of_blanks += blank and previous
            previous = blank
    children = [c for c in body if c.tag != W + "sectPr"]
    trailing = bool(children) and children[-1].tag == W + "p" and is_blank(children[-1])
    if typed or runs_of_blanks or trailing:
        found = [x for x, ok in (("typed page breaks", typed), ("runs of blank lines", runs_of_blanks), ("blank lines at the end", trailing)) if ok]
        return Check("breaks", WARN, "The file has " + ", ".join(found) + ".")
    return Check("breaks", PASS, "No stray breaks or blank lines.")


# --- entry point ---------------------------------------------------------------------------------------------------------

def check_conformance(template: bytes, output: bytes, resume: Resume, *, used_standard_layout: bool = False) -> Report:
    """Compare the finished file with the template it was made from. If the standard layout was used, `template` is
    still the company's file, and the standard layout is what the output is compared with."""
    if used_standard_layout:
        from app.rmg.resume.demo_template import make_demo_template  # only needed on this path

        template = make_demo_template()
    tdoc, odoc = Document(io.BytesIO(template)), Document(io.BytesIO(output))
    tmap, omap = analyse(tdoc), analyse(odoc)
    return Report(checks=(
        _template_check(used_standard_layout),
        _sections_check(tdoc, tmap, odoc, omap, resume),
        _sample_check(tdoc, tmap, odoc, resume),
        _complete_check(tmap, odoc, resume),
        _empty_sections_check(odoc, omap, {text for _, text in _slot_headings(tdoc, tmap)}),
        _bullets_check(tdoc, odoc),
        _bold_check(tmap, omap),
        _fonts_check(tdoc, odoc),
        _format_check(tdoc, odoc),
        _pages_check(odoc),
        _breaks_check(odoc),
    ))

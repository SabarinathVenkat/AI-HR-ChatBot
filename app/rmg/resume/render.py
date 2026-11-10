"""Render a Resume into a template by cloning the template's own paragraphs.

Nothing is edited in place and no formatting is built from scratch: every new line is a copy of a prototype paragraph
the analyser found, with its text replaced, so fonts, spacing, bullets and colours come from the template. Each section
is rebuilt from prototypes (editing text in place mixes up labels and values in documents exported from Google Docs).

Resume text is untrusted, so it is written exactly as it is: characters such as ** are never turned into formatting,
and control characters that would corrupt the file are removed.

Content the template has no place for is reported in `problems` and never silently lost. A template whose required
slots cannot be found is refused (TemplateError) with the list of what is missing.
"""
import copy
import io
import re
from dataclasses import dataclass

from docx import Document
from docx.oxml import OxmlElement
from docx.shared import RGBColor

from app.rmg.resume.model import Resume
from app.rmg.resume.template import W, TemplateMap, all_bold, analyse, is_blank, is_heading, run_is_bold, text_runs

DRAFT_TEXT = "DRAFT - pending approval"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

TEMPLATE_MESSAGES = {"unreadable": "That template could not be read."}


class TemplateError(Exception):
    def __init__(self, code: str, missing: tuple[str, ...] = ()):
        self.code, self.missing = code, tuple(missing)
        super().__init__(TEMPLATE_MESSAGES.get(code) or f"The template is missing: {', '.join(missing)}.")


@dataclass(frozen=True)
class RenderResult:
    docx: bytes
    problems: tuple[str, ...]  # content the template could not hold


# --- cloning ----------------------------------------------------------------------------------------

def _clean(text: str) -> str:
    return _CONTROL.sub("", text)


def _run_properties(p):
    """(regular, bold) run properties taken from a prototype paragraph, derived from each other when one is missing."""
    regular = bold = None
    for r in text_runs(p):
        rpr = r.find(W + "rPr")
        if run_is_bold(r) and bold is None:
            bold = copy.deepcopy(rpr)
        elif not run_is_bold(r) and regular is None and rpr is not None:
            regular = copy.deepcopy(rpr)
    if regular is None and bold is not None:
        regular = copy.deepcopy(bold)
        for tag in ("b", "bCs"):
            for e in regular.findall(W + tag):
                regular.remove(e)
    if bold is None:
        bold = copy.deepcopy(regular) if regular is not None else OxmlElement("w:rPr")
        bold.insert(0, OxmlElement("w:b"))
    return regular, bold


def _fill(p, segments: list[tuple[str, bool]]) -> None:
    """Replace the runs of a paragraph with new text, keeping its paragraph properties and the prototype's run formatting."""
    regular, bold = _run_properties(p)
    keep_bold = all_bold(p)  # a prototype that is bold throughout (a project name) stays bold
    for child in list(p):
        if child.tag != W + "pPr":
            p.remove(child)
    for text, is_bold in segments:
        run = OxmlElement("w:r")
        rpr = copy.deepcopy(bold if (is_bold or keep_bold) else regular)
        if rpr is not None:
            run.append(rpr)
        t = OxmlElement("w:t")
        t.set(_SPACE, "preserve")
        t.text = _clean(text)
        run.append(t)
        p.append(run)


def _clone(proto, segments: list[tuple[str, bool]]):
    p = copy.deepcopy(proto)
    _fill(p, segments)
    return p


def _blank_like(proto):
    p = copy.deepcopy(proto)
    for child in list(p):
        if child.tag != W + "pPr":
            p.remove(child)
    ppr = p.find(W + "pPr")
    if ppr is not None:
        for e in ppr.findall(W + "numPr"):
            ppr.remove(e)
    return p


def _replace(old: list, new: list) -> None:
    """Take out `old` elements and put `new` where the first of them was."""
    if not old:
        return
    parent = old[0].getparent()
    index = parent.index(old[0])
    for e in old:
        e.getparent().remove(e)
    for offset, e in enumerate(new):
        parent.insert(index + offset, e)


def _set_run_text(run, text: str) -> None:
    ts = list(run.iter(W + "t"))
    ts[0].text = _clean(text)
    ts[0].set(_SPACE, "preserve")
    for extra in ts[1:]:
        extra.getparent().remove(extra)


# --- sections ---------------------------------------------------------------------------------------

def _render_header(m: TemplateMap, resume: Resume, years_text: str) -> None:
    _fill(m.name, [(resume.name, False)])
    title = resume.role_title.text if resume.role_title else ""
    if m.role is not None:
        runs = text_runs(m.role)
        if len(runs) >= 2 and title and years_text:  # the template styles the title and the years differently
            _set_run_text(runs[0], title + " ")
            _set_run_text(runs[1], years_text)
            for extra in runs[2:]:
                extra.getparent().remove(extra)
        else:
            _fill(m.role, [(f"{title} {years_text}".strip(), False)])
    _fill(m.summary, [(resume.summary.text if resume.summary else "", False)])


def _render_skills(m: TemplateMap, resume: Resume) -> None:
    new = []
    for group in resume.skill_groups:
        new.append(_clone(m.skills.proto_label, [(group.category, True), (": ", False)]))
        new.append(_clone(m.skills.proto_value, [(", ".join(i.text for i in group.items), False)]))
    _replace(m.skills.region, new)


def _render_list(slot, entries: list[list[tuple[str, bool]]]) -> None:
    _replace(slot.region, [_clone(slot.proto, segments) for segments in entries])


def _project_span(slot) -> list:
    """Every element from the first project name to the last bullet, plus the blank lines right after it."""
    first, last = slot.blocks[0].name, (slot.blocks[-1].bullets or [slot.blocks[-1].name])[-1]
    span, element = [], first
    while element is not None:
        span.append(element)
        if element is last:
            break
        element = element.getnext()
    element = last.getnext()
    while element is not None and element.tag == W + "p" and is_blank(element) and not is_heading(element):
        span.append(element)
        element = element.getnext()
    return span


def _render_projects(m: TemplateMap, resume: Resume) -> list[str]:
    slot, new, problems = m.projects, [], []
    for project in resume.projects:
        new.append(_clone(slot.proto_name, [(project.name, False)]))
        if project.description is not None:
            if slot.proto_desc is not None:
                new.append(_clone(slot.proto_desc, [(project.description.text, False)]))
            else:
                problems.append("project descriptions: the template has no place for them, so they were not included")
        count = len(project.bullets)
        for i, bullet in enumerate(project.bullets):
            proto = slot.proto_first if i == 0 else slot.proto_last if i == count - 1 else slot.proto_mid
            new.append(_clone(proto, [(bullet.text, False)]))
        new.append(_blank_like(slot.proto_blank if slot.proto_blank is not None else slot.proto_name))
    _replace(_project_span(slot), new)
    _keep_with_next(slot.heading)
    return list(dict.fromkeys(problems))


def _keep_with_next(p) -> None:
    """A heading must not be left alone at the bottom of a page."""
    ppr = p.find(W + "pPr")
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        p.insert(0, ppr)
    if ppr.find(W + "keepNext") is None:
        position = 1 if ppr.find(W + "pStyle") is not None else 0  # schema order: pStyle, then keepNext
        ppr.insert(position, OxmlElement("w:keepNext"))


def _mark_draft(doc) -> None:
    for number, section in enumerate(doc.sections):
        headers = [section.header]
        if section.different_first_page_header_footer:
            headers.append(section.first_page_header)
        for header in headers:
            if header.is_linked_to_previous:
                if number > 0:
                    continue  # it shows the first section's header already
                header.is_linked_to_previous = False
            paragraph = header.paragraphs[0].insert_paragraph_before()
            run = paragraph.add_run(DRAFT_TEXT)
            run.bold = True
            run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)


# --- entry point ------------------------------------------------------------------------------------

def _load(template: bytes):
    try:
        doc = Document(io.BytesIO(template))
        m = analyse(doc)
    except Exception:
        raise TemplateError("unreadable") from None
    if missing := m.missing():
        raise TemplateError("incomplete", tuple(missing))
    return doc, m


def check_template(template: bytes) -> None:
    """Raise TemplateError if the template cannot be rendered into. Cheap, so it can run before anything costly."""
    _load(template)


def render_resume(template: bytes, resume: Resume, *, years_text: str = "", draft: bool = False) -> RenderResult:
    doc, m = _load(template)
    problems: list[str] = []
    _render_header(m, resume, years_text)
    _render_skills(m, resume)
    for name, slot, entries in (
        ("education", m.education, [[(e.degree, True), (f" {e.institution} {e.year or ''}".rstrip(), False)] for e in resume.education]),
        ("certifications", m.certifications, [[(c, False)] for c in resume.certifications]),
    ):
        if slot is not None:
            _render_list(slot, entries)
        elif entries:
            problems.append(f"{name}: the template has no such section, so they were not included")
    _render_list(m.highlights, [[(h.text, False)] for h in resume.highlights])
    problems += _render_projects(m, resume)
    if draft:
        _mark_draft(doc)

    out = io.BytesIO()
    doc.save(out)
    return RenderResult(docx=out.getvalue(), problems=tuple(problems))

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

from app.rmg.resume.emphasis import emphasise, terms_of
from app.rmg.resume.fit import MAX_PAGES, capacity, compact_document, fit
from app.rmg.resume.model import Resume
from app.rmg.resume.repair import repair_layout
from app.rmg.resume.template import (
    W, TemplateMap, all_bold, analyse, is_blank, is_heading, run_is_bold, text_runs, typed_glyph,
)

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
    used_standard_layout: bool = False  # the company template could not be used


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
    allows_bold = any(run_is_bold(r) for r in text_runs(p))  # a prototype with no bold anywhere gets no bold: that is the template's style
    glyph = typed_glyph(p)  # a bullet the template typed by hand is typed again
    if glyph and segments:
        segments = [(f"{glyph} {segments[0][0]}", segments[0][1]), *segments[1:]]
    for child in list(p):
        if child.tag != W + "pPr":
            p.remove(child)
    for text, is_bold in segments:
        run = OxmlElement("w:r")
        rpr = copy.deepcopy(bold if ((is_bold and allows_bold) or keep_bold) else regular)
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

MAX_ROLE_LINE_CHARS = 46  # beyond this the role line wraps onto the summary in the template's banner


def shorten_years(text: str) -> str:
    """"10 years 3 months" -> "10 yrs": the years only, shortened. Months alone are left as they are."""
    match = re.match(r"^(\d+) years?\b", text.strip())
    if not match:
        return text
    years = int(match.group(1))
    return f"{years} {'yr' if years == 1 else 'yrs'}"


def _render_header(m: TemplateMap, resume: Resume, years_text: str) -> None:
    _fill(m.name, [(resume.name, False)])
    title = resume.role_title.text if resume.role_title else ""
    if len(f"{title} {years_text}") > MAX_ROLE_LINE_CHARS:
        years_text = shorten_years(years_text)
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


def _render_skills(m: TemplateMap, resume: Resume) -> list:
    new = []
    for group in resume.skill_groups:
        new.append(_clone(m.skills.proto_label, [(group.category, True), (": ", False)]))
        new.append(_clone(m.skills.proto_value, [(", ".join(i.text for i in group.items), False)]))
    _replace(m.skills.region, new)
    return new


def _entry_span(region: list) -> list:
    """Every element from the first entry to the last, including the blank spacers the template keeps between them."""
    span, element = [], region[0]
    while element is not None:
        span.append(element)
        if element is region[-1]:
            break
        element = element.getnext()
    return span


def _render_list(slot, entries: list[list[tuple[str, bool]]]) -> list:
    """Replace a list section's entries with new ones cloned from its prototype. Returns the new elements."""
    new = []
    for number, segments in enumerate(entries):
        if number and slot.separator is not None:
            new.append(copy.deepcopy(slot.separator))  # the template's own spacing between entries
        new.append(_clone(slot.proto, segments))
    _replace(_entry_span(slot.region) if slot.separator is not None else slot.region, new)
    return new


def _drop(elements) -> None:
    for element in elements:
        if element is not None and element.getparent() is not None:
            element.getparent().remove(element)


def _drop_section(heading, body: list, extra=()) -> None:
    """A section with nothing to show goes completely: a heading with nothing under it looks like a mistake."""
    _drop([heading, *body, *extra])


def _job_line(job) -> str:
    """"Senior Data Scientist, Ideas2IT (May 2025 – Present)"; whatever part is missing is simply left out."""
    text = ", ".join(part for part in (job.title, job.company) if part)
    if job.start and job.end:
        return f"{text} ({job.start} \u2013 {job.end})"
    return f"{text} (from {job.start})" if job.start else text


def _render_work_history(slot, jobs: list, anchor) -> None:
    """Under the highlights: a subheading and one bullet per job, cloned from the template's own subheading and bullet."""
    new = [copy.deepcopy(slot.separator) if slot.separator is not None else _blank_like(slot.subheading),
           _clone(slot.subheading, [("Work history", False)])]
    for number, job in enumerate(jobs):
        if number and slot.separator is not None:
            new.append(copy.deepcopy(slot.separator))
        new.append(_clone(slot.proto, [(_job_line(job), False)]))
    for element in new:
        anchor.addnext(element)
        anchor = element


def template_gaps(template: bytes, resume: Resume) -> list[str]:
    """In plain words, what this resume has that the template has no place for. Cheap: it only reads the template."""
    _, m = _load(template)
    gaps = []
    if resume.certifications and m.certifications is None:
        gaps.append("Certifications are not in the Word file: the template has no place for them.")
    if resume.education and m.education is None:
        gaps.append("Education is not in the Word file: the template has no place for it.")
    if resume.jobs and not resume.highlights and m.highlights.subheading is None:
        gaps.append("Work history is not in the Word file: the template has no place for it.")
    if any(p.description for p in resume.projects) and m.projects.proto_desc is None:
        gaps.append("Project descriptions are not in the Word file: the template has no place for them.")
    return gaps


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
    terms = terms_of(resume)
    if not resume.projects:
        _drop([*_project_span(slot), slot.heading])
        return []
    for project in resume.projects:
        new.append(_clone(slot.proto_name, [(project.name, False)]))
        if project.description is not None:
            if slot.proto_desc is not None:
                new.append(_clone(slot.proto_desc, emphasise(project.description.text, terms) if slot.desc_emphasis else [(project.description.text, False)]))
            else:
                problems.append("project descriptions: the template has no place for them, so they were not included")
        count = len(project.bullets)
        for i, bullet in enumerate(project.bullets):
            proto = slot.proto_first if i == 0 else slot.proto_last if i == count - 1 else slot.proto_mid
            new.append(_clone(proto, emphasise(bullet.text, terms) if slot.emphasis else [(bullet.text, False)]))
        new.append(_blank_like(slot.proto_blank if slot.proto_blank is not None else slot.proto_name))
    _replace(_project_span(slot), new)
    _remove_spacers_before(slot.heading)
    _start_on_new_page(slot.heading)
    return list(dict.fromkeys(problems))


_PPR_ORDER = ["pStyle", "keepNext", "keepLines", "pageBreakBefore"]  # the order Word requires inside w:pPr


def _ensure_ppr_child(ppr, name: str) -> None:
    if ppr.find(W + name) is not None:
        return
    earlier = _PPR_ORDER[:_PPR_ORDER.index(name)]
    position = 0
    for index, child in enumerate(ppr):
        if child.tag.split("}")[1] in earlier:
            position = index + 1
    ppr.insert(position, OxmlElement(f"w:{name}"))


def _start_on_new_page(heading) -> None:
    """Page 1 of the template is a fixed block (banner, sidebar, highlights); the projects belong on the pages after it.
    Left to flow, a short first page lets the projects start at the bottom of page 1, on top of the sidebar."""
    ppr = heading.find(W + "pPr")
    if ppr is None:
        ppr = OxmlElement("w:pPr")
        heading.insert(0, ppr)
    _ensure_ppr_child(ppr, "keepNext")
    if heading.getparent().tag != W + "tc":  # a page break inside a table cell moves the whole table row, leaving a blank page
        _ensure_ppr_child(ppr, "pageBreakBefore")


def _remove_spacers_before(heading) -> None:
    """Blank lines right before the heading only pushed it down the page; with a page break they would risk a blank page."""
    previous = heading.getprevious()
    while previous is not None and previous.tag == W + "p" and is_blank(previous):
        heading.getparent().remove(previous)
        previous = heading.getprevious()


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


def _education_line(e) -> list[tuple[str, bool]]:
    """The first part (the degree, or the institution if there is no degree) in bold, the rest in the regular style."""
    first = e.degree or e.institution
    rest = " ".join(part for part in ([e.institution] if e.degree else []) + [e.year or ""] if part)
    return [(first, True)] + ([(" " + rest, False)] if rest else [])


def render_resume(template: bytes, resume: Resume, *, years_text: str = "") -> RenderResult:
    doc, m = _load(template)
    problems: list[str] = []
    _render_header(m, resume, years_text)
    sample = list(m.skills.region)
    for slot in (m.education, m.certifications):
        sample += list(slot.region) if slot is not None else []
    column = _render_skills(m, resume)
    if not resume.skill_groups:
        _drop_section(m.skills.heading, [])
    for name, slot, entries in (
        ("education", m.education, [_education_line(e) for e in resume.education]),
        ("certifications", m.certifications, [[(c, False)] for c in resume.certifications]),
    ):
        if slot is not None:
            column += _render_list(slot, entries)
            if not entries:
                _drop_section(slot.heading, [])
        elif entries:
            problems.append(f"{name}: the template has no such section, so they were not included")
    if not fit(column, capacity(sample, doc), doc):
        problems.append("skills: the list is long for the side column of this template, so part of it may run onto the next page")
    terms = terms_of(resume)
    new_highlights = _render_list(m.highlights, [emphasise(h.text, terms) if m.highlights.emphasis else [(h.text, False)]
                                                 for h in resume.highlights])
    if resume.jobs and not new_highlights:  # the Experience section holds key highlights; a job list only fills in when there are none
        if m.highlights.subheading is not None:
            _render_work_history(m.highlights, resume.jobs, m.highlights.subheading)
        else:
            problems.append("work history: the template has no place for it, so it was not included")
    if not new_highlights and not (resume.jobs and m.highlights.subheading is not None):
        _drop_section(m.highlights.heading, [], [m.highlights.subheading])
    problems += _render_projects(m, resume)
    repair_layout(doc)
    pages = compact_document(doc).pages
    if pages > MAX_PAGES:
        problems.append(f"the resume is long: it will run to about {pages} pages, and {MAX_PAGES} is the limit, so some of it should be shortened")

    out = io.BytesIO()
    doc.save(out)
    return RenderResult(docx=out.getvalue(), problems=tuple(problems))


def render_best(template: bytes, resume: Resume, *, years_text: str = "") -> RenderResult:
    """Always produce a resume. If the template cannot be used (it has no recognisable sections, or is damaged), the
    standard layout is used instead and the result says so, so a mistake in a template never blocks an associate."""
    try:
        return render_resume(template, resume, years_text=years_text)
    except TemplateError as e:
        from app.rmg.resume.demo_template import make_demo_template  # imported here: it is only needed on this path

        standard = render_resume(make_demo_template(), resume, years_text=years_text)
        reason = f"it is missing {', '.join(e.missing)}" if e.missing else "it could not be read"
        return RenderResult(docx=standard.docx, used_standard_layout=True, problems=(
            f"The company template could not be used ({reason}), so the standard layout was used instead.", *standard.problems))


def template_warning(template: bytes) -> str | None:
    """A sentence for the person uploading a template if resumes made from it will use the standard layout, else None."""
    try:
        check_template(template)
    except TemplateError as e:
        reason = f"it is missing {', '.join(e.missing)}" if e.missing else "it could not be read"
        return f"This template will not be used as it is ({reason}); resumes will use the standard layout instead."
    return None

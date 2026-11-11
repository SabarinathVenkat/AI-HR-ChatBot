"""Read the structure of a resume template (.docx) so a renderer can rebuild it.

The analyser finds where each slot lives (name, role line, summary, skills, education, certifications, highlights,
projects) and keeps one prototype paragraph for each kind of line, so new content can be made by cloning the
template's own formatting instead of building formatting from scratch. The map holds live elements of one specific
document, so it belongs to that file and is thrown away with it.

It only reads. If the template is unusual (no Title-style header, bullets typed as a character) a slot is reported as
missing by `missing()` rather than guessed, so a template that cannot be rendered is found when it is uploaded.
"""
import re
from dataclasses import dataclass, field

from docx.document import Document as DocxDocument

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

SECTION_WORDS = {
    "skills": r"skill|technolog|expertise|competenc|tech stack",
    "education": r"education|qualification|academic",
    "highlights": r"experience|summary|highlight|profile",
    "projects": r"project",
    "certifications": r"certif|training|award",
}
MAX_HEADING_CHARS = 40
MAX_PROJECT_NAME_CHARS = 90
SUMMARY_MIN_CHARS = 120


# --- small helpers on paragraph elements -----------------------------------------------------------

def paragraph_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(W + "t"))


def is_blank(p) -> bool:
    return not paragraph_text(p).strip() and p.find(f".//{W}drawing") is None


def paragraph_style(p) -> str:
    e = p.find(f"{W}pPr/{W}pStyle")
    return e.get(W + "val") if e is not None else ""


def has_numbering(p) -> bool:
    return p.find(f"{W}pPr/{W}numPr") is not None


def run_is_bold(r) -> bool:
    b = r.find(f"{W}rPr/{W}b")
    return b is not None and b.get(W + "val") not in ("0", "false")


def text_runs(p):
    return [r for r in p.iter(W + "r") if "".join(t.text or "" for t in r.iter(W + "t"))]


def all_bold(p) -> bool:
    runs = text_runs(p)
    return bool(runs) and all(run_is_bold(r) for r in runs)


def first_run_bold(p) -> bool:
    runs = text_runs(p)
    return bool(runs) and run_is_bold(runs[0])


def is_heading(p) -> bool:
    text = paragraph_text(p).strip()
    if not text:
        return False
    if paragraph_style(p).lower().startswith("heading") and len(text) < MAX_HEADING_CHARS:
        return True
    return text.isupper() and len(text.split()) <= 3 and len(text) < 30


def classify_heading(text: str) -> str:
    for name, pattern in SECTION_WORDS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return name
    return "unknown"


# --- the map ----------------------------------------------------------------------------------------

@dataclass(eq=False)
class SkillsSlot:
    heading: object
    region: list  # every non-blank paragraph of the section
    proto_label: object | None  # a paragraph that starts bold: the label line, such as "Backend:"
    proto_value: object | None  # the paragraph after it: the values


@dataclass(eq=False)
class ListSlot:
    heading: object
    region: list
    proto: object  # the first entry, cloned for every new entry
    separator: object | None = None  # a blank line the template keeps between entries, if it does


@dataclass(eq=False)
class Block:
    name: object
    desc: object | None
    bullets: list


@dataclass(eq=False)
class ProjectsSlot:
    heading: object
    blocks: list[Block]
    proto_name: object
    proto_desc: object | None
    proto_first: object  # first, middle and last bullets are separate prototypes: their spacing differs
    proto_mid: object
    proto_last: object
    proto_blank: object | None  # the separator between projects


@dataclass(eq=False)
class TemplateMap:
    name: object | None = None
    role: object | None = None
    summary: object | None = None
    skills: SkillsSlot | None = None
    education: ListSlot | None = None
    certifications: ListSlot | None = None
    highlights: ListSlot | None = None
    projects: ProjectsSlot | None = None
    notes: list[str] = field(default_factory=list)

    def missing(self) -> list[str]:
        """Slots a resume cannot be rendered without. Education and certifications are optional."""
        found = {"name": self.name, "summary": self.summary, "highlights": self.highlights, "projects": self.projects}
        gaps = [slot for slot, value in found.items() if value is None]
        if self.skills is None or self.skills.proto_label is None or self.skills.proto_value is None:
            gaps.append("skills")
        return gaps


# --- the analyser -----------------------------------------------------------------------------------

def _containers(doc: DocxDocument):
    """The body, then every table cell: the places paragraphs live."""
    body = doc.element.body
    yield "body", body
    for t, table in enumerate(body.iter(W + "tbl")):
        for r, row in enumerate(table.findall(W + "tr")):
            for c, cell in enumerate(row.findall(W + "tc")):
                yield f"table{t}.r{r}c{c}", cell


def _paragraphs(container) -> list:
    return [child for child in container if child.tag == W + "p"]


def _find_header(doc: DocxDocument, m: TemplateMap) -> None:
    for label, container in _containers(doc):
        titles = [p for p in _paragraphs(container) if paragraph_style(p).lower() == "title"]
        if not titles:
            continue
        m.name = titles[0]
        m.role = titles[1] if len(titles) > 1 else None
        after = [p for p in _paragraphs(container) if p not in titles and paragraph_text(p).strip()]
        if after:
            m.summary = after[0]
        else:  # the summary can sit in another cell of the same table
            table = container.getparent().getparent()
            for cell in table.iter(W + "tc"):
                if cell is container:
                    continue
                m.summary = next((p for p in _paragraphs(cell) if paragraph_text(p).strip()), None)
                if m.summary is not None:
                    break
        m.notes.append(f"header found in {label}")
        break
    else:
        m.notes.append("no header: no Title-style paragraphs")
    if m.summary is None:  # last resort: the first long, unnumbered paragraph that is not a heading
        for _, container in _containers(doc):
            m.summary = next((p for p in _paragraphs(container) if len(paragraph_text(p)) > SUMMARY_MIN_CHARS
                              and not has_numbering(p) and not is_heading(p)), None)
            if m.summary is not None:
                break


def _find_sections(doc: DocxDocument) -> dict[str, list]:
    sections: dict[str, list] = {}
    for _, container in _containers(doc):
        paras = _paragraphs(container)
        for i, p in enumerate(paras):
            if not is_heading(p):
                continue
            end = next((j for j in range(i + 1, len(paras))
                        if is_heading(paras[j]) and paragraph_style(paras[j]).lower() == paragraph_style(p).lower()), len(paras))
            sections.setdefault(classify_heading(paragraph_text(p)), []).append((p, paras[i + 1:end]))
    return sections


def _find_blocks(paras: list) -> list[Block]:
    blocks: list[Block] = []
    current: Block | None = None
    for p in paras:
        if is_blank(p):
            if current is not None and current.bullets:
                blocks.append(current)
                current = None
        elif has_numbering(p):
            if current is not None:
                current.bullets.append(p)
        elif all_bold(p) and len(paragraph_text(p)) < MAX_PROJECT_NAME_CHARS:
            if current is not None and current.bullets:
                blocks.append(current)
            current = Block(name=p, desc=None, bullets=[])
        elif current is not None and current.desc is None:
            current.desc = p
    if current is not None and current.bullets:
        blocks.append(current)
    return blocks


def _separator_between(entries: list):
    """The blank paragraph that sits between the first two entries, if the template spaces its entries that way."""
    if len(entries) < 2:
        return None
    between = entries[0].getnext()
    return between if between is not None and between.getnext() is entries[1] and is_blank(between) else None


def analyse(doc: DocxDocument) -> TemplateMap:
    m = TemplateMap()
    _find_header(doc, m)
    sections = _find_sections(doc)
    m.notes.append("sections: " + ", ".join(f"{kind}x{len(found)}" for kind, found in sections.items()))

    def first(kind):
        return sections.get(kind, [None])[0]

    if found := first("skills"):
        heading, paras = found
        region = [p for p in paras if not is_blank(p)]
        label = next((p for p in region if first_run_bold(p)), None)
        value = region[region.index(label) + 1] if label is not None and region.index(label) + 1 < len(region) else None
        m.skills = SkillsSlot(heading=heading, region=region, proto_label=label, proto_value=value)
        m.notes.append(f"skills: {len(region)} paragraphs")
    for kind in ("education", "certifications"):
        if found := first(kind):
            heading, paras = found
            region = [p for p in paras if not is_blank(p)]
            if region:
                setattr(m, kind, ListSlot(heading=heading, region=region, proto=region[0]))
                m.notes.append(f"{kind}: {len(region)} entries")
    if found := first("highlights"):
        heading, paras = found
        bullets = [p for p in paras if has_numbering(p)]
        if bullets:
            m.highlights = ListSlot(heading=heading, region=bullets, proto=bullets[0], separator=_separator_between(bullets))
            m.notes.append(f"highlights: {len(bullets)} bullets")
    if found := first("projects"):
        heading, paras = found
        blocks = _find_blocks(paras)
        if blocks:
            richest = max(blocks, key=lambda b: len(b.bullets))
            bullets = richest.bullets
            m.projects = ProjectsSlot(
                heading=heading, blocks=blocks, proto_name=richest.name, proto_desc=richest.desc,
                proto_first=bullets[0], proto_mid=bullets[len(bullets) // 2] if len(bullets) > 2 else bullets[0],
                proto_last=bullets[-1], proto_blank=next((p for p in paras if is_blank(p)), None))
            m.notes.append(f"projects: {len(blocks)} blocks")
    return m

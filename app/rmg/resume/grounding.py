"""The grounding check: nothing in a tailored resume may be a claim the original resume does not support.

The tailoring model is not trusted, so this is done in code by comparing the tailored resume with the original.
Every item names the original item it came from (its `source`). For each item whose wording differs from that
original we check that it adds
  - no JD skill the resume does not have (missing_skill),
  - no number that is not in the original item (new_number),
  - no technology-looking term that is nowhere in the original resume (new_term),
and for every item that its source exists (unknown_source) and that an item claiming to be unchanged is unchanged
(altered_original). Items the associate typed in themselves are theirs to claim: they are not flagged, only listed.

enforce_grounding puts the original wording back for any item that fails, and drops an item that has no original.
"""
import re
from dataclasses import dataclass

from app.rmg.resume.match import MatchPlan, mentions
from app.rmg.resume.model import Item, Origin, Project, Resume, SkillGroup

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*%?")
_TOKEN = re.compile(r"[A-Za-z](?:[A-Za-z0-9+#.]*[A-Za-z0-9+#])?")


@dataclass(frozen=True)
class Violation:
    kind: str  # unknown_source, altered_original, missing_skill, new_number, new_term
    path: str  # where in the tailored resume, for example "projects.0.bullets.2"
    detail: str  # the offending skill, number or term


@dataclass(frozen=True)
class GroundingReport:
    violations: tuple[Violation, ...]
    user_added: tuple[str, ...]  # paths of items the associate typed in, for the Lead to see

    @property
    def ok(self) -> bool:
        return not self.violations


def _norm(text: str) -> str:
    return " ".join(text.split())


def _resume_text(resume: Resume) -> str:
    parts = [resume.name, *(item.text for _, item in resume.all_items()), *resume.certifications]
    parts += [g.category for g in resume.skill_groups]
    parts += [f"{e.degree or ''} {e.institution or ''}" for e in resume.education]
    parts += [f"{j.company or ''} {j.title or ''}" for j in resume.jobs]
    parts += [p.name for p in resume.projects]
    return "\n".join(parts)


def _looks_technical(token: str, position: int) -> bool:
    return (any(c.isupper() for c in token[1:]) or any(c.isdigit() or c in "+#" for c in token)
            or (token[0].isupper() and position > 0))


def check_grounding(original: Resume, tailored: Resume, plan: MatchPlan) -> GroundingReport:
    by_source = {item.source: item for _, item in original.all_items()}
    vocabulary = {t.casefold() for t in _TOKEN.findall(_resume_text(original))}
    not_evidenced = [*plan.missing_required, *plan.missing_nice]
    violations: list[Violation] = []
    user_added: list[str] = []

    for path, item in tailored.all_items():
        if item.origin is Origin.USER_ADDED:
            user_added.append(path)
            continue
        source = by_source.get(item.source)
        if source is None:
            violations.append(Violation("unknown_source", path, item.source or ""))
            continue
        if _norm(item.text) == _norm(source.text):
            continue
        if item.origin is Origin.ORIGINAL:
            violations.append(Violation("altered_original", path, ""))

        flagged_words: set[str] = set()
        for skill in not_evidenced:
            if mentions(item.text, skill) and not mentions(source.text, skill):
                violations.append(Violation("missing_skill", path, skill))
                flagged_words.update(w.casefold() for w in skill.split())
        allowed_numbers = set(_NUMBER.findall(source.text))
        violations += [Violation("new_number", path, n) for n in dict.fromkeys(_NUMBER.findall(item.text)) if n not in allowed_numbers]
        for position, token in enumerate(_TOKEN.findall(item.text)):
            key = token.casefold()
            if key not in vocabulary and key not in flagged_words and _looks_technical(token, position):
                violations.append(Violation("new_term", path, token))
                flagged_words.add(key)
    return GroundingReport(violations=tuple(violations), user_added=tuple(user_added))


def rebuild_items(resume: Resume, fn) -> Resume:
    """A copy of the resume with every item replaced by fn(path, item); None removes the item."""
    groups = []
    for g, group in enumerate(resume.skill_groups):
        items = [x for i, item in enumerate(group.items) if (x := fn(f"skill_groups.{g}.items.{i}", item)) is not None]
        if items:
            groups.append(SkillGroup(category=group.category, items=items))
    projects = []
    for p, project in enumerate(resume.projects):
        description = fn(f"projects.{p}.description", project.description) if project.description else None
        bullets = [x for b, item in enumerate(project.bullets) if (x := fn(f"projects.{p}.bullets.{b}", item)) is not None]
        projects.append(Project(name=project.name, description=description, bullets=bullets))
    return resume.model_copy(update={
        "role_title": fn("role_title", resume.role_title) if resume.role_title else None,
        "summary": fn("summary", resume.summary) if resume.summary else None,
        "skill_groups": groups,
        "highlights": [x for i, item in enumerate(resume.highlights) if (x := fn(f"highlights.{i}", item)) is not None],
        "projects": projects,
    })


def enforce_grounding(original: Resume, tailored: Resume, plan: MatchPlan) -> tuple[Resume, GroundingReport]:
    """The tailored resume with every failing item put back to its original wording (or dropped if it has no original)."""
    report = check_grounding(original, tailored, plan)
    failing = {v.path for v in report.violations}
    by_source: dict[str | None, Item] = {item.source: item for _, item in original.all_items()}

    def fix(path: str, item: Item) -> Item | None:
        return by_source.get(item.source) if path in failing else item

    return rebuild_items(tailored, fix), report

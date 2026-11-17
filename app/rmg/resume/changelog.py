"""The change log: what tailoring changed, in words a person can check. Computed in code from the two resumes, so the
log cannot disagree with what actually changed (a model's own account of its edits would not be trustworthy).

Kinds:
  reworded      the wording changed
  emphasised    reworded, and now brings forward a skill the role asks for
  condensed     reworded and clearly shorter
  dropped       an original item is no longer there
  reordered     a project, or the bullets inside a project, moved
  rejected      a change grounding refused (the original wording was kept)
  added_by_you  typed in by the associate
Alongside the entries: a plain-English summary and the JD coverage (what is covered, what cannot be claimed).
"""
import re
from dataclasses import dataclass

from app.rmg.resume.facts import Experience
from app.rmg.resume.grounding import GroundingReport
from app.rmg.resume.jd import Role
from app.rmg.resume.match import build_match_plan, mentions
from app.rmg.resume.model import Origin, Resume

CONDENSED_RATIO = 0.8

_PROJECT_ITEM = re.compile(r"^projects\.(\d+)\.(description|dates|bullets\.(\d+))$")
_HIGHLIGHT = re.compile(r"^highlights\.(\d+)$")
_CERTIFICATION = re.compile(r"^certifications\.(\d+)$")
_SKILL = re.compile(r"^skill_groups\.(\d+)\.items\.(\d+)$")


@dataclass(frozen=True)
class ChangeEntry:
    kind: str
    where: str  # a place a person can find, for example "Project 'Payments', bullet 2"
    source: str | None  # the original item's source reference, if there is one
    before: str | None
    after: str | None
    reason: str
    path: str | None = None  # the line in the tailored resume this is about (None for something that is no longer there)


@dataclass(frozen=True)
class Coverage:
    covered: tuple[str, ...]  # JD skills the tailored resume evidences
    missing_required: tuple[str, ...]  # required, not in the resume, so never claimed
    missing_nice: tuple[str, ...]
    required_before: float | None
    required_after: float | None
    meets_min_years: bool | None
    listed_required: tuple[str, ...] = ()  # required skills that are listed in the Skills section itself


@dataclass(frozen=True)
class ChangeLog:
    entries: tuple[ChangeEntry, ...]
    summary: str
    coverage: Coverage


def _where(path: str, resume: Resume) -> str:
    if m := _PROJECT_ITEM.match(path):
        p = int(m.group(1))
        if p < len(resume.projects):
            name = resume.projects[p].name
            if m.group(2) in ("description", "dates"):
                return f"Project '{name}', {m.group(2)}"
            return f"Project '{name}', bullet {int(m.group(3)) + 1}"
    if m := _HIGHLIGHT.match(path):
        return f"Highlight {int(m.group(1)) + 1}"
    if m := _CERTIFICATION.match(path):
        return f"Certification {int(m.group(1)) + 1}"
    if m := _SKILL.match(path):
        g, i = int(m.group(1)), int(m.group(2))
        if g < len(resume.skill_groups) and i < len(resume.skill_groups[g].items):
            return f"Skill '{resume.skill_groups[g].items[i].text}' in {resume.skill_groups[g].category}"
    return {"summary": "Summary", "role_title": "Role line"}.get(path, "Skills" if path.startswith("skill_groups.") else path)


def _count(n: int, noun: str, plural: str, verb: str = "") -> str:
    return f"{n} {noun if n == 1 else plural}" + (f" {verb}" if verb else "")


def _summary(entries, coverage: Coverage, required_total: int) -> str:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    parts = [_count(counts[k], "item", "items", k) for k in ("reworded", "emphasised", "condensed", "dropped") if k in counts]
    if "reordered" in counts:
        parts.append(_count(counts["reordered"], "order change", "order changes"))
    if "rejected" in counts:
        parts.append(_count(counts["rejected"], "change", "changes", "rejected"))
    if "added_by_you" in counts:
        parts.append(_count(counts["added_by_you"], "item", "items", "added by you"))
    text = ("Changes: " + ", ".join(parts) + ".") if parts else "No changes were made."
    if required_total:
        done = required_total - len(coverage.missing_required)
        text += f" Your resume covers {done} of {required_total} required skills."
        if coverage.missing_required:
            text += f" Not in your resume, so not added: {', '.join(coverage.missing_required)}."
    return text


def _reason_for_rejection(violations) -> str:
    terms = [v.detail for v in violations if v.kind in ("missing_skill", "new_term")]
    numbers = [v.detail for v in violations if v.kind == "new_number"]
    parts = []
    if terms:
        parts.append(f"it would have added {', '.join(dict.fromkeys(terms))}, which is not in your resume")
    if numbers:
        parts.append(f"it would have added the number {', '.join(dict.fromkeys(numbers))}, which is not in your resume")
    return "A change was rejected and the original wording kept: " + ("; ".join(parts) if parts else "it did not match your resume") + "."


def build_change_log(original: Resume, tailored: Resume, role: Role, report: GroundingReport,
                     experience: Experience | None = None) -> ChangeLog:
    wanted = [*role.must_have, *role.nice_to_have]
    original_items = dict(original.all_items())
    by_source = {item.source: item for item in original_items.values()}
    plan_before = build_match_plan(original, role, experience)
    plan_after = build_match_plan(tailored, role, experience)
    entries: list[ChangeEntry] = []

    # projects that moved (matched by name, each original project used once)
    unused = list(range(len(original.projects)))
    for new_pos, project in enumerate(tailored.projects):
        old_pos = next((i for i in unused if original.projects[i].name == project.name), None)
        if old_pos is None:
            continue
        unused.remove(old_pos)
        if old_pos != new_pos:
            skills = next((r.skills for r in plan_before.project_order if r.index == old_pos), ())
            reason = ((f"Covers {', '.join(skills)}, which the role asks for." if skills else "Moved up.")
                      if new_pos < old_pos else "Moved down so more relevant projects come first.")
            entries.append(ChangeEntry("reordered", f"Project '{project.name}'", None, f"Position {old_pos + 1}",
                                       f"Position {new_pos + 1}", reason, f"projects.{new_pos}"))
        original_project = original.projects[old_pos]
        position = {b.source: i for i, b in enumerate(original_project.bullets)}
        sequence = [position[b.source] for b in project.bullets if b.source in position]
        if sequence != sorted(sequence):
            entries.append(ChangeEntry("reordered", f"Project '{project.name}', bullets", None, None, None,
                                       "Most relevant bullets first.", f"projects.{new_pos}"))

    # items whose wording changed
    for path, item in tailored.all_items():
        source = by_source.get(item.source)
        if item.origin is not Origin.REWORDED or source is None or item.text == source.text:
            continue
        brought_forward = [s for s in wanted if mentions(item.text, s) and not mentions(source.text, s)]
        if brought_forward:
            kind, reason = "emphasised", f"Brings forward {', '.join(brought_forward)}, which the role asks for."
        elif len(item.text) < CONDENSED_RATIO * len(source.text):
            kind, reason = "condensed", "Shorter, so the strongest points stand out."
        else:
            kind, reason = "reworded", "Reworded for clarity."
        entries.append(ChangeEntry(kind, _where(path, tailored), source.source, source.text, item.text, reason, path))

    # original items that are gone, skills included (the baseline already has duplicate skills removed)
    kept_sources = {item.source for _, item in tailored.all_items() if item.origin is not Origin.USER_ADDED}
    for path, item in original.all_items():
        if item.source not in kept_sources:
            entries.append(ChangeEntry("dropped", _where(path, original), item.source, item.text, None,
                                       "Left out to keep the resume focused on this role."))

    tailored_items = dict(tailored.all_items())
    by_path: dict[str, list] = {}
    for v in report.violations:
        by_path.setdefault(v.path, []).append(v)
    for path, violations in by_path.items():
        kept = tailored_items.get(path)
        entries.append(ChangeEntry("rejected", _where(path, tailored), kept.source if kept else None,
                                   kept.text if kept else None, None, _reason_for_rejection(violations), path if kept else None))

    for path in report.user_added:
        item = tailored_items.get(path)
        if item is not None:
            entries.append(ChangeEntry("added_by_you", _where(path, tailored), None, None, item.text,
                                       "Added by you; the Competency Lead will see it marked as yours.", path))

    coverage = Coverage(
        covered=tuple(m.skill for m in plan_after.matches), missing_required=plan_after.missing_required,
        missing_nice=plan_after.missing_nice, required_before=plan_before.required_coverage,
        required_after=plan_after.required_coverage, meets_min_years=plan_after.meets_min_years,
        listed_required=tuple(m.skill for m in plan_after.matches if m.required and m.in_skills))
    return ChangeLog(entries=tuple(entries), summary=_summary(entries, coverage, len(role.must_have)), coverage=coverage)

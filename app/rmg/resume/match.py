"""The match plan: which JD requirements a resume already evidences, and which it does not.

Pure code, no model, so it is exact and testable. "Evidenced" means the skill is actually written in the resume
(skills section, summary, highlights or a project). A requirement that is not evidenced is reported as missing and
must never be claimed when the resume is tailored.
"""
import re
from dataclasses import dataclass

from app.rmg.resume.facts import Experience
from app.rmg.resume.jd import Role
from app.rmg.resume.model import Resume

REQUIRED_WEIGHT = 2
NICE_WEIGHT = 1


def mentions(text: str, skill: str) -> bool:
    """True if `skill` appears in `text` as a whole word, ignoring case and spacing ("Java" is not in "JavaScript",
    "C" is not in "C++")."""
    words = skill.split()
    if not words:
        return False
    pattern = r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in words) + r"(?![A-Za-z0-9+#])"
    return re.search(pattern, text, re.IGNORECASE) is not None


@dataclass(frozen=True)
class SkillMatch:
    skill: str
    required: bool
    in_skills: bool  # listed in the skills section
    projects: tuple[int, ...]  # indexes of projects that use it
    elsewhere: bool  # in the summary, role title or highlights


@dataclass(frozen=True)
class ProjectRank:
    index: int
    name: str
    skills: tuple[str, ...]  # JD skills this project mentions
    score: int


@dataclass(frozen=True)
class MatchPlan:
    role_title: str
    matches: tuple[SkillMatch, ...]  # required first, then nice to have, in JD order
    missing_required: tuple[str, ...]
    missing_nice: tuple[str, ...]
    required_coverage: float | None  # None if the role lists no must-haves
    project_order: tuple[ProjectRank, ...]  # most relevant first; every project is present
    skill_order: tuple[str, ...]  # the resume's own skills, JD-wanted ones first
    meets_min_years: bool | None  # None when unknown


def _project_text(project) -> str:
    parts = [project.name, project.description.text if project.description else "", *(b.text for b in project.bullets)]
    return "\n".join(parts)


def build_match_plan(resume: Resume, role: Role, experience: Experience | None = None) -> MatchPlan:
    wanted = [(s, True) for s in role.must_have] + [(s, False) for s in role.nice_to_have]
    skill_texts = [item.text for group in resume.skill_groups for item in group.items]
    project_texts = [_project_text(p) for p in resume.projects]
    elsewhere_text = "\n".join([
        resume.role_title.text if resume.role_title else "", resume.summary.text if resume.summary else "",
        *(h.text for h in resume.highlights)])

    matches, missing_required, missing_nice = [], [], []
    for skill, required in wanted:
        match = SkillMatch(
            skill=skill, required=required,
            in_skills=any(mentions(t, skill) for t in skill_texts),
            projects=tuple(i for i, t in enumerate(project_texts) if mentions(t, skill)),
            elsewhere=mentions(elsewhere_text, skill))
        if match.in_skills or match.projects or match.elsewhere:
            matches.append(match)
        else:
            (missing_required if required else missing_nice).append(skill)

    ranks = []
    for i, text in enumerate(project_texts):
        hit = [(s, req) for s, req in wanted if mentions(text, s)]
        ranks.append(ProjectRank(index=i, name=resume.projects[i].name, skills=tuple(s for s, _ in hit),
                                 score=sum(REQUIRED_WEIGHT if req else NICE_WEIGHT for _, req in hit)))
    project_order = tuple(sorted(ranks, key=lambda r: (-r.score, r.index)))

    def priority(skill_text: str) -> int:
        return next((n for n, (s, _) in enumerate(wanted) if mentions(skill_text, s)), len(wanted))

    skill_order = tuple(sorted(skill_texts, key=priority))  # sorted() is stable: the rest keep their order

    required_total = len(role.must_have)
    covered = sum(1 for m in matches if m.required)
    years = None
    if role.min_years is not None and experience is not None:
        years = experience.months >= role.min_years * 12

    return MatchPlan(
        role_title=role.title, matches=tuple(matches), missing_required=tuple(missing_required),
        missing_nice=tuple(missing_nice), required_coverage=covered / required_total if required_total else None,
        project_order=project_order, skill_order=skill_order, meets_min_years=years)


def order_skills(resume: Resume, plan: MatchPlan) -> Resume:
    """Each skill group keeps its place, and inside a group the skills the JD wants come first (ties keep their order)."""
    rank = {}
    for n, text in enumerate(plan.skill_order):
        rank.setdefault(text, n)
    groups = [group.model_copy(update={"items": sorted(group.items, key=lambda i: rank.get(i.text, len(rank)))})
              for group in resume.skill_groups]
    return resume.model_copy(update={"skill_groups": groups})

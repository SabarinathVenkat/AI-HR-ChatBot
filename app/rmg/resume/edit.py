"""Draft-only edits to a resume. Each function returns a new Resume and never changes the one it was given.

Who wrote the text decides what happens when it is not supported by the associate's original resume:
  by="user"       the associate typed it: it is kept, but marked user_added (theirs), so the Lead can see it
  by="assistant"  the model wrote it: it is refused (EditError "ungrounded"), because the model may not add claims
The associate can always add a fact of their own with add_fact; that is how a true skill the resume forgot to mention
gets in, as their own statement.
"""
from typing import Literal

from app.rmg.resume.grounding import check_grounding, rebuild_items
from app.rmg.resume.match import MatchPlan
from app.rmg.resume.model import (
    MAX_BULLETS_PER_PROJECT, MAX_CERTIFICATIONS, MAX_HIGHLIGHTS, MAX_ITEM_CHARS, MAX_ITEMS_PER_GROUP, MAX_SKILL_GROUPS, Item, Origin, Resume, SkillGroup,
)

By = Literal["user", "assistant"]

MESSAGES = {
    "no_such_item": "That part of the resume does not exist.",
    "empty_text": "The text cannot be empty.",
    "too_long": f"That is too long: please keep it under {MAX_ITEM_CHARS} characters.",
    "bad_position": "That position does not exist.",
    "full": "There is no room for another item there.",
    "ungrounded": "That wording is not supported by your original resume.",
    "duplicate": "That skill is already listed.",
    "not_allowed": "Please use the Add a skill button in the Skills section.",
}
MAX_DATES_CHARS = 60
MAX_CERTIFICATION_CHARS = 200
MAX_SKILL_CHARS = 100


class EditError(Exception):
    def __init__(self, code: str, message: str | None = None):
        self.code = code
        super().__init__(message or MESSAGES[code])


def _clean(text: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        raise EditError("empty_text")
    if len(text) > MAX_ITEM_CHARS:
        raise EditError("too_long")
    return text


def _skill_key(text: str) -> str:
    return " ".join(text.casefold().split())


def _check_skill(resume: Resume, text: str, ignore_path: str | None = None) -> None:
    if len(text) > MAX_SKILL_CHARS:
        raise EditError("too_long", f"A skill should be short: please keep it under {MAX_SKILL_CHARS} characters.")
    for path, item in resume.all_items():
        if path.startswith("skill_groups.") and path != ignore_path and _skill_key(item.text) == _skill_key(text):
            raise EditError("duplicate")


def _replace(resume: Resume, path: str, item: Item | None) -> Resume:
    return rebuild_items(resume, lambda p, i: item if p == path else i)


def set_text(resume: Resume, base: Resume, plan: MatchPlan, path: str, text: str, *, by: By) -> Resume:
    text = _clean(text)
    current = dict(resume.all_items()).get(path)
    if current is None:
        raise EditError("no_such_item")
    if path.startswith("skill_groups."):
        _check_skill(resume, text, ignore_path=path)
    if current.origin is Origin.USER_ADDED:
        return _replace(resume, path, Item(text=text, origin=Origin.USER_ADDED))
    original = next((i for _, i in base.all_items() if i.source == current.source), None)
    unchanged = original is not None and " ".join(original.text.split()) == text
    candidate = Item(text=text, origin=Origin.ORIGINAL if unchanged else Origin.REWORDED, source=current.source)
    result = _replace(resume, path, candidate)
    if unchanged:
        return result
    problems = [v for v in check_grounding(base, result, plan).violations if v.path == path]
    if not problems:
        return result
    if by == "assistant":
        terms = ", ".join(dict.fromkeys(v.detail for v in problems if v.detail))
        raise EditError("ungrounded", f"That wording would add {terms or 'something'}, which is not in your original resume.")
    return _replace(resume, path, Item(text=text, origin=Origin.USER_ADDED))  # theirs to claim, and the Lead can see it


def remove_item(resume: Resume, path: str) -> Resume:
    if path not in dict(resume.all_items()):
        raise EditError("no_such_item")
    return _replace(resume, path, None)


def _moved(items: list, index: int, to: int) -> list:
    if not (0 <= index < len(items) and 0 <= to < len(items)):
        raise EditError("bad_position")
    items = list(items)
    items.insert(to, items.pop(index))
    return items


def move_project(resume: Resume, index: int, to: int) -> Resume:
    return resume.model_copy(update={"projects": _moved(resume.projects, index, to)})


def move_bullet(resume: Resume, project: int, index: int, to: int) -> Resume:
    if not 0 <= project < len(resume.projects):
        raise EditError("no_such_item")
    target = resume.projects[project]
    changed = target.model_copy(update={"bullets": _moved(target.bullets, index, to)})
    projects = list(resume.projects)
    projects[project] = changed
    return resume.model_copy(update={"projects": projects})


def add_fact(resume: Resume, project: int | None, text: str) -> Resume:
    """A fact the associate gives us. It is added as theirs (user_added), to a project or to the highlights."""
    item = Item(text=_clean(text), origin=Origin.USER_ADDED)
    if project is None:
        if len(resume.highlights) >= MAX_HIGHLIGHTS:
            raise EditError("full")
        return resume.model_copy(update={"highlights": [*resume.highlights, item]})
    if not 0 <= project < len(resume.projects):
        raise EditError("no_such_item")
    target = resume.projects[project]
    if len(target.bullets) >= MAX_BULLETS_PER_PROJECT:
        raise EditError("full")
    projects = list(resume.projects)
    projects[project] = target.model_copy(update={"bullets": [*target.bullets, item]})
    return resume.model_copy(update={"projects": projects})


def set_role_line(resume: Resume, base: Resume, plan: MatchPlan, text: str, *, by: By) -> Resume:
    if resume.role_title is not None:
        return set_text(resume, base, plan, "role_title", text, by=by)
    if by == "assistant":
        raise EditError("ungrounded", "I cannot give you a role title that is not in your original resume.")
    return resume.model_copy(update={"role_title": Item(text=_clean(text), origin=Origin.USER_ADDED)})


def add_skill(resume: Resume, text: str, *, group: int | None = None, category: str | None = None) -> Resume:
    """A skill the associate adds. It is their own statement (user_added), so the Lead can see it. It goes into the group
    at index `group`, or into the group called `category` (made if it does not exist), or into "Other"."""
    text = _clean(text)
    _check_skill(resume, text)
    item = Item(text=text, origin=Origin.USER_ADDED)
    groups = list(resume.skill_groups)
    if group is not None:
        if not 0 <= group < len(groups):
            raise EditError("no_such_item")
        target = group
    else:
        name = " ".join((category or "Other").split())[:200] or "Other"
        target = next((i for i, g in enumerate(groups) if _skill_key(g.category) == _skill_key(name)), None)
        if target is None:
            if len(groups) >= MAX_SKILL_GROUPS:
                raise EditError("full")
            groups.append(SkillGroup(category=name, items=[]))
            target = len(groups) - 1
    if len(groups[target].items) >= MAX_ITEMS_PER_GROUP:
        raise EditError("full")
    groups[target] = SkillGroup(category=groups[target].category, items=[*groups[target].items, item])
    return resume.model_copy(update={"skill_groups": groups})


def add_certification_as(resume: Resume, text: str, *, by: By) -> Resume:
    """A certification the associate adds. Only they can: it is a claim about them, so it is marked as theirs."""
    if by == "assistant":
        raise EditError("not_allowed", "Please add the certification yourself, using Add a certification.")
    text = _clean(text)
    if len(text) > MAX_CERTIFICATION_CHARS:
        raise EditError("too_long", f"A certification should be short: please keep it under {MAX_CERTIFICATION_CHARS} characters.")
    if any(_skill_key(c.text) == _skill_key(text) for c in resume.certifications):
        raise EditError("duplicate", "That certification is already listed.")
    if len(resume.certifications) >= MAX_CERTIFICATIONS:
        raise EditError("full")
    return resume.model_copy(update={"certifications": [*resume.certifications, Item(text=text, origin=Origin.USER_ADDED)]})


def add_dates_as(resume: Resume, project: int, text: str, *, by: By) -> Resume:
    """Dates for a project whose resume gave none. Only the associate can add them: a date is a claim about their work."""
    if by == "assistant":
        raise EditError("not_allowed", "Please add the dates yourself, using Add dates on the project.")
    text = _clean(text)
    if len(text) > MAX_DATES_CHARS:
        raise EditError("too_long", f"Dates should be short: please keep them under {MAX_DATES_CHARS} characters.")
    if not 0 <= project < len(resume.projects):
        raise EditError("no_such_item")
    target = resume.projects[project]
    if target.dates is not None:
        raise EditError("duplicate", "That project already has dates: edit them instead.")
    projects = list(resume.projects)
    projects[project] = target.model_copy(update={"dates": Item(text=text, origin=Origin.USER_ADDED)})
    return resume.model_copy(update={"projects": projects})


def add_skill_as(resume: Resume, text: str, *, group: int | None = None, category: str | None = None, by: By) -> Resume:
    """Only the associate adds skills. The assistant may not: a skill is a claim, and only the associate can make it."""
    if by == "assistant":
        raise EditError("not_allowed")
    return add_skill(resume, text, group=group, category=category)

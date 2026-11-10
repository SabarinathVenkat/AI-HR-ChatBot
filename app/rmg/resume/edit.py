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
from app.rmg.resume.model import MAX_BULLETS_PER_PROJECT, MAX_HIGHLIGHTS, MAX_ITEM_CHARS, Item, Origin, Project, Resume

By = Literal["user", "assistant"]

MESSAGES = {
    "no_such_item": "That part of the resume does not exist.",
    "empty_text": "The text cannot be empty.",
    "too_long": f"That is too long: please keep it under {MAX_ITEM_CHARS} characters.",
    "bad_position": "That position does not exist.",
    "full": "There is no room for another item there.",
    "ungrounded": "That wording is not supported by your original resume.",
}


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


def _replace(resume: Resume, path: str, item: Item | None) -> Resume:
    return rebuild_items(resume, lambda p, i: item if p == path else i)


def set_text(resume: Resume, base: Resume, plan: MatchPlan, path: str, text: str, *, by: By) -> Resume:
    text = _clean(text)
    current = dict(resume.all_items()).get(path)
    if current is None:
        raise EditError("no_such_item")
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
    changed = Project(name=target.name, description=target.description, bullets=_moved(target.bullets, index, to))
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
    projects[project] = Project(name=target.name, description=target.description, bullets=[*target.bullets, item])
    return resume.model_copy(update={"projects": projects})


def set_role_line(resume: Resume, base: Resume, plan: MatchPlan, text: str, *, by: By) -> Resume:
    if resume.role_title is not None:
        return set_text(resume, base, plan, "role_title", text, by=by)
    if by == "assistant":
        raise EditError("ungrounded", "I cannot give you a role title that is not in your original resume.")
    return resume.model_copy(update={"role_title": Item(text=_clean(text), origin=Origin.USER_ADDED)})

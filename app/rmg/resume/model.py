"""The structured resume: the one shape every step of the resume builder agrees on.

Parsing produces it, tailoring changes it, the change log compares two of them, the renderer draws it.

Provenance is part of the model. Every piece of text is an Item that says where it came from:
  original    it is in the associate's resume (`source` points to where)
  reworded    the model rewrote an original item (`source` points to the item it was rewritten from)
  user_added  the associate typed it in during review (it has no source, because it is not in the resume)
An item that claims to come from the resume but names no source cannot be built, so "never invent skills" is
enforced by the data model itself, not only by a prompt.

Everything here is immutable and rejects unknown fields. Resume text is untrusted input, so it is trimmed,
checked for emptiness and limited in size.
"""
from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

MAX_ITEM_CHARS = 1200
MAX_SHORT_CHARS = 200
MAX_PROJECTS = 30
MAX_BULLETS_PER_PROJECT = 20
MAX_SKILL_GROUPS = 15
MAX_ITEMS_PER_GROUP = 40
MAX_HIGHLIGHTS = 15
MAX_EDUCATION = 10
MAX_CERTIFICATIONS = 20
MAX_JOBS = 20
MAX_BADGES = 6

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_ITEM_CHARS)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_SHORT_CHARS)]


class Origin(StrEnum):
    ORIGINAL = "original"
    REWORDED = "reworded"
    USER_ADDED = "user_added"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Item(_Model):
    """A piece of text with its provenance."""

    text: Text
    origin: Origin
    source: ShortText | None = None
    by: ShortText | None = None  # who added or changed it when it was not the associate: a reviewer's name

    @model_validator(mode="after")
    def _provenance_is_consistent(self) -> "Item":
        if self.origin is Origin.USER_ADDED and self.source is not None:
            raise ValueError("a user-added item has no source: it is not in the original resume")
        if self.origin is not Origin.USER_ADDED and self.source is None:
            raise ValueError(f"an item with origin '{self.origin.value}' must name its source in the original resume")
        return self


class SkillGroup(_Model):
    category: ShortText
    items: list[Item] = Field(default_factory=list, max_length=MAX_ITEMS_PER_GROUP)


class Education(_Model):
    """A degree or an institution (or both): a resume may leave out the college, or give only the college."""

    degree: ShortText | None = None
    institution: ShortText | None = None
    year: ShortText | None = None

    @model_validator(mode="after")
    def _has_something(self) -> "Education":
        if self.degree is None and self.institution is None:
            raise ValueError("an education entry needs a degree or an institution")
        return self


class Job(_Model):
    """A company or a title (or both): a resume may leave out either. The dates are what experience is computed from."""

    company: ShortText | None = None
    title: ShortText | None = None
    start: ShortText | None = None
    end: ShortText | None = None

    @model_validator(mode="after")
    def _has_something(self) -> "Job":
        if self.company is None and self.title is None:
            raise ValueError("a job needs a company or a title")
        return self


class Project(_Model):
    name: ShortText
    dates: Item | None = None  # when the project ran, as the resume writes it: "Jan 2022 \u2013 Mar 2023"
    description: Item | None = None
    bullets: list[Item] = Field(default_factory=list, max_length=MAX_BULLETS_PER_PROJECT)


class Badge(_Model):
    """A small picture kept from the header of the uploaded resume (for example a certification badge). The picture itself is in
    the file store under `key`; the associate can leave it out of the Word file by setting `keep` to false."""

    key: ShortText
    label: ShortText | None = None
    keep: bool = True


class Resume(_Model):
    name: ShortText
    role_title: Item | None = None
    summary: Item | None = None
    skill_groups: list[SkillGroup] = Field(default_factory=list, max_length=MAX_SKILL_GROUPS)
    education: list[Education] = Field(default_factory=list, max_length=MAX_EDUCATION)
    certifications: list[Item] = Field(default_factory=list, max_length=MAX_CERTIFICATIONS)
    highlights: list[Item] = Field(default_factory=list, max_length=MAX_HIGHLIGHTS)
    jobs: list[Job] = Field(default_factory=list, max_length=MAX_JOBS)
    projects: list[Project] = Field(default_factory=list, max_length=MAX_PROJECTS)
    badges: list[Badge] = Field(default_factory=list, max_length=MAX_BADGES)

    @field_validator("certifications", mode="before")
    @classmethod
    def _old_certifications_were_plain_text(cls, value):
        """Drafts saved before certifications carried a source stored them as plain text: they are the resume's own."""
        if isinstance(value, list):
            return [{"text": v, "origin": "original", "source": f"certifications.{i}"} if isinstance(v, str) else v
                    for i, v in enumerate(value)]
        return value

    def all_items(self) -> Iterator[tuple[str, Item]]:
        """Every text item with its path, for example ("projects.0.bullets.2", Item). Used to compare and verify."""
        if self.role_title is not None:
            yield "role_title", self.role_title
        if self.summary is not None:
            yield "summary", self.summary
        for g, group in enumerate(self.skill_groups):
            for i, item in enumerate(group.items):
                yield f"skill_groups.{g}.items.{i}", item
        for i, item in enumerate(self.highlights):
            yield f"highlights.{i}", item
        for i, item in enumerate(self.certifications):
            yield f"certifications.{i}", item
        for p, project in enumerate(self.projects):
            if project.dates is not None:
                yield f"projects.{p}.dates", project.dates
            if project.description is not None:
                yield f"projects.{p}.description", project.description
            for b, bullet in enumerate(project.bullets):
                yield f"projects.{p}.bullets.{b}", bullet

    def items_with_origin(self, origin: Origin) -> list[tuple[str, Item]]:
        return [(path, item) for path, item in self.all_items() if item.origin is origin]

    def skills_flat(self) -> list[str]:
        return [item.text for group in self.skill_groups for item in group.items]

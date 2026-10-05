"""The shape of an evaluation case."""
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from eval.checks import Check


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    persona: str  # employee name from the seeded demo company
    turns: tuple[str, ...]  # the user's messages, in order, on one conversation thread
    expect: Callable[[sqlite3.Connection], list[Check]]  # built against the case's own database
    setup: Callable[[sqlite3.Connection], None] | None = None  # e.g. poison a policy chunk
    probe: bool = False  # also run in the serial latency measurement

    @property
    def question(self) -> str:
        return self.turns[-1]


def case(id, category, persona, turns, expect, setup=None, probe=False) -> Case:
    turns = (turns,) if isinstance(turns, str) else tuple(turns)
    return Case(id, category, persona, turns, expect, setup, probe)


CATEGORIES = (
    "policy", "data", "calculation", "policy_and_data", "workflow",
    "multi_turn", "planning", "sensitive", "out_of_scope", "manager",
)

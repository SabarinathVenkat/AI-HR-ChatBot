"""Server-side identity and environment for tool calls. The model never supplies these."""
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from app.rag.search import Retrieval


@dataclass(frozen=True)
class ToolContext:
    conn: sqlite3.Connection
    employee_id: int
    role: str
    trace_id: str
    today: date
    retrieval: Retrieval | None = None
    now: datetime | None = None  # the app's clock; None means use the machine clock

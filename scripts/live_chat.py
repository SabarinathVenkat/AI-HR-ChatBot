"""Run real questions through the live agent and print routing, tools, answer and timing.

    python scripts/live_chat.py                 # built-in sample questions, as Ravi Kumar (employee)
    python scripts/live_chat.py "your question" # one question
Uses ANTHROPIC_API_KEY (from .env). Costs a few cents per run.
"""
import sys
import time
import uuid
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from app.agent.factory import build_live_agent  # noqa: E402
from app.agent.graph import run_turn  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.connection import connect, init_schema  # noqa: E402
from app.db.seed import SEED_AS_OF, seed  # noqa: E402
from app.rag.chunker import load_policy_dir  # noqa: E402
from app.rag.embeddings import FastEmbedder  # noqa: E402
from app.rag.index import index_policies  # noqa: E402
from app.rag.search import Retrieval  # noqa: E402
from app.tools.context import ToolContext  # noqa: E402

POLICIES = Path(__file__).resolve().parents[1] / "data" / "policies"
SAMPLE = [
    "Hi!",
    "How many annual leave days do I have left?",
    "What is the notice period after I resign?",
    "I want to take leave from 2 November to 6 November. Is that okay?",
    "How many working days is 19 October to 23 October?",
    "Can I carry forward my unused annual leave? How much would carry over?",
    "What is the dress code at the office?",
    "What is Divya Menon's leave balance?",
    "Someone at work has been harassing me and I don't know what to do.",
    "Write me a poem about the moon.",
]


def main() -> None:
    settings = Settings(jwt_secret="x" * 40)
    conn = connect(":memory:")
    init_schema(conn)
    seed(conn, as_of=SEED_AS_OF, hash_password=lambda p: "unused")
    embedder = FastEmbedder()
    index_policies(conn, load_policy_dir(POLICIES), embedder)
    agent = build_live_agent(settings, MemorySaver())
    ctx = ToolContext(conn=conn, employee_id=4, role="employee", trace_id="live", today=date(2026, 10, 2),
                      retrieval=Retrieval(embedder))
    questions = sys.argv[1:] or SAMPLE
    thread = uuid.uuid4().hex
    for question in questions:
        start = time.perf_counter()
        result = run_turn(agent, ctx, thread if len(questions) == 1 else uuid.uuid4().hex, question)
        elapsed = time.perf_counter() - start
        print("=" * 78)
        print(f"Q: {question}")
        print(f"   intent={result.intent} tools={[c['name'] for c in result.calls]} "
              f"rewrites={result.attempts} fallback={result.used_fallback} flags={result.flags} {elapsed:.1f}s")
        if result.problems:
            print(f"   verifier problems: {result.problems}")
        print(result.final)


if __name__ == "__main__":
    main()

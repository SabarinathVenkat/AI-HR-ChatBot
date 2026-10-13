"""Live smoke test of the Anthropic API: both models, a tool call, and native citations.

Run:  python scripts/check_claude.py
The key is read from ANTHROPIC_API_KEY (loaded from .env if present). It is never printed.
"""
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()
if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("ANTHROPIC_API_KEY is not set.")

import anthropic  # noqa: E402

client = anthropic.Anthropic()
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]


def timed(label, **kwargs):
    start = time.perf_counter()
    response = client.messages.create(**kwargs)
    elapsed = time.perf_counter() - start
    print(f"[{label}] {elapsed:.2f}s in={response.usage.input_tokens} out={response.usage.output_tokens}")
    return response


for model in MODELS:
    try:
        r = timed(model, model=model, max_tokens=30, messages=[{"role": "user", "content": "Reply with the single word: ready"}])
        print("  ->", r.content[0].text.strip(), "| model:", r.model)
    except Exception as exc:  # report, do not hide
        print(f"[{model}] FAILED: {type(exc).__name__}: {str(exc)[:200]}")

# Tool use
tool = {
    "name": "get_leave_balance",
    "description": "Get the signed-in employee's leave balances.",
    "input_schema": {"type": "object", "properties": {"leave_type": {"type": "string"}}},
}
try:
    r = timed("tool-use", model="claude-sonnet-5-5", max_tokens=200, tools=[tool],
              messages=[{"role": "user", "content": "How many annual leave days do I have?"}])
    uses = [b for b in r.content if b.type == "tool_use"]
    print("  ->", [(u.name, u.input) for u in uses], "| stop:", r.stop_reason)
except Exception as exc:
    print(f"[tool-use] FAILED: {type(exc).__name__}: {str(exc)[:200]}")

# Native citations over search_result blocks
try:
    r = timed(
        "citations",
        model="claude-sonnet-5-5",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "search_result",
                    "source": "POL-05 §3",
                    "title": "Notice Period",
                    "content": [{"type": "text", "text": "3.1 After confirmation the notice period is 60 days for individual contributors and 90 days for managers."}],
                    "citations": {"enabled": True},
                },
                {"type": "text", "text": "How long is the notice period for an individual contributor?"},
            ],
        }],
    )
    for block in r.content:
        if block.type == "text":
            cites = [getattr(c, "source", None) or getattr(c, "type", "?") for c in (block.citations or [])]
            print("  ->", block.text.strip()[:160], "| citations:", cites)
except Exception as exc:
    print(f"[citations] FAILED: {type(exc).__name__}: {str(exc)[:300]}")

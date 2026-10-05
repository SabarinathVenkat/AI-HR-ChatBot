"""Run evaluation cases against an agent and summarize the results honestly."""
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone

from langchain_core.callbacks import get_usage_metadata_callback

from app.agent.graph import run_turn
from app.db import repositories as repo
from app.db.connection import connect
from app.tools.context import ToolContext
from eval import oracle
from eval.cases_base import Case
from eval.checks import CheckResult, Outcome, World, is_soft
from eval.stats import percentile, wilson_interval

TODAY = date(2026, 10, 2)
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


@dataclass
class CaseResult:
    id: str
    category: str
    persona: str
    turns: tuple[str, ...]
    passed: bool
    checks: list[tuple[CheckResult, bool]]  # (result, soft)
    outcome: Outcome

    @property
    def hard_failures(self) -> list[CheckResult]:
        return [r for r, soft in self.checks if not r.passed and not soft]


def copy_database(template: sqlite3.Connection) -> sqlite3.Connection:
    """A private, writable copy so one case's changes can never leak into another."""
    copy = connect(":memory:")
    template.backup(copy)
    return copy


def run_case(
    case: Case,
    template: sqlite3.Connection,
    agent,
    retrieval,
    judge_fn=None,
) -> CaseResult:
    conn = copy_database(template)
    try:
        if case.setup:
            case.setup(conn)
        persona_id = oracle.employee_id(conn, case.persona)
        employee = repo.get_employee(conn, persona_id)
        requests_before = conn.execute("SELECT count(*) FROM leave_requests").fetchone()[0]
        ctx = ToolContext(
            conn=conn, employee_id=persona_id, role=employee.role, trace_id=f"eval-{case.id}",
            today=TODAY, retrieval=retrieval, now=NOW,
        )
        outcome = Outcome()
        thread = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"
        started = time.perf_counter()
        try:
            with get_usage_metadata_callback() as usage:
                for message in case.turns:
                    turn = run_turn(agent, ctx, thread, message)
                    outcome.answers.append(turn.final)
                    outcome.intents.append(turn.intent)
                    outcome.calls.extend(turn.calls)
                    outcome.used_fallback = outcome.used_fallback or turn.used_fallback
                    outcome.rewrites += turn.attempts
                    outcome.confirmation = turn.confirmation
            for counts in usage.usage_metadata.values():
                outcome.input_tokens += counts.get("input_tokens", 0)
                outcome.output_tokens += counts.get("output_tokens", 0)
        except Exception as exc:  # a crashed case is a failed case, not a crashed run
            outcome.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        outcome.seconds = time.perf_counter() - started

        world = World(
            conn=conn, requests_before=requests_before, drafts_open_before=0, persona_id=persona_id,
            other_names=oracle.other_names(conn, persona_id), judge=judge_fn, question=case.question,
        )
        results = []
        for check in case.expect(conn):
            try:
                results.append((check(outcome, world), is_soft(check)))
            except Exception as exc:  # a broken check must be visible, never silently passed
                results.append((CheckResult("check_error", False, f"{type(exc).__name__}: {exc}"), False))
        passed = all(r.passed for r, soft in results if not soft)
        return CaseResult(case.id, case.category, case.persona, case.turns, passed, results, outcome)
    finally:
        conn.close()


def run_cases(cases, template, agent, retrieval, judge_fn=None, workers: int = 1, progress=None) -> list[CaseResult]:
    def one(case):
        result = run_case(case, template, agent, retrieval, judge_fn)
        if progress:
            progress(result)
        return result

    if workers <= 1:
        return [one(c) for c in cases]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, cases))


# ---- summarizing ----------------------------------------------------------------------------

def _rate(passed: int, n: int) -> dict:
    low, high = wilson_interval(passed, n)
    return {"n": n, "passed": passed, "rate": (passed / n) if n else None, "ci_low": low, "ci_high": high}


def _metric_group(name: str) -> str | None:
    if name.startswith("number:"):
        return "numeric_exactness"
    if name == "citations_valid":
        return "citation_validity"
    if name.startswith("cites:"):
        return "citation_present"
    if name.startswith("judge:"):
        return "judged_answers"
    if name.startswith("calls:") or name.startswith("never_calls:"):
        return "tool_correctness"
    if name in ("writes_nothing", "db_intact", "no_draft") or name.startswith(("draft_prepared", "request_")):
        return "workflow_safety"
    if name == "no_other_people" or name.startswith("never_says:"):
        return "no_data_leaks"
    if name == "no_fallback":
        return "no_fallback"
    if name.startswith("intent:"):
        return "routing"
    return None


def summarize(results: list[CaseResult], set_name: str, config: dict | None = None) -> dict:
    by_category: dict[str, list[CaseResult]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r)

    groups: dict[str, list[bool]] = {}
    for r in results:
        for check, _soft in r.checks:
            group = _metric_group(check.name)
            if group:
                groups.setdefault(group, []).append(check.passed)

    n = len(results)
    failures = [
        {
            "id": r.id, "category": r.category, "persona": r.persona, "turns": list(r.turns),
            "answer": r.outcome.answer[:600],
            "failed": [{"check": c.name, "detail": c.detail} for c in r.hard_failures],
            "error": r.outcome.error,
        }
        for r in results if not r.passed
    ]
    return {
        "set": set_name,
        "config": config or {},
        "overall": _rate(sum(r.passed for r in results), n),
        "by_category": {cat: _rate(sum(r.passed for r in rs), len(rs)) for cat, rs in sorted(by_category.items())},
        "metrics": {g: _rate(sum(v), len(v)) for g, v in sorted(groups.items())},
        "fallback_rate": _rate(sum(r.outcome.used_fallback for r in results), n),
        "rewrite_rate": _rate(sum(r.outcome.rewrites > 0 for r in results), n),
        "errors": sum(1 for r in results if r.outcome.error),
        "tokens": {
            "input": sum(r.outcome.input_tokens for r in results),
            "output": sum(r.outcome.output_tokens for r in results),
            "note": "Approximate: calls made inside planning sub-agents may not be counted.",
        },
        "failures": failures,
    }


def latency_summary(results: list[CaseResult]) -> dict:
    by_category: dict[str, list[float]] = {}
    for r in results:
        by_category.setdefault(r.category, []).append(r.outcome.seconds)
    return {
        cat: {"n": len(v), "p50": percentile(v, 50), "p95": percentile(v, 95), "max": max(v)}
        for cat, v in sorted(by_category.items())
    }


def _pct(rate: dict) -> str:
    if not rate["n"]:
        return "n/a"
    return f"{rate['rate'] * 100:.1f}% ({rate['passed']}/{rate['n']}, 95% CI {rate['ci_low'] * 100:.0f} to {rate['ci_high'] * 100:.0f}%)"


def render_markdown(summary: dict, latency: dict | None = None) -> str:
    lines = [f"# Evaluation report: {summary['set']}", ""]
    if summary["config"]:
        lines += ["| Setting | Value |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in summary["config"].items()] + [""]
    lines += [
        f"**Cases passed: {_pct(summary['overall'])}**",
        "",
        "A case passes only if every hard check passes. Intervals are 95% Wilson intervals: with few "
        "cases they are wide, and a high score on a small set proves less than it seems to.",
        "",
        "## By category", "", "| Category | Result |", "|---|---|",
    ]
    lines += [f"| {cat} | {_pct(r)} |" for cat, r in summary["by_category"].items()]
    lines += ["", "## Quality metrics (over individual checks)", "", "| Metric | Result |", "|---|---|"]
    lines += [f"| {name} | {_pct(r)} |" for name, r in summary["metrics"].items()]
    lines += [
        f"| cases that used the plain fallback | {_pct(summary['fallback_rate'])} |",
        f"| cases that needed a rewrite | {_pct(summary['rewrite_rate'])} |",
        "",
        f"Crashed cases: {summary['errors']}. Tokens: {summary['tokens']['input']:,} in, "
        f"{summary['tokens']['output']:,} out ({summary['tokens']['note']})",
    ]
    if latency:
        lines += ["", "## Latency (serial run, seconds per complete answer)", "",
                  "| Category | n | median | p95 | max |", "|---|---|---|---|---|"]
        lines += [f"| {c} | {v['n']} | {v['p50']:.1f} | {v['p95']:.1f} | {v['max']:.1f} |" for c, v in latency.items()]
    lines += ["", f"## Failures ({len(summary['failures'])})", ""]
    for f in summary["failures"]:
        lines += [
            f"### {f['id']} ({f['category']}, as {f['persona']})",
            f"- Asked: {' / '.join(f['turns'])}",
            "- Failed: " + "; ".join(f"`{x['check']}` {x['detail']}" for x in f["failed"]) + (f" ERROR {f['error']}" if f["error"] else ""),
            f"- Answer: {f['answer']!r}", "",
        ]
    return "\n".join(lines)

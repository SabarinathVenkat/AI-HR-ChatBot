"""Run the evaluation against the live agent.

    python -m eval.run_eval                       # development set (120 questions)
    python -m eval.run_eval --set redteam         # attack set: every case must pass
    python -m eval.run_eval --set heldout         # held-out set: run ONCE, at the end
    python -m eval.run_eval --latency             # serial latency run over the probe questions
    python -m eval.run_eval --only P01,D03        # specific cases
Reports are written to eval/reports/ as JSON and Markdown. Uses ANTHROPIC_API_KEY (from .env).
"""
import argparse
import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver

from app.agent import prompts
from app.agent.factory import build_live_agent
from app.config import Settings
from app.db.connection import connect, init_schema
from app.db.seed import SEED_AS_OF, seed
from app.rag.chunker import load_policy_dir
from app.rag.embeddings import FastEmbedder
from app.rag.index import index_policies
from app.rag.search import Retrieval
from eval.cases_dev import DEV_CASES
from eval.cases_heldout import HELD_OUT_CASES
from eval.judge import make_judge
from eval.redteam import REDTEAM_CASES
from eval.runner import latency_summary, render_markdown, run_cases, summarize

POLICIES = Path(__file__).resolve().parents[1] / "data" / "policies"
REPORTS = Path(__file__).resolve().parent / "reports"
SETS = {"dev": DEV_CASES, "heldout": HELD_OUT_CASES, "redteam": REDTEAM_CASES}
LATENCY_CATEGORIES = ("policy", "data", "calculation", "policy_and_data", "workflow", "sensitive", "out_of_scope", "manager")


def latency_probes():
    probes = [c for c in DEV_CASES if c.probe]
    for category in LATENCY_CATEGORIES:
        probes += [c for c in DEV_CASES if c.category == category and not c.probe][:3]
    return probes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=[*SETS, "all"], default="dev")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--latency", action="store_true", help="serial run over the probe questions")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.WARNING)
    for noisy in ("httpx", "httpx2", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    if args.latency:
        cases, name, workers = latency_probes(), "latency-probes", 1
    else:
        cases = list(SETS[args.set]) if args.set != "all" else [*DEV_CASES, *REDTEAM_CASES]
        name, workers = args.set, args.workers
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.id in wanted]
    if args.limit:
        cases = cases[: args.limit]
    if args.set == "heldout" and not args.only:
        print("NOTE: the held-out set should be run once, at the end. Do not tune against it.\n")

    settings = Settings(jwt_secret="x" * 40)
    template = connect(":memory:")
    init_schema(template)
    seed(template, as_of=SEED_AS_OF, hash_password=lambda _plain: "unused")
    embedder = FastEmbedder()
    corpus = index_policies(template, load_policy_dir(POLICIES), embedder)
    embedder.embed(["warm up"])
    agent = build_live_agent(settings, MemorySaver())
    judge_fn = make_judge(settings.answer_model)
    retrieval = Retrieval(embedder)

    lock = threading.Lock()
    done = [0]

    def progress(result):
        with lock:
            done[0] += 1
            mark = "PASS" if result.passed else "FAIL"
            print(f"[{done[0]:>3}/{len(cases)}] {result.id:<5} {mark} {result.outcome.seconds:5.1f}s", flush=True)

    print(f"Running {len(cases)} cases ({name}) with {workers} worker(s)...")
    results = run_cases(cases, template, agent, retrieval, judge_fn, workers, progress)

    config = {
        "set": name, "cases": len(cases), "workers": workers,
        "answer_model": settings.answer_model, "router_model": settings.router_model,
        "prompt_version": prompts.PROMPT_VERSION, "policy_corpus_sha256": corpus[:16],
        "demo_date": SEED_AS_OF.isoformat(), "run_at": datetime.now().isoformat(timespec="seconds"),
    }
    summary = summarize(results, name, config)
    latency = latency_summary(results) if args.latency else None

    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = REPORTS / f"{stamp}-{name}"
    base.with_suffix(".json").write_text(
        json.dumps({"summary": summary, "latency": latency}, indent=2, default=str), encoding="utf-8")
    base.with_suffix(".md").write_text(render_markdown(summary, latency), encoding="utf-8")

    overall = summary["overall"]
    print(f"\nPassed {overall['passed']}/{overall['n']}  (95% CI {overall['ci_low']:.0%} to {overall['ci_high']:.0%})")
    for cat, r in summary["by_category"].items():
        print(f"  {cat:<16} {r['passed']}/{r['n']}")
    print(f"Report: {base}.md")
    if args.set == "redteam" or name == "redteam":
        return 0 if overall["passed"] == overall["n"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

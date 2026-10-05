"""Measure retrieval quality with the real embedding model.

    python -m eval.run_retrieval_eval            # dev set only (use this while tuning)
    python -m eval.run_retrieval_eval --held-out # held-out set; run once, at the end
"""
import argparse
from pathlib import Path

from app.db.connection import connect, init_schema
from app.rag.chunker import load_policy_dir
from app.rag.embeddings import FastEmbedder
from app.rag.index import index_policies
from app.rag.search import search_policy
from eval import retrieval_questions as q

POLICIES = Path(__file__).resolve().parents[1] / "data" / "policies"


def build_index():
    conn = connect(":memory:")
    init_schema(conn)
    embedder = FastEmbedder()
    index_policies(conn, load_policy_dir(POLICIES), embedder)
    return conn, embedder


def top_similarity(conn, embedder, question: str) -> float:
    hits = search_policy(conn, question, embedder, k=5)
    sims = [h.similarity for h in hits if h.similarity is not None]
    return max(sims) if sims else 0.0


def evaluate(conn, embedder, answerable, unanswerable):
    found = 0
    answer_sims, miss = [], []
    for question, accepted in answerable:
        hits = search_policy(conn, question, embedder, k=3)
        ok = any(h.section_id in accepted for h in hits)
        found += ok
        answer_sims.append(top_similarity(conn, embedder, question))
        if not ok:
            miss.append((question, accepted, [h.section_id for h in hits]))
    decline_sims = [top_similarity(conn, embedder, question) for question in unanswerable]
    return found, miss, answer_sims, decline_sims


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--held-out", action="store_true")
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args()
    answerable = q.HELD_OUT_ANSWERABLE if args.held_out else q.DEV_ANSWERABLE
    unanswerable = q.HELD_OUT_UNANSWERABLE if args.held_out else q.DEV_UNANSWERABLE
    conn, embedder = build_index()
    found, miss, a_sims, d_sims = evaluate(conn, embedder, answerable, unanswerable)
    print(f"{'HELD-OUT' if args.held_out else 'DEV'} set")
    print(f"recall@3: {found}/{len(answerable)}")
    for question, accepted, got in miss:
        print(f"  MISS: {question!r} wanted {sorted(accepted)} got {got}")
    print(f"answerable top similarity: min {min(a_sims):.3f}  median {sorted(a_sims)[len(a_sims)//2]:.3f}")
    print(f"unanswerable top similarity: max {max(d_sims):.3f}  median {sorted(d_sims)[len(d_sims)//2]:.3f}")
    if args.threshold is not None:
        kept = sum(s >= args.threshold for s in a_sims)
        declined = sum(s < args.threshold for s in d_sims)
        print(f"threshold {args.threshold}: answers kept {kept}/{len(a_sims)}, "
              f"unanswerable declined {declined}/{len(d_sims)}")


if __name__ == "__main__":
    main()

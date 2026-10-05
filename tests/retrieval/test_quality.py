"""Retrieval quality with the real embedding model, on the DEV question set only.

The held-out set is never used here. It is run by eval/run_retrieval_eval.py --held-out.
The first run downloads the embedding model (about 130 MB) into models_cache/.
"""
from pathlib import Path

import pytest

from app.db.connection import connect, init_schema
from app.rag.chunker import load_policy_dir
from app.rag.embeddings import FastEmbedder
from app.rag.index import index_policies
from app.rag.search import SIMILARITY_THRESHOLD, is_confident, search_policy
from eval import retrieval_questions as q

POLICIES = Path(__file__).resolve().parents[2] / "data" / "policies"


@pytest.fixture(scope="module")
def real_index():
    conn = connect(":memory:")
    init_schema(conn)
    embedder = FastEmbedder()
    index_policies(conn, load_policy_dir(POLICIES), embedder)
    yield conn, embedder
    conn.close()


def test_the_right_section_is_in_the_top_three_for_nearly_every_dev_question(real_index):
    conn, embedder = real_index
    found = sum(
        any(h.section_id in accepted for h in search_policy(conn, question, embedder, k=3))
        for question, accepted in q.DEV_ANSWERABLE
    )

    assert found / len(q.DEV_ANSWERABLE) >= 0.95


def test_questions_the_policies_do_not_cover_are_declined(real_index):
    conn, embedder = real_index
    declined = [
        question
        for question in q.DEV_UNANSWERABLE
        if not is_confident(search_policy(conn, question, embedder, k=5))
    ]

    assert declined == q.DEV_UNANSWERABLE


def test_questions_the_policies_cover_are_not_declined(real_index):
    conn, embedder = real_index
    kept = sum(
        is_confident(search_policy(conn, question, embedder, k=5))
        for question, _ in q.DEV_ANSWERABLE
    )

    assert kept / len(q.DEV_ANSWERABLE) >= 0.95


def test_the_threshold_is_the_documented_value():
    assert SIMILARITY_THRESHOLD == 0.655

"""Indexing and hybrid search logic, using a deterministic bag-of-words embedder."""
import pytest

from app.db.connection import connect, init_schema
from app.rag.chunker import chunk_policy_text
from app.rag.index import index_policies
from app.rag.search import search_policy
from tests.support import BagOfWordsEmbedder

LEAVE = """---
policy_id: POL-A
title: Leave Policy
version: "1.0"
effective_date: 2026-01-01
source_status: test
---

## 1. Notice Period
1.1 The notice period after confirmation is sixty days for everyone.

## 2. Carry Forward
2.1 Unused annual leave carries forward up to ten days each year.
"""

CONDUCT = """---
policy_id: POL-B
title: Conduct Policy
version: "1.0"
effective_date: 2026-01-01
source_status: test
---

## 1. Gifts
1.1 Gifts from vendors above three thousand rupees must be reported to HR.
"""


@pytest.fixture
def indexed():
    conn = connect(":memory:")
    init_schema(conn)
    chunks = chunk_policy_text(LEAVE) + chunk_policy_text(CONDUCT)
    index_policies(conn, chunks, BagOfWordsEmbedder())
    yield conn
    conn.close()


def search(conn, query, **kwargs):
    return search_policy(conn, query, BagOfWordsEmbedder(), **kwargs)


def test_indexing_is_idempotent():
    conn = connect(":memory:")
    init_schema(conn)
    chunks = chunk_policy_text(LEAVE) + chunk_policy_text(CONDUCT)

    first = index_policies(conn, chunks, BagOfWordsEmbedder())
    second = index_policies(conn, chunks, BagOfWordsEmbedder())

    count = conn.execute("SELECT count(*) FROM policy_chunks").fetchone()[0]
    assert count == 3
    assert first == second


def test_the_corpus_hash_changes_when_policy_text_changes():
    conn = connect(":memory:")
    init_schema(conn)
    before = index_policies(conn, chunk_policy_text(LEAVE), BagOfWordsEmbedder())
    after = index_policies(
        conn, chunk_policy_text(LEAVE.replace("sixty", "ninety")), BagOfWordsEmbedder()
    )

    assert before != after


def test_a_keyword_query_finds_the_matching_section_first(indexed):
    hits = search(indexed, "notice period")

    assert hits[0].section_id == "POL-A §1"


def test_hits_carry_what_the_agent_needs_to_cite(indexed):
    hit = search(indexed, "carry forward annual leave")[0]

    assert hit.section_id == "POL-A §2"
    assert hit.clause_ids == ("POL-A §2.1",)
    assert (hit.policy_id, hit.version, hit.title) == ("POL-A", "1.0", "Carry Forward")
    assert "ten days" in hit.text


def test_results_can_be_limited_to_one_policy(indexed):
    hits = search(indexed, "reported", policy_id="POL-B")

    assert {h.policy_id for h in hits} == {"POL-B"}


def test_the_number_of_results_is_capped(indexed):
    assert len(search(indexed, "policy notice leave gifts", k=2)) <= 2


@pytest.mark.parametrize(
    "query", ['"notice" OR (period) *', "NEAR(a b)", "col:umn -x", "'; DROP TABLE policy_chunks;--"]
)
def test_search_syntax_in_the_query_never_breaks_search(indexed, query):
    search(indexed, query)  # must not raise

    assert indexed.execute("SELECT count(*) FROM policy_chunks").fetchone()[0] == 3


def test_an_empty_query_returns_nothing(indexed):
    assert search(indexed, "   ") == []


def test_reindexing_removes_sections_that_no_longer_exist(indexed):
    index_policies(indexed, chunk_policy_text(LEAVE), BagOfWordsEmbedder())

    hits = search(indexed, "gifts vendors reported")

    assert all(h.policy_id != "POL-B" for h in hits)

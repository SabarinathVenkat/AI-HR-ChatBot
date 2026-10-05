"""Hybrid policy search: keyword (FTS5/BM25) plus vector, merged with reciprocal rank fusion."""
import json
import re
import sqlite3
from dataclasses import dataclass

import sqlite_vec

from app.rag.embeddings import QUERY_PREFIX, Embedder

CANDIDATES = 50  # the whole corpus is small; this covers it so similarity is always known
RRF_K = 60
# Precision-first gate for "the policies do not cover this". Chosen on the dev question set
# (eval/retrieval_questions.py): answerable questions scored 0.668 or more, unanswerable 0.641 or
# less. A held-out check showed one false decline (0.634), which is the safe failure direction.
SIMILARITY_THRESHOLD = 0.655
# Below the confident gate but above this, sections are still handed to the model, flagged as weak
# matches. Evaluation showed that the model's own rephrasings of a question score 0.53 to 0.63
# even when the policy does answer it, while the model reliably says "not found" when weak
# sections do not directly answer. Below this value nothing is returned.
WEAK_SIMILARITY_THRESHOLD = 0.50
STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i if in is it me my of on or the "
    "to what when where which who will with you your".split()
)


@dataclass(frozen=True)
class SearchHit:
    chunk_id: int
    policy_id: str
    policy_title: str
    version: str
    effective_date: str
    section_id: str
    title: str
    text: str
    clause_ids: tuple[str, ...]
    score: float  # fused rank score, only meaningful for ordering
    similarity: float | None  # cosine similarity to the query, 0..1, None if not in the vector list


@dataclass(frozen=True)
class Retrieval:
    """What a tool needs to search the policies: the embedder and the confidence gate."""

    embedder: Embedder
    threshold: float = SIMILARITY_THRESHOLD
    weak_threshold: float = WEAK_SIMILARITY_THRESHOLD


def is_confident(hits: list[SearchHit], threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """True when at least one hit is semantically close enough to the question to answer from."""
    return any(h.similarity is not None and h.similarity >= threshold for h in hits)


def _keyword_query(query: str) -> str | None:
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in STOPWORDS]
    if not tokens:
        return None
    # Each token is quoted, so FTS operators in user text are treated as plain words.
    return " OR ".join(f'"{t}"' for t in tokens)


def _keyword_ranks(conn: sqlite3.Connection, query: str) -> dict[int, int]:
    match = _keyword_query(query)
    if match is None:
        return {}
    rows = conn.execute(
        "SELECT rowid FROM policy_fts WHERE policy_fts MATCH ? ORDER BY bm25(policy_fts, 5.0, 1.0)"
        " LIMIT ?",
        (match, CANDIDATES),
    ).fetchall()
    return {row[0]: rank for rank, row in enumerate(rows, start=1)}


def _vector_ranks(
    conn: sqlite3.Connection, query: str, embedder: Embedder
) -> tuple[dict[int, int], dict[int, float]]:
    (vector,) = embedder.embed([QUERY_PREFIX + query])
    rows = conn.execute(
        "SELECT rowid, distance FROM policy_vec WHERE embedding MATCH ? AND k = ?",
        (sqlite_vec.serialize_float32(vector), CANDIDATES),
    ).fetchall()
    ranks = {row[0]: rank for rank, row in enumerate(rows, start=1)}
    similarity = {row[0]: 1.0 - row[1] for row in rows}
    return ranks, similarity


def search_policy(
    conn: sqlite3.Connection,
    query: str,
    embedder: Embedder,
    k: int = 5,
    policy_id: str | None = None,
) -> list[SearchHit]:
    if not query.strip():
        return []
    keyword = _keyword_ranks(conn, query)
    vector, similarity = _vector_ranks(conn, query, embedder)
    fused: dict[int, float] = {}
    for ranks in (keyword, vector):
        for chunk_id, rank in ranks.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)

    hits: list[SearchHit] = []
    for chunk_id, score in sorted(fused.items(), key=lambda item: item[1], reverse=True):
        row = conn.execute("SELECT * FROM policy_chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if row is None or (policy_id and row["policy_id"] != policy_id):
            continue
        hits.append(
            SearchHit(
                chunk_id=chunk_id,
                policy_id=row["policy_id"],
                policy_title=row["policy_title"],
                version=row["version"],
                effective_date=row["effective_date"],
                section_id=row["section_id"],
                title=row["title"],
                text=row["text"],
                clause_ids=tuple(json.loads(row["clause_ids"])),
                score=score,
                similarity=similarity.get(chunk_id),
            )
        )
        if len(hits) == k:
            break
    return hits

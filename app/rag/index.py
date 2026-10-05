"""Build the policy search index. Rebuilding is idempotent: it replaces the whole index."""
import hashlib
import json
import sqlite3

import sqlite_vec

from app.rag.chunker import Chunk
from app.rag.embeddings import Embedder


def corpus_hash(chunks: list[Chunk]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda c: c.section_id):
        digest.update(f"{chunk.section_id}|{chunk.version}|{chunk.text}".encode("utf-8"))
    return digest.hexdigest()


def index_policies(conn: sqlite3.Connection, chunks: list[Chunk], embedder: Embedder) -> str:
    """Replace the index with `chunks`. Returns the corpus hash, recorded in traces."""
    vectors = embedder.embed([f"{c.policy_title}. {c.title}. {c.text}" for c in chunks])
    try:
        conn.execute("DELETE FROM policy_chunks")
        conn.execute("DELETE FROM policy_fts")
        conn.execute("DELETE FROM policy_vec")
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk_id = conn.execute(
                "INSERT INTO policy_chunks (policy_id, policy_title, section_id, clause_ids,"
                " title, text, version, effective_date) VALUES (?,?,?,?,?,?,?,?)",
                (
                    chunk.policy_id,
                    chunk.policy_title,
                    chunk.section_id,
                    json.dumps(chunk.clause_ids),
                    chunk.title,
                    chunk.text,
                    chunk.version,
                    chunk.effective_date,
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO policy_fts (rowid, title, text) VALUES (?, ?, ?)",
                (chunk_id, chunk.title, chunk.text),
            )
            conn.execute(
                "INSERT INTO policy_vec (rowid, embedding) VALUES (?, ?)",
                (chunk_id, sqlite_vec.serialize_float32(vector)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return corpus_hash(chunks)

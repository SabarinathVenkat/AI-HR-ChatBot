"""Prepare a database for use: schema, demo data and the policy index. Safe to run repeatedly."""
import logging
from pathlib import Path

from app.api.security import hash_password
from app.db.connection import connect, init_schema
from app.db.seed import SEED_AS_OF, seed
from app.rag.chunker import load_policy_dir
from app.rag.embeddings import Embedder
from app.rag.index import index_policies

log = logging.getLogger(__name__)
POLICY_DIR = Path(__file__).resolve().parents[1] / "data" / "policies"


def bootstrap(
    db_path: str | Path,
    embedder: Embedder,
    demo_data: bool = True,
    reindex: bool = False,
    policy_dir: Path = POLICY_DIR,
) -> None:
    conn = connect(str(db_path))
    try:
        init_schema(conn)
        if demo_data and conn.execute("SELECT count(*) FROM employees").fetchone()[0] == 0:
            log.info("seeding demo data")
            seed(conn, as_of=SEED_AS_OF, hash_password=hash_password)
        if reindex or conn.execute("SELECT count(*) FROM policy_chunks").fetchone()[0] == 0:
            chunks = load_policy_dir(policy_dir)
            log.info("indexing %d policy sections", len(chunks))
            index_policies(conn, chunks, embedder)
    finally:
        conn.close()

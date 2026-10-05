"""Sanity check that the retrieval dependencies work on this machine."""
import sqlite3

import sqlite_vec

conn = sqlite3.connect(":memory:")
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)
print("sqlite-vec", conn.execute("select vec_version()").fetchone()[0])

conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
conn.execute("INSERT INTO t VALUES ('notice period is sixty days')")
print("fts5 match:", conn.execute("SELECT count(*) FROM t WHERE t MATCH 'notice'").fetchone()[0])

from fastembed import TextEmbedding  # noqa: E402

model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir="models_cache")
vector = next(iter(model.embed(["How long is the notice period?"])))
print("embedding dimensions:", len(vector))

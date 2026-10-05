"""Look inside the learning database. A tiny stand-in for the sqlite3 command-line tool.

    python scripts/db.py                       # list the tables and how many rows each has
    python scripts/db.py "SELECT * FROM leave_requests"
    python scripts/db.py learning.db "SELECT name, role FROM employees"   # pick a different file

Read-only: it refuses anything except SELECT, so you can explore without breaking anything.
"""
import sqlite3
import sys

args = sys.argv[1:]
path = args.pop(0) if args and args[0].endswith(".db") else "learning.db"
query = args[0] if args else None

conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)  # mode=ro opens the file read-only
conn.row_factory = sqlite3.Row

if query is None:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'policy_fts%' AND name NOT LIKE 'policy_vec%' ORDER BY name")]
    print(f"{path}: {len(tables)} tables")
    for name in tables:
        print(f"  {name:<28} {conn.execute(f'SELECT count(*) FROM {name}').fetchone()[0]:>5} rows")
    sys.exit(0)

if not query.lstrip().lower().startswith("select"):
    sys.exit("Only SELECT queries are allowed here.")

rows = conn.execute(query).fetchall()
if not rows:
    print("(no rows)")
    sys.exit(0)
columns = rows[0].keys()
widths = [min(40, max(len(c), *(len(str(r[c])) for r in rows))) for c in columns]
print("  ".join(c.ljust(w) for c, w in zip(columns, widths, strict=True)))
print("  ".join("-" * w for w in widths))
for r in rows:
    print("  ".join(str(r[c])[:w].ljust(w) for c, w in zip(columns, widths, strict=True)))
print(f"\n{len(rows)} row(s)")

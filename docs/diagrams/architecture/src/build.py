import importlib
import pathlib
import sys

here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(here))
out = here.parent

MODULES = sys.argv[1:] or ["d01_overview", "d02_agent_graph", "d03_deep_agents", "d04_rag", "d05_security_data", "d06_full_zoned"]
FILES = {
    "d01_overview": "01-overview.html",
    "d02_agent_graph": "02-agent-graph.html",
    "d03_deep_agents": "03-deep-agents-path.html",
    "d04_rag": "04-rag-pipeline.html",
    "d05_security_data": "05-security-and-data.html",
    "d06_full_zoned": "architecture-full-zoned.html",
}
bad = 0
for m in MODULES:
    try:
        mod = importlib.import_module(m)
    except ModuleNotFoundError as e:
        print("skip", m, e)
        continue
    d = mod.build()
    warns = d.check()
    (out / FILES[m]).write_text(d.html(), encoding="utf-8")
    print("%-22s nodes=%-3d conns=%-3d warnings=%d" % (FILES[m], len(d.nodes), len(d.conns), len(warns)))
    for w in warns:
        print("   WARN", w)
    bad += len(warns)
print("total warnings:", bad)

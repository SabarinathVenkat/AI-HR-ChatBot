from dd import Diagram

LEGEND = [
    ("node", "focal", "Confidence gate"),
    ("node", "store", "Index"),
    ("node", "external", "LLM"),
    ("node", "input", "Input"),
    ("node", "optional", "Not-found path"),
    ("line", "default", "Data flow"),
    ("line", "default-dashed", "Optional"),
]


def build():
    d = Diagram(
        "hr-rag-pipeline", 1280, 720,
        "Policy RAG: indexing and cited answers",
        "Data flow · RAG pipeline",
        "Two flows: offline indexing turns policy markdown into chunks, local embeddings and a SQLite index; "
        "online queries run hybrid keyword and vector search, merge the two rankings, apply a confidence gate, then "
        "either say nothing was found or hand the sections to Claude, which cites them as text.",
        [
            "Offline, the policy files are split by section heading, each section becomes one chunk with its policy ID, "
            "version, effective date and clause ids, and each chunk is embedded locally with bge-small. Text, keyword index "
            "and vectors live in the same SQLite file.",
            "Online, a question searches keywords and vectors in parallel, takes the top 50 of each, and merges them by "
            "reciprocal rank fusion into the top five. There is no reranker, because with about 50 sections it was not needed. "
            "The best vector similarity then sets one of three tiers: confident (0.655 or more), weak match (0.50 to 0.655, "
            "up to three sections, flagged), or nothing (below 0.50), in which case the agent says it could not find "
            "the answer and gives the HR contact.",
            "The model writes citations such as POL-02 §5.4 as plain text, and the verifier later checks that each citation "
            "was really retrieved in that turn.",
        ],
        LEGEND,
    )
    d.zone(32, 108, 1216, 144, "OFFLINE INDEXING")
    d.zone(32, 388, 1216, 252, "ONLINE QUERY")
    xs = [48, 296, 544, 792, 1040]
    f = d.node("f", xs[0], 144, 192, 64, "Policy files", "8 markdown docs + front matter", "DATA", "input")
    c = d.node("c", xs[1], 144, 192, 64, "Chunker", "one chunk per ## section", "STEP")
    e = d.node("e", xs[2], 144, 192, 64, "Embeddings", "bge-small-en-v1.5 · local", "STEP")
    s = d.node("s", xs[3], 144, 192, 64, "SQLite index", "FTS5 + sqlite-vec (384-d)", "STORE", "store")
    q = d.node("q", xs[0], 424, 192, 64, "Question", "from the search_policy tool", "IN", "input")
    h = d.node("h", xs[1], 424, 192, 64, "Hybrid search", "FTS5 top 50 + vectors top 50", "STEP")
    r = d.node("r", xs[2], 424, 192, 64, "Fuse (RRF)", "merge two lists · top 5", "STEP")
    g = d.node("g", xs[3], 416, 192, 80, "Confidence tiers", ["0.655+ confident", "0.50 to 0.655 weak match"], "GATE", "focal")
    a = d.node("a", xs[4], 424, 192, 64, "Claude answers", "citations checked by verifier", "LLM", "external")
    n = d.node("n", xs[3], 548, 192, 64, "Not found", "say so + HR contact", "DECLINE", "optional")

    d.conn([f.right(), c.left()], "f", "c", "PARSE")
    d.conn([c.right(), e.left()], "c", "e", "EMBED")
    d.conn([e.right(), s.left()], "e", "s", "WRITE")
    d.conn([s.bottom(), (888, 312), (392, 312), h.top()], "s", "h", "READ INDEX", seg=1, style="link")
    d.conn([q.right(), h.left()], "q", "h", "TEXT")
    d.conn([h.right(), r.left()], "h", "r", "2 LISTS")
    d.conn([r.right(), g.left()], "r", "g", "TOP 5")
    d.conn([g.right(), a.left()], "g", "a", "SECTIONS")
    d.conn([g.bottom(), n.top()], "g", "n", "BELOW 0.50", dashed=True)
    return d

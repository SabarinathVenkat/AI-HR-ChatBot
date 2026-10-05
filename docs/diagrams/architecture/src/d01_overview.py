from dd import Diagram

LEGEND = [
    ("node", "focal", "Focal: agent core"),
    ("node", "backend", "Service"),
    ("node", "store", "Data store"),
    ("node", "external", "External API"),
    ("node", "optional", "Conditional / optional"),
    ("line", "default", "Call / data"),
    ("line", "default-dashed", "Optional / async"),
]


def build():
    d = Diagram(
        "hr-overview", 1280, 720,
        "HR Chat Agent: system overview",
        "Architecture · Overview",
        "Architecture overview of the HR Chat Agent: a web UI and API gateway feed a LangGraph agent that "
        "uses scoped tools, policy retrieval and an optional read-only Deep Agents planning path over one SQLite "
        "database, with Claude models behind it and a trace id, audit log and evaluation suite alongside.",
        [
            "Employees, managers and HR admins use a custom web app. Every request goes through the API gateway, which "
            "checks the login token, applies rate limits and attaches the verified employee ID.",
            "The LangGraph agent decides what each question needs. Policy questions go to retrieval, personal data and "
            "calculations go to ten scoped tools built on tested leave rules, and multi-step planning requests go to a "
            "read-only Deep Agents path with two sub-agents.",
            "One SQLite database holds HR data, leave drafts, policy chunks, the audit log and conversation state. Claude "
            "Sonnet writes answers and Claude Haiku routes. A per-request trace id, the audit log and an evaluation "
            "suite watch the system.",
        ],
        LEGEND,
    )
    ui = d.node("ui", 40, 304, 152, 64, "Users + Web UI", "employee · manager · HR", "UI", "input")
    gw = d.node("gw", 264, 304, 152, 64, "FastAPI gateway", "JWT · rate limit · SSE", "API")
    ag = d.node("ag", 496, 288, 184, 96, "LangGraph agent", ["router · verify loop", "Sonnet answers"], "CORE", "focal")
    da = d.node("da", 792, 128, 184, 64, "Deep Agents path", "plan · 2 sub-agents", "PLAN", "optional")
    tl = d.node("tl", 792, 304, 184, 64, "Tools + leave rules", "10 scoped tools · R1-R10", "TOOLS")
    rg = d.node("rg", 792, 480, 184, 64, "Policy RAG", "FTS5 + vectors · cited", "RAG")
    db = d.node("db", 1048, 288, 168, 96, "SQLite", ["HR data · chunks", "drafts · audit · state"], "STORE", "store")
    cl = d.node("cl", 1048, 128, 168, 64, "Claude API", "sonnet-5-5 · haiku-4-5", "LLM", "external")
    ob = d.node("ob", 496, 592, 184, 64, "Trace id + eval", "audit_log · eval · CI", "OPS", "optional")

    d.conn([ui.right(), gw.left()], "ui", "gw", "HTTPS+JWT")
    d.conn([gw.right(), (496, 336)], "gw", "ag", "CHAT + ID")
    # agent right edge fan: 312 / 336 / 360
    d.conn([(680, 312), (736, 312), (736, 160), da.left()], "ag", "da", label=None)
    d.conn([(680, 336), tl.left()], "ag", "tl", "TOOL CALLS")
    d.conn([(680, 360), (736, 360), (736, 512), rg.left()], "ag", "rg")
    d.conn([ag.top(), (588, 88), (1132, 88), cl.top()], "ag", "cl", "LLM CALLS", seg=1, style="link")
    d.conn([da.right(), cl.left()], "da", "cl", "LLM", style="link", dashed=True)
    d.conn([da.bottom(), tl.top()], "da", "tl", "READ-ONLY", dashed=True)
    d.conn([tl.right(), (1048, 336)], "tl", "db", "SQL")
    d.conn([rg.right(), (1012, 512), (1012, 360), (1048, 360)], "rg", "db", "READ", seg=1)
    d.conn([ag.bottom(), ob.top()], "ag", "ob", "TRACES", dashed=True)
    return d

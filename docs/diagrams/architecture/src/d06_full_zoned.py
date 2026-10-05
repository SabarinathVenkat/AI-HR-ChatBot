from dd import Diagram

LEGEND = [
    ("node", "focal", "Accuracy gate"),
    ("node", "security", "User confirmation"),
    ("node", "backend", "Service / logic"),
    ("node", "store", "Data store"),
    ("node", "external", "External API"),
    ("node", "optional", "Conditional / ops"),
    ("node", "input", "User / entry"),
    ("line", "default", "Call / data"),
    ("line", "link", "LLM call"),
    ("line", "default-dashed", "Trace / audit / retry"),
]


def build():
    d = Diagram(
        "hr-architecture-full", 1776, 1160,
        "HR Chat Agent: full system architecture by layer",
        "Architecture · Full zoned view",
        "Layered architecture of the HR Chat Agent as built: web client, API gateway, LangGraph agent with verifier, "
        "a read-only Deep Agents planning path, ten tools and domain rules, policy retrieval, SQLite data stores, "
        "Anthropic models, and trace id, evaluation and CI.",
        [
            "Read it top to bottom. Employees, managers and HR admins use the web app, and every request passes JWT login, a rate "
            "limit and security headers in the gateway, which attaches the verified employee ID.",
            "The LangGraph agent runs an input guardrail, a Haiku-tier router labels the intent, and plain code picks the route. "
            "The normal route is a tool loop where Claude Sonnet calls up to five tools and drafts a cited answer that the "
            "verifier checks before it streams back. Multi-step planning requests go to a read-only Deep Agents path with "
            "two sub-agents. Submitting leave is a separate endpoint that only the employee's click reaches.",
            "Below the agent, tools call pure leave rules and parameterized repositories, and policy questions use hybrid "
            "search with confidence tiers. All data sits in one SQLite file. A per-request trace id, the audit log, the "
            "evaluation suite and a CI workflow watch the system. For readability, the planner's own model calls, the deep-path "
            "result returning to the verifier and the web app's confirm click are described here rather than drawn.",
        ],
        LEGEND,
        wide=True,
    )
    # ---- zones (layers)
    d.zone(48, 48, 536, 116, "CLIENT")
    d.zone(912, 48, 248, 116, "EXTERNAL · ANTHROPIC")
    d.zone(48, 220, 824, 116, "API GATEWAY · FASTAPI")
    d.zone(48, 392, 1400, 236, "LANGGRAPH AGENT · CORE", 148)
    d.zone(48, 684, 432, 116, "DEEP AGENTS PATH", 132)
    d.zone(512, 684, 480, 236, "TOOLS + DOMAIN", 180)
    d.zone(1024, 684, 424, 116, "POLICY RAG")
    d.zone(512, 976, 936, 116, "DATA STORES · SQLITE", 132)
    d.zone(1480, 392, 256, 244, "TRACE · EVAL · CI")

    # ---- tier 1
    us = d.node("us", 64, 84, 216, 64, "Employee · Manager · HR", "role comes from the JWT claim", "USER", "input")
    ui = d.node("ui", 352, 84, 216, 64, "Web UI (custom)", "chat · citations · steps · confirm", "UI")
    an = d.node("an", 928, 84, 216, 64, "Anthropic API", "sonnet-5-5 · haiku-4-5", "LLM", "external")
    # ---- tier 2
    gd = d.node("gd", 64, 256, 216, 64, "Rate limit + headers", "30/min · CSP · nosniff", "GUARD")
    jw = d.node("jw", 352, 256, 216, 64, "JWT auth", "argon2 · 60 min · lockout 5/10", "AUTH")
    sm = d.node("sm", 640, 256, 216, 64, "SSE stream + trace_id", "steps live · verified answer", "API")
    # ---- tier 3
    it = d.node("it", 64, 428, 216, 64, "guardrail", "length · injection flag", "NODE")
    rt = d.node("rt", 352, 428, 216, 64, "router", "Haiku · intent · confidence", "LLM")
    br = d.node("br", 640, 428, 216, 64, "route choice", "plain code · 5 routes", "NODE")
    cp = d.node("cp", 928, 428, 216, 64, "agent ⇄ tools", "Sonnet · max 5 calls · draft", "LLM")
    vf = d.node("vf", 1216, 428, 216, 64, "verify", "numbers · citations · fallback", "CHECK", "focal")
    lv = d.node("lv", 1216, 548, 216, 64, "Confirm endpoint", "user click · model cannot call", "HUMAN", "security")
    # ---- tier 4
    pl = d.node("pl", 64, 720, 184, 64, "Deep planner", "todo · 12 calls · 22 s", "PLAN", "optional")
    sb = d.node("sb", 280, 720, 184, 64, "2 sub-agents", "policy · leave calculator", "SUB", "optional")
    tl = d.node("tl", 528, 720, 216, 64, "10 tools + ToolContext", "identity injected server-side", "TOOLS")
    dm = d.node("dm", 528, 840, 200, 64, "Domain layer", "calendar · accrual · R1-R10 · pure", "RULES")
    rp = d.node("rp", 776, 840, 200, 64, "Repositories", "parameterized SQL · scoped", "SQL")
    ix = d.node("ix", 1040, 720, 184, 64, "Index pipeline", "chunk · bge-small · FTS5+vec", "RAG")
    sr = d.node("sr", 1256, 720, 176, 64, "Hybrid search", "RRF · 3 confidence tiers", "RAG")
    # ---- tier 5
    au = d.node("au", 528, 1012, 200, 64, "audit_log + checkpoints", "calls · writes · chat history", "STORE", "store")
    hr = d.node("hr", 776, 1012, 200, 64, "HR tables", "balances · requests · drafts", "STORE", "store")
    ch = d.node("ch", 1256, 1012, 176, 64, "policy_chunks", "FTS5 + sqlite-vec 384-d", "STORE", "store")
    # ---- ops column
    ob = d.node("ob", 1496, 428, 224, 64, "Trace id + logs", "per-request trace_id · plain logs", "OPS", "optional")
    ev = d.node("ev", 1496, 548, 224, 64, "Evaluation + CI", ["120 dev · 30 held-out · 30 red-team", "Docker · CI workflow (not yet run)"], None, "optional")

    # ---- connectors
    d.conn([us.right(), ui.left()], "us", "ui", "CHAT")
    d.conn([(424, 148), (424, 256)], "ui", "jw", "HTTPS")
    d.conn([jw.left(), gd.right()], "jw", "gd", "TOKEN OK")
    d.conn([(172, 320), (172, 428)], "gd", "it", "ID INJECTED")
    d.conn([(280, 460), (352, 460)], "it", "rt", "CONTEXT")
    d.conn([(568, 460), (640, 460)], "rt", "br", "INTENT")
    d.conn([(856, 460), (928, 460)], "br", "cp", "AGENT")
    d.conn([(1144, 448), (1216, 448)], "cp", "vf", "DRAFT")
    d.conn([(1216, 472), (1144, 472)], "vf", "cp", "REWRITE x2", dashed=True, side="below")
    d.conn([(424, 492), (424, 644), (156, 644), (156, 720)], "rt", "pl", "complex_plan", seg=1)
    d.conn([(424, 428), (424, 348), (1000, 348), (1000, 164)], "rt", "an", "HAIKU", seg=1, style="link")
    d.conn([(1072, 428), (1072, 164)], "cp", "an", "SONNET", style="link")
    d.conn([(1324, 428), (1324, 372), (748, 372), (748, 320)], "vf", "sm", "ANSWER", seg=1)
    d.conn([(748, 256), (748, 200), (496, 200), (496, 148)], "sm", "ui", "SSE", seg=1)
    d.conn([(1432, 460), (1496, 460)], "vf", "ob", "TRACES", dashed=True)
    d.conn([(1608, 548), (1608, 492)], "ev", "ob", "REPORTS")
    d.conn([(984, 492), (984, 660), (600, 660), (600, 720)], "cp", "tl", "TOOLS", seg=1)
    d.conn([(1072, 492), (1072, 644), (1344, 644), (1344, 720)], "cp", "sr", "POLICY", seg=1)
    d.conn([(1216, 580), (1008, 580), (1008, 872), (976, 872)], "lv", "rp", "SUBMIT", seg=0)
    d.conn([pl.right(), sb.left()], "pl", "sb")
    d.conn([sb.right(), tl.left()], "sb", "tl", "READ-ONLY")
    d.conn([(600, 784), (600, 840)], "tl", "dm", "RULES")
    d.conn([(744, 752), (876, 752), (876, 840)], "tl", "rp", "SQL")
    d.conn([(844, 904), (844, 1012)], "rp", "hr", "SCOPED")
    d.conn([(776, 872), (752, 872), (752, 940), (628, 940), (628, 1012)], "rp", "au", "AUDIT", seg=2, dashed=True)
    d.conn([(1344, 784), (1344, 1012)], "sr", "ch", "QUERY")
    d.conn([(1132, 784), (1132, 880), (1284, 880), (1284, 1012)], "ix", "ch", "WRITE", seg=1)
    return d

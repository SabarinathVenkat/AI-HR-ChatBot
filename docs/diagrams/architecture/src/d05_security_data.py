from dd import Diagram

LEGEND = [
    ("node", "focal", "Pure domain rules"),
    ("node", "security", "Trust enforcement"),
    ("node", "store", "Data store"),
    ("node", "external", "Untrusted model"),
    ("node", "input", "Verified input"),
    ("line", "default", "Call / data"),
    ("line", "default-dashed", "Audit write"),
]


def build():
    d = Diagram(
        "hr-security-data", 1120, 680,
        "Identity, tools, domain rules and data: the trust boundary",
        "Architecture · Security and data",
        "How identity and data are protected: the model proposes a tool call without any identity, the server "
        "injects the verified employee ID from the token, tools call pure domain rules and parameterized "
        "repositories, and every call is written to an audit log.",
        [
            "The model is treated as untrusted. It can suggest a tool and its arguments, such as dates or a leave type, but the "
            "tool schemas contain no employee ID or role, and unknown arguments are rejected. The server adds identity from the "
            "verified login token, and offers each role only its own tools. The model can prepare a leave draft but cannot "
            "submit it: only the employee's confirmation does.",
            "Tools call two things: pure domain rules (working days, accrual, eligibility R1 to R10) that never touch the "
            "database or the clock, and repositories that run parameterized SQL filtered by employee or manager ID. "
            "A manager can only ever see direct reports because the filter is in the query itself.",
            "Every tool call and every write is recorded in an audit log with the user, inputs, outputs and trace ID.",
        ],
        LEGEND,
    )
    d.zone(288, 104, 752, 508, "TRUSTED SERVER SIDE")
    llm = d.node("llm", 48, 136, 192, 64, "Claude tool call", "args only: dates, leave type", "LLM", "external")
    jwt = d.node("jwt", 48, 328, 192, 64, "JWT claims", "sub = employee_id · role", "AUTH", "input")
    tl = d.node("tl", 320, 136, 192, 64, "Ten tools", "role-filtered · no identity", "TOOLS")
    tc = d.node("tc", 320, 328, 192, 64, "ToolContext", "injected server-side", "GUARD", "security")
    dm = d.node("dm", 576, 124, 200, 96, "Domain layer", ["calendar · accrual", "eligibility R1-R10", "pure · no I/O · no clock"], "RULES", "focal")
    rp = d.node("rp", 576, 328, 200, 64, "Repositories", "WHERE employee_id / manager_id", "SQL")
    hr = d.node("hr", 832, 328, 184, 64, "HR tables", "balances · requests · drafts", "STORE", "store")
    au = d.node("au", 576, 488, 200, 64, "audit_log", "user · inputs · outputs · trace", "STORE", "store")

    d.conn([llm.right(), tl.left()], "llm", "tl", "ARGS ONLY", style="link")
    d.conn([jwt.right(), tc.left()], "jwt", "tc", "VERIFIED")
    d.conn([tc.top(), tl.bottom()], "tc", "tl", "ID + ROLE")
    d.conn([(512, 156), (576, 156)], "tl", "dm", "RULES")
    d.conn([(512, 180), (544, 180), (544, 360), (576, 360)], "tl", "rp", "QUERY", seg=1)
    d.conn([rp.right(), hr.left()], "rp", "hr", "PARAMS")
    d.conn([rp.bottom(), au.top()], "rp", "au", "EVERY CALL", dashed=True)
    return d

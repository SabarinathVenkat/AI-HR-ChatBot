from dd import Diagram

LEGEND = [
    ("node", "focal", "Planner"),
    ("node", "security", "Safety boundary"),
    ("node", "backend", "Component"),
    ("node", "input", "Entry"),
    ("node", "optional", "Fallback"),
    ("line", "default", "Delegation / data"),
    ("line", "default-dashed", "Blocked or fallback"),
]


def build():
    d = Diagram(
        "hr-deep-agents", 1280, 720,
        "Deep Agents path: planning without write access",
        "Architecture · Deep Agents path",
        "How a multi-step request is handled: the router hands it to a Deep Agents planner that delegates to two "
        "sub-agents using read-only tools, the planner's answer goes through the same verifier, and if planning fails "
        "the request falls back to the normal tool loop. Write and shell tools are refused on this path.",
        [
            "Only requests the router labels as planning reach this path, for example comparing leave options around holidays. "
            "Simple questions never pay for planning, which is slower than the normal tool loop.",
            "The planner writes a short to-do list and delegates to two sub-agents: one reads policy, one does leave "
            "calculations. The sub-agents run on the faster Haiku model. They can only use read tools, with a shared budget of 12 "
            "tool calls, 3 sub-agent runs and 22 seconds, after which the planner must answer with what it has.",
            "The planner's answer passes the same verifier as every other answer and is shown as options only. It cannot "
            "prepare or submit a leave request: that tool is not offered, and the guard also refuses it, and the library's "
            "file and shell tools, at the moment they are called. If planning fails or returns nothing, the normal tool loop "
            "answers instead.",
        ],
        LEGEND,
    )
    rt = d.node("rt", 40, 336, 152, 64, "Router", "complex_plan or flag", "IN", "input")
    pl = d.node("pl", 264, 320, 200, 96, "Deep Agents planner", ["todo plan · Sonnet", "12 calls · 22 s", "3 sub-agent runs max"], "PLAN", "focal")
    s0 = d.node("s0", 568, 152, 192, 64, "policy_specialist", "Haiku · search_policy", "SUB")
    s1 = d.node("s1", 568, 336, 192, 64, "leave_calculator", "Haiku · balances · dates", "SUB")
    tl = d.node("tl", 864, 240, 184, 96, "Read-only tools", ["search_policy · hr contact", "balances · history · holidays", "calculate · check eligibility"], "TOOLS")
    bl = d.node("bl", 1112, 240, 128, 96, "Never available", ["prepare_leave_request", "file + shell tools"], None, "security")
    vf = d.node("vf", 864, 520, 184, 64, "verify", "same verifier as fast path", "CHECK")
    hf = d.node("hf", 1112, 520, 128, 64, "To employee", "nothing prepared", "OUT")
    fb = d.node("fb", 264, 588, 200, 64, "Normal tool loop", "if planning fails", "FALLBACK", "optional")

    d.conn([rt.right(), (264, 368)], "rt", "pl", "ROUTE")
    d.conn([(464, 344), (500, 344), (500, 184), s0.left()], "pl", "s0", seg=2, label=None)
    d.conn([(464, 368), s1.left()], "pl", "s1", "DELEGATE")
    d.conn([s0.right(), (812, 184), (812, 264), (864, 264)], "s0", "tl", "READ", seg=1)
    d.conn([s1.right(), (812, 368), (812, 312), (864, 312)], "s1", "tl", "CALC", seg=1)
    d.conn([tl.right(), bl.left()], "tl", "bl", "BLOCKED", dashed=True)
    d.conn([(396, 416), (396, 552), vf.left()], "pl", "vf", "ANSWER", seg=1)
    d.conn([(332, 416), (332, 588)], "pl", "fb", "FAILED", dashed=True)
    d.conn([vf.right(), hf.left()], "vf", "hf", "VERIFIED")
    return d

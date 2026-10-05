from dd import Diagram

LEGEND = [
    ("node", "focal", "Accuracy gate"),
    ("node", "backend", "Graph node"),
    ("node", "input", "Entry"),
    ("line", "default", "Flow"),
    ("line", "default-dashed", "Retry / fallback"),
]

ROUTES = [
    ("cd", "clarify / decline", "fixed replies, no model call", "low conf / out of scope"),
    ("rs", "respond", "chitchat: plain model reply", "chitchat"),
    ("sn", "sensitive", "fixed tools, short cited reply", "sensitive"),
    ("dp", "deep (Deep Agents)", "plan · 2 sub-agents · 22 s", "complex_plan"),
    ("ag", "agent ⇄ tools", "max 5 calls, then answer_now", "all other intents"),
]


def build():
    d = Diagram(
        "hr-agent-graph", 1472, 768,
        "LangGraph agent: nodes, routing and the verify loop",
        "Flowchart · Agent graph",
        "Flow of the LangGraph agent as built: the input guardrail runs, a router labels the intent, plain code "
        "picks one of five routes, every drafted answer goes through the verifier, a failed draft is rewritten up to "
        "twice and then replaced by a deterministic fallback, and the planning route falls back to the tool loop "
        "if it fails.",
        [
            "A message first passes the input guardrail, which checks its length and flags prompt-injection wording. A small "
            "Haiku-tier router then labels the intent with a confidence. A plain Python function, not the model, picks the "
            "route: ask for clarification, decline, answer small talk, handle a sensitive topic with fixed tools, plan with "
            "Deep Agents, or run the tool loop used for everything else.",
            "The tool loop lets the model call the tools its role allows, up to five calls, then forces an answer. If the "
            "planning route fails or returns nothing, the request falls back to this same tool loop. Clarify and decline "
            "replies are fixed text and go straight to finalize.",
            "Every drafted answer goes to the verifier, which checks numbers, dates, citations and names against the tool "
            "results. A failed draft is rewritten up to twice, then replaced by a plain answer built from the tool output. "
            "Submitting a leave request is not in this graph: the model can only prepare a draft, and the employee confirms "
            "it through a separate endpoint.",
        ],
        LEGEND,
        wide=True,
    )
    d.zone(40, 64, 160, 624, "INTAKE")
    d.zone(312, 240, 472, 440, "ROUTES")
    d.zone(808, 232, 640, 480, "CHECK AND ANSWER")

    ms = d.node("ms", 56, 96, 128, 48, "POST /chat", "identity from token", None, "input")
    gr = d.node("gr", 56, 176, 128, 48, "guardrail", "length · injection")
    rt = d.node("rt", 56, 272, 128, 384, "router", ["Haiku-tier", "structured intent", "needs_planning", "confidence"], "LLM", "backend", center=True)

    ys = [296 + 80 * i for i in range(len(ROUTES))]
    for (nid, name, sub, intent), y in zip(ROUTES, ys):
        d.node(nid, 336, y - 24, 192, 48, name, sub)

    vf = d.node("vf", 832, 344, 176, 312, "verify",
                ["numbers and dates", "citations retrieved", "no other names", "sentence cap"], "CHECK", "focal", center=True)
    rw = d.node("rw", 1072, 360, 176, 64, "rewrite", "names the exact problems", "LLM")
    fb = d.node("fb", 1072, 616, 176, 64, "fallback", "built from tool output", "CODE")
    fn = d.node("fn", 1288, 488, 144, 64, "finalize", ["final answer", "saved to history"])

    d.conn([ms.bottom(), gr.top()], "ms", "gr")
    d.conn([gr.bottom(), rt.top()], "gr", "rt")
    for (nid, name, sub, intent), y in zip(ROUTES, ys):
        d.conn([(184, y), (336, y)], "rt", nid, intent)
    # the four routes that draft an answer all pass through the verifier
    for (nid, name, sub, intent), y in zip(ROUTES[1:], ys[1:]):
        d.conn([(528, y), (832, y)], nid, "vf")
    d.conn([(528, ys[0]), (1360, ys[0]), (1360, 488)], "cd", "fn", "straight to finalize")
    d.conn([(432, ys[3] + 24), (432, ys[4] - 24)], "dp", "ag", "failed", dashed=True)

    d.conn([(1008, 520), (1288, 520)], "vf", "fn", "pass")
    d.conn([(1008, 392), (1072, 392)], "vf", "rw", "problems")
    d.conn([(1160, 360), (1160, 320), (920, 320), (920, 344)], "rw", "vf", "rewrite max 2", seg=1, dashed=True)
    d.conn([(1008, 648), (1072, 648)], "vf", "fb", "2 fails", dashed=True)
    d.conn([(1248, 648), (1360, 648), (1360, 552)], "fb", "fn", dashed=True)
    return d

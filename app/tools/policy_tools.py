"""Policy search tool. Returns nothing at all when the policies do not clearly cover the question."""
from pydantic import Field

from app.rag.search import is_confident, search_policy
from app.tools.context import ToolContext
from app.tools.registry import ToolArgs, tool

RESULTS = 5
WEAK_RESULTS = 3
NOT_FOUND = (
    "No policy section clearly covers this question. Say you could not find it in the HR "
    "policies and refer the employee to HR (use get_hr_contact)."
)
WEAK_MATCH = (
    "These sections are only weak matches. Use them only if one directly answers the question; "
    "if none does, say you could not find it in the HR policies and refer the employee to HR "
    "(use get_hr_contact). Never present a related but different rule as the answer."
)


class SearchPolicyArgs(ToolArgs):
    query: str = Field(max_length=500)
    policy_id: str | None = Field(default=None, max_length=20)


@tool(
    "search_policy",
    "Search the HR policy documents. Use it for any question about rules, entitlements, "
    "processes or benefits. Returns policy sections with their section ids, clause ids and "
    "text. Answer only from these sections and cite them by clause id (for example "
    "[POL-05 §3.1]). If it returns no results, the policies do not cover the question.",
    SearchPolicyArgs,
)
def search_policy_tool(ctx: ToolContext, args: SearchPolicyArgs) -> dict:
    if ctx.retrieval is None:
        return {"error": "Policy search is not configured."}
    hits = search_policy(
        ctx.conn, args.query, ctx.retrieval.embedder, k=RESULTS, policy_id=args.policy_id
    )
    confident = is_confident(hits, ctx.retrieval.threshold)
    weak = not confident and is_confident(hits, ctx.retrieval.weak_threshold)
    if not confident and not weak:
        return {"confident": False, "results": [], "message": NOT_FOUND}
    shown = hits if confident else hits[:WEAK_RESULTS]
    response = {
        "confident": confident,
        "results": [
            {
                "section_id": h.section_id,
                "policy_id": h.policy_id,
                "policy_title": h.policy_title,
                "title": h.title,
                "version": h.version,
                "effective_date": h.effective_date,
                "clause_ids": list(h.clause_ids),
                "similarity": round(h.similarity, 3) if h.similarity is not None else None,
                "text": h.text,
            }
            for h in shown
        ],
    }
    if weak:
        response["weak_match"] = True
        response["message"] = WEAK_MATCH
    return response

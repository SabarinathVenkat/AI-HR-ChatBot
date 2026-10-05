# Stack API notes (verified 2026-10-02)

All versions from PyPI JSON; snippets marked VERIFIED were run in a clean Python 3.12 venv on this Windows 11 box (fake chat model, no API key).

## 0. Python (critical)
- `python` on PATH = **3.9.13** (too old). `py -0` shows **3.12 (64-bit)** installed -> use `py -3.12 -m venv .venv`.
- requires-python: langgraph 1.2.12 >=3.10; langchain-anthropic 1.7.5 >=3.10; **deepagents 0.7.21 >=3.11**; fastembed 0.8.1 >=3.10; sentence-transformers 6.1.0 >=3.10; sqlite-vec none (wheels).
- On 3.9, `pip` silently resolves OLD versions (langgraph 0.6.11, langchain-anthropic 0.3.22) and deepagents is not found at all. Don't trust `pip index versions` from the default python.

## Pins (installed together without conflict on 3.12/Windows)
```
langgraph==1.2.12
langgraph-checkpoint-sqlite==3.1.1   # pulls langgraph-checkpoint 4.2.0, langgraph-prebuilt 1.1.0
langchain==1.4.3
langchain-core==1.6.6
langchain-anthropic==1.7.5           # anthropic 1.11.0
deepagents==0.7.21
sqlite-vec==0.1.9
fastembed==0.8.1                     # onnxruntime 1.30.0, numpy 2.5.3 (no torch)
# alt: sentence-transformers==6.1.0 (needs torch, heavy)
```

## 1. LangGraph 1.2.12
Sources: https://docs.langchain.com/oss/python/langgraph/interrupts , PyPI.
VERIFIED snippet (StateGraph + conditional routing + ToolNode + SqliteSaver + interrupt + resume + multi-mode stream):
```python
import sqlite3
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.sqlite import SqliteSaver      # pip: langgraph-checkpoint-sqlite
from langgraph.types import interrupt, Command

class S(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    ok: bool

g = StateGraph(S)
g.add_node("llm", llm_node); g.add_node("tools", ToolNode([lookup])); g.add_node("approve", approve)
g.add_edge(START, "llm")
g.add_conditional_edges("llm", tools_condition, {"tools": "tools", END: "approve"})
g.add_edge("tools", "llm"); g.add_edge("approve", END)

def approve(state):
    return {"ok": interrupt({"q": "approve?"})}   # returns resume value

conn = sqlite3.connect("ck.db", check_same_thread=False)
app = g.compile(checkpointer=SqliteSaver(conn))   # SqliteSaver.from_conn_string("ck.db") is a context manager
cfg = {"configurable": {"thread_id": "t1"}}
for mode, chunk in app.stream(inputs, cfg, stream_mode=["updates", "values"]): ...   # interrupt appears as updates {'__interrupt__': (Interrupt(...),)}
app.get_state(cfg).next            # ('approve',)
app.get_state(cfg).tasks[0].interrupts
app.invoke(Command(resume=True), cfg)   # same thread_id required
```
- Stream modes: values, updates, messages (LLM tokens), custom, debug (list allowed). Docs page now also shows a newer `stream_events(..., version="v3")` API with `.interrupted/.interrupts`; classic `stream()/invoke()` still works (verified).
- Interrupt gotchas (docs): node restarts from its start on resume; never wrap interrupt() in try/except; keep interrupt order stable; side effects before interrupt must be idempotent; async: use AsyncSqliteSaver (`langgraph.checkpoint.sqlite.aio`).
- `langgraph.prebuilt.create_react_agent` is superseded by `langchain.agents.create_agent` in langchain 1.x (docs show create_agent); ToolNode/tools_condition still in langgraph.prebuilt.
- ChatAnthropic: `from langchain_anthropic import ChatAnthropic; llm = ChatAnthropic(model="claude-sonnet-5-5", max_tokens=1024).bind_tools([lookup])` (constructor verified; needs ANTHROPIC_API_KEY at call time, not tested live).

## 2. Deep Agents 0.7.21 (package `deepagents`, py>=3.11)
Sources: https://github.com/langchain-ai/deepagents (libs/deepagents/deepagents/graph.py), https://docs.langchain.com/oss/python/deepagents/overview , .../subagents
Signature (from source):
```python
create_deep_agent(model=None, tools=None, *, system_prompt=None, middleware=(), subagents=None,
  skills=None, memory=None, permissions=None, backend=None, interrupt_on=None, response_format=None,
  state_schema=None, context_schema=None, checkpointer=None, store=None, debug=False, name=None, cache=None)
  -> CompiledStateGraph
```
- Model: pass `"anthropic:claude-sonnet-5-5"` or a `ChatAnthropic(...)` instance. `model=None` defaults to claude-sonnet-4-6 but is **deprecated** (removed in 1.0.0) -> always pass model explicitly.
- Built-in tools (VERIFIED by introspection): ls, read_file, write_file, edit_file, delete, glob, grep, execute, **task** (subagent delegation). **`write_todos` is NOT included by default in 0.7.21**; add it: `from langchain.agents.middleware import TodoListMiddleware; create_deep_agent(..., middleware=[TodoListMiddleware()])` -> adds `write_todos` (VERIFIED). Docs describe it as opt-in.
- Filesystem: `backend=` (default StateBackend = virtual in-state files; also local disk, store, composite). `execute` tool exists - restrict/avoid for an HR bot (use `permissions=[FilesystemPermission...]` / backend choice).
- Custom tools: plain callables with docstrings in `tools=[...]`.
- Subagents:
```python
sub = {"name": "policy-researcher", "description": "...when to delegate...",
       "system_prompt": "...", "tools": [search_policies], "model": "anthropic:claude-haiku-4-5"}  # also mode="isolated"|"fork", middleware, response_format, permissions
agent = create_deep_agent(model=..., tools=[...], subagents=[sub])
# or CompiledSubAgent(name=, description=, runnable=<graph with "messages" key>)
```
  A default `general-purpose` subagent is added automatically.
- HITL: `interrupt_on={"tool_name": True}` + a `checkpointer` (required).
- Step cap: compiled graph has `recursion_limit` config baked at **9_999**. Cap per call: `agent.invoke(inp, {"recursion_limit": 50, "configurable": {"thread_id": ...}})`. (Exceeding raises GraphRecursionError.) Passing config was accepted (VERIFIED with nesting).
- Embed in LangGraph (VERIFIED, runs):
```python
agent = create_deep_agent(model=..., tools=[...])
g = StateGraph(MessagesState); g.add_node("deep", agent)   # compiled graph as node; shares "messages" key
g.add_edge(START, "deep"); g.add_edge("deep", END); app = g.compile(checkpointer=...)
```
  Parent's checkpointer propagates to subgraph; recursion_limit in parent config applies. If state schemas differ, wrap in a function node that maps state in/out.
- Always adds AnthropicPromptCachingMiddleware, SummarizationMiddleware.

## 3. Anthropic models (https://platform.claude.com/docs/en/models/overview ; docs.anthropic.com 301s there)
| Tier | API ID | Price in/out per MTok | Ctx | Retirement |
|---|---|---|---|---|
| Sonnet 5.5 | `claude-sonnet-5-5` | $2 / $10 | 1M | not before 2027-09-28 |
| Haiku 4.5 | `claude-haiku-4-5` (snapshot `claude-haiku-4-5-20251001`) | $1 / $5 | 200K | **not before 2026-10-15 (2 weeks away)** |
| Opus 5.5 | `claude-opus-5-5` | $4 / $20 | 1M | 2027-09-22 |
| Fable 5.1 | `claude-fable-5-1` | $10 / $50 | 1M | 2027-09-01 |
- Legacy still available: Sonnet 5, Sonnet 4.6, Opus 5/4.x. Haiku 4.5 is still the newest Haiku; there is no Haiku 5. Plan a fallback (Sonnet 5.5) for the cheap tier.
- Sonnet 5.5 uses adaptive thinking, default effort `high` (set effort lower for cheap RAG turns).
- Citations / RAG: `search_result` content blocks are GA, **no beta header**, supported by all active models except Haiku 3 (https://platform.claude.com/docs/en/build-with-claude/search-results). Shape:
```json
{"type":"search_result","source":"policy/leave.md#s3","title":"Leave Policy","content":[{"type":"text","text":"..."}],"citations":{"enabled":true}}
```
  Pass as top-level user content blocks or inside a tool_result. Response text blocks carry `citations: [{"type":"search_result_location","cited_text","source","title","search_result_index","start_block_index","end_block_index"}]`. Set `citations.enabled` consistently on all results in a request. Via LangChain, these appear in AIMessage content blocks; pass raw dict blocks in the message content (not live-tested here - no API key).

## 4. sqlite-vec 0.1.9 + embeddings
VERIFIED on Windows/py3.12 (wheel installs, extension loads, KNN works):
```python
import sqlite3, sqlite_vec
from sqlite_vec import serialize_float32
db = sqlite3.connect("hr.db"); db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
db.execute("create virtual table v using vec0(embedding float[384] distance_metric=cosine)")
db.execute("insert into v(rowid, embedding) values (?, ?)", (1, serialize_float32(vec)))
db.execute("select rowid, distance from v where embedding match ? and k=5", (serialize_float32(q),)).fetchall()
```
- Use `match ... and k=N` (or `order by distance limit N`). Keep metadata in a normal table keyed by rowid. Pre-1.0 (alpha) API; pin version. Brute-force KNN, fine for HR-doc scale.
- Gotcha: `enable_load_extension` is missing in some Python builds (python.org Windows builds and the `py` 3.12 here have it - worked). Conda/pyenv/macOS system builds may lack it.
- fastembed (ONNX, no torch):
```python
from fastembed import TextEmbedding
m = TextEmbedding("BAAI/bge-small-en-v1.5")      # dim 384, VERIFIED
doc_vecs = [list(map(float, e)) for e in m.embed(texts)]
q = list(map(float, next(iter(m.query_embed("question")))))
```
  First run downloads ~130MB model from HF into a temp dir (default `%TEMP%\fastembed_cache`; set `cache_dir=` to persist, otherwise it can be wiped). Prints HF unauthenticated warning (harmless). Pass numpy float32 -> convert to list/`serialize_float32`.
- sentence-transformers 6.1.0 + `BAAI/bge-small-en-v1.5` also works but pulls torch (~2GB on Windows); prefer fastembed.

## Contradictions / surprises vs. likely earlier assumptions
1. Default `python` is 3.9.13: cannot run any of the current stack; must use `py -3.12`.
2. Versions are far past 0.x: langgraph 1.2.12, langchain 1.x, langchain-anthropic 1.7.5, checkpoint-sqlite 3.1.1 (not 2.x). Old tutorials (create_react_agent, langchain 0.3) are outdated.
3. deepagents has **no write_todos by default** in 0.7.21 and its model=None default (Sonnet 4.6) is deprecated; has `execute` tool by default.
4. Recursion limit default for deepagents is 9,999 - cap it explicitly.
5. Model IDs: Sonnet is 5.5 (`claude-sonnet-5-5`, no date suffix); Haiku remains 4.5, retirement no sooner than 2026-10-15.
6. search_result citations are GA with no beta header.

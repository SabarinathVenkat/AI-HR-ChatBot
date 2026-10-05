# Technical Design Document: HR Chat Agent

> **Status: design-time document, partly superseded.** Read [`ARCHITECTURE.md`](ARCHITECTURE.md)
> for the system as built. Main differences from this document: custom web UI instead of Chainlit;
> database drafts instead of a LangGraph `interrupt()` workflow; no reranker; text citations
> enforced by the verifier instead of native `search_result` blocks; two planning sub-agents; no
> OpenTelemetry/Langfuse, Docker or CI yet. The section 10 pins were verified later against the live
> API, so the note there that they were only run against a fake model is out of date.

| | |
|---|---|
| Version | 1.0 (draft) |
| Implements | `docs/PRD.md`, `docs/FSD.md` |
| Evidence | `research/framework-comparison.md`, `research/stack-api-notes.md` |
| Pins | Resolved in §10 from `research/stack-api-notes.md` (checked in a clean venv with a fake chat model, **not** yet against the live Anthropic API) |

## 1. Design Principles
1. **Deterministic where it matters.** Numbers, dates, eligibility and access control are plain code with tests. The model chooses tools and writes prose.
2. **Identity is never model input.** The verified token supplies `employee_id` and `role`. Tools receive them from the server.
3. **Grounded or silent.** Policy claims carry citations. No support means no claim.
4. **Fast path by default.** Planning machinery only runs when a request needs it.
5. **Writes need confirmation.** State-changing actions pause for the user, and are idempotent.
6. **Everything observable.** Every node, tool call and retrieval is traced and audited.
7. **Replaceable edges.** Policy files, model, embeddings and database sit behind small interfaces.

## 2. Technology Choices and Rationale
| Concern | Choice | Why | Alternatives considered |
|---|---|---|---|
| Agent orchestration | **LangGraph** | Explicit state graph, conditional routing, checkpointing, interrupt and resume for confirmation, streaming, highest overall score in research | Plain Anthropic tool loop (fastest, but we would hand-build checkpointing and resume), Pydantic AI, CrewAI, OpenAI Agents SDK |
| Planning path | **Deep Agents** (`deepagents`) | Built-in planning, sub-agents and context offloading for multi-step requests, built on LangGraph so it embeds cleanly | Hand-built planner |
| LLM | **Anthropic Claude**: Sonnet-tier for answers and planning, Haiku-tier for routing and classification **[PIN model IDs]** | Strong tool use and citation support, a cheap fast router | OpenAI, Gemini |
| API | **FastAPI** | Async, typed, SSE streaming, mature | Flask, Django |
| Database | **SQLite** (WAL mode) | Zero-setup for judges. Same SQL, so Postgres is a documented migration | Postgres |
| Vector and keyword search | **sqlite-vec** plus **FTS5** in the same database | One file, hybrid search without extra services | Chroma, Qdrant, pgvector |
| Embeddings | **Local small model (BGE-small via fastembed)** **[PIN]** | No second API key, works offline, good enough for a small corpus | Voyage (higher quality, needs key) |
| Reranking | Lightweight cross-encoder, or LLM-free score fusion if latency demands **[PIN]** | Improves top-5 precision | None |
| Auth | **JWT** (HS256 via env secret), **argon2** password hashing | Simple, standard, testable | Real SSO (out of scope) |
| UI | **Chainlit** | Chat UI with streaming, steps, and custom elements in a day | React (more polish, more time) |
| Tracing | **OpenTelemetry** to **Langfuse** (self-hostable) or local JSON logs **[PIN]** | Standard, shows reasoning steps | LangSmith |
| Evaluation | Custom golden-set runner, optional RAGAS or DeepEval metrics, **promptfoo** for red-team | Measured accuracy for the deck | None |
| Testing | **pytest**, **hypothesis** for date math, **freezegun** | Property tests suit calendar logic | unittest |
| Packaging | Docker, docker-compose, GitHub Actions CI | Reproducible, expected for production readiness | None |
| Language | Python 3.11+ **[PIN to the local version]** | Ecosystem fit | TypeScript |

Honest trade-off: LangGraph adds some latency and abstraction over a plain loop. We accept it for
checkpointed confirmation flows and for a visible, explainable graph, and we measure the
overhead in the evaluation.

## 3. System Context
```
Employee/Manager/HR ──HTTPS──► Chainlit UI ──► FastAPI ──► LangGraph agent
                                                   │            │
                                                   │            ├─► Anthropic API (Claude)
                                                   │            ├─► Tools ─► SQLite (HR data)
                                                   │            └─► Retrieval ─► SQLite (FTS5 + sqlite-vec)
                                                   └─► OTel ─► Langfuse / logs
```
The UI and API run in one process for the demo (Chainlit mounted on FastAPI) and can be split
later.

## 4. Component Design

### 4.1 Layers and dependency direction
```
api  ─►  agent  ─►  tools  ─►  domain  ◄─  db
              └──►  rag   ──►  db
```
- `domain/` holds pure logic with no I/O: leave calculation, eligibility rules, accrual, working days, models. It is the most heavily tested layer.
- `db/` holds repositories (SQL) that return domain objects.
- `tools/` are thin wrappers that bind identity, call domain and repositories, and write audit records.
- `agent/` holds the graph, router, prompts, verifier and the Deep Agents path.
- `rag/` handles chunking, indexing and hybrid search.
- `api/` handles routing, auth, rate limiting and streaming.

### 4.2 Project layout
```
app/
  config.py            settings from environment (pydantic-settings)
  domain/              calendar.py  accrual.py  eligibility.py  models.py
  db/                  schema.sql  repositories.py  seed.py  connection.py
  tools/               registry.py  leave_tools.py  policy_tools.py  manager_tools.py
  rag/                 chunker.py  index.py  search.py  embeddings.py
  agent/               graph.py  state.py  router.py  nodes.py  verifier.py
                       leave_workflow.py  deep_path.py  prompts/
  api/                 main.py  auth.py  deps.py  ratelimit.py  routes_*.py
  observability/       tracing.py  audit.py  logging.py
  ui/                  chainlit_app.py
data/                  policies/  seed/
eval/                  golden_questions.yaml  run_eval.py  redteam.yaml
tests/                 unit/  integration/  security/
docs/  research/  Dockerfile  docker-compose.yml  pyproject.toml  .github/workflows/ci.yml
```

### 4.3 Domain logic (the accuracy core)
- **Working days:** `count_working_days(start, end, start_half, end_half, holidays)` counts Monday to Friday excluding the holiday set, applies half-day adjustments, and returns the counted days plus the list of excluded dates with reasons.
- **Accrual:** `accrued_annual_leave(join_date, as_of)` implements monthly accrual and the 15th-of-month rule. `prorated_upfront(type, join_date, year)` implements CL and SL pro-rating with half-day rounding up.
- **Eligibility:** each rule R1 to R10 is a pure function returning `RuleResult(rule_id, passed, blocking, message, policy_ref)`. `check_eligibility` runs them all and aggregates.
- **Time:** all functions take `today` as a parameter, never reading the clock, so tests are deterministic.
- Money-like values are not used in this domain. Days are `Decimal` or integer half-days (stored as integer halves internally) to avoid float errors.

### 4.4 Tool layer
Tools are defined once with typed schemas, and exposed to both LangGraph and Deep Agents from the same registry. A `ToolContext` carries `employee_id`, `role`, `trace_id` and `today`. The model-visible schema excludes the context fields. Each call writes an `audit_log` row. Manager tools verify that the target employee reports to the caller, in the repository query itself (`WHERE manager_id = ?`), not only in Python after the fact.

### 4.5 Retrieval
- **Indexing:** parse front matter, split on `##`, store chunk text, metadata and embedding. FTS5 virtual table over text and title. `sqlite-vec` table over embeddings.
- **Search:** FTS5 top 20 and vector top 20, merged by reciprocal rank fusion, reranked, top 5 returned with scores.
- **Abstention:** a configured threshold on the rerank score or the fused score decides "no relevant policy". The threshold is tuned on the golden set, not guessed.
- **Citations:** each chunk is passed to the model as a labeled source with its section ID. The verifier checks that every cited ID was in the retrieved set. Where the provider's native citation feature is available and compatible, it is used. Otherwise the model is instructed to cite section IDs, and the verifier enforces it. **[PIN after checking the citations and search-result support in the API notes]**

### 4.6 Agent graph
State (`TypedDict`): `messages`, `employee` (id, role, name), `intent`, `needs_planning`, `retrieved`, `tool_results`, `draft`, `verified`, `attempts`, `workflow` (leave request draft), `trace_id`.

Nodes: `load_context`, `guardrail`, `route`, `policy_rag`, `tool_agent`, `calc`, `leave_workflow` (subgraph), `manager_actions`, `deep_path`, `sensitive`, `chitchat`, `decline`, `compose`, `verify`, `finalize`.

Edges:
- `route` selects one of the branches via conditional edges on `intent`.
- `policy_rag` and `tool_agent` can both run for `policy_and_data` (parallel fan-out, then merge).
- Every answer-producing branch flows to `compose`, then `verify`.
- `verify` returns to `compose` (max 2 attempts), escalates to `deep_path` once if the intent was not already a plan, or falls back to a deterministic template from tool output.
- `leave_workflow` uses `interrupt()` at the confirmation step and resumes with the user's decision. State is persisted by the SQLite checkpointer **[PIN]**.

`tool_agent` is a bounded ReAct-style loop, limited to 5 tool calls, over the read and calculate tools for the current role.

### 4.7 Deep Agents path
Built with `create_deep_agent` using the read-only tool set, a planner instruction, and three sub-agents: `policy_specialist` (search_policy), `leave_calculator` (balances, holidays, calculate, eligibility) and `drafter` (composes the final proposal). Runs inside a `deep_path` node with a recursion limit, a tool-call budget of 12 and a 30 second wall clock. Output is a structured proposal plus prose, passed through `verify`. Write tools are not registered on this path. **[PIN API shape and limits control]**

### 4.8 Prompts
Stored as versioned files in `agent/prompts/`: router, answer composer, tool agent, planner, sensitive handler, verifier rewrite. They contain: role and scope, the rule "use only provided sources and tool results", the citation format, the current date, and a refusal policy. The employee's data is delivered as tool results (data), never concatenated into system instructions. User text is wrapped and labeled as untrusted. Prompt versions are recorded in traces.

### 4.9 Verifier
Deterministic checks first (cheap): citations present and drawn from retrieved set, every number or date in the draft present in tool output or in the user's own message, no other employee names or IDs. Optionally a small-model groundedness check for policy claims when the golden-set evaluation shows it helps, since it adds latency. On failure the rewrite instruction lists exactly what failed.

### 4.10 API and streaming
`POST /chat` returns Server-Sent Events: `route`, `step` (tool calls), `token`, `citation`, `confirm_required`, `done`, `error`. Auth and rate limiting run as dependencies. Request-scoped `trace_id` is attached to logs and returned in error bodies.

## 5. Security Design
| Threat | Control | Test |
|---|---|---|
| Reading another employee's data | Identity from the token only. Repositories filter by `employee_id`. Manager access checked by `manager_id` in SQL. | Security tests with two employees and a manager outside the reporting line |
| Prompt injection (in user text or in a retrieved policy chunk) | Untrusted-content labeling, tool-level enforcement so injection cannot widen access, injection pattern flagging, policies come from a trusted ingestion path only | Red-team suite |
| Unauthorized writes | Write tools unavailable on Deep Agents path. Writes only after explicit confirmation and re-validation. | Workflow tests |
| SQL injection | Parameterized queries only, no string-built SQL | Static check and tests |
| Token theft or forgery | Short expiry, strong secret from environment, algorithm pinned | Token tests |
| Brute-force login | Lockout and rate limit | Tests |
| Secrets in code or logs | Environment variables, `.env` ignored by git, log redaction | Secret scan in CI |
| Sensitive content in logs | Audit stores tool inputs and outputs, not full chat text. Chat retention configurable. | Review |
| Dependency compromise | Pin and hash dependencies, `pip-audit` in CI | CI |

## 6. Performance Design
- Router uses the small model with a short prompt and structured output.
- Simple intents use a single tool call or a single retrieval, with streaming starting at the compose step.
- Hot data cached in-process per request: holidays, leave types.
- Embedding model loaded once at startup. Index loaded in memory.
- Prompt caching for the stable system prompt and tool definitions **[PIN]**.
- Parallel execution for independent retrieval and tool calls.
- Measured budgets and breakdown per node are reported by the evaluation run.

## 7. Reliability and Operations
- Retries with backoff for model calls, timeouts on every external call.
- Leave submission is a single database transaction with an idempotency key.
- SQLite in WAL mode with a busy timeout. Single writer is acceptable at this scale. Migration notes cover Postgres.
- `GET /health` checks database, index presence and model API reachability.
- Structured JSON logs with `trace_id`. Docker image runs as a non-root user.
- CI: lint, type check, unit and integration tests, secret scan, dependency audit, and the offline part of the evaluation.

## 8. Evaluation Design (details in the Test and Evaluation Plan)
Golden question set across categories (policy, data, calculation, workflow, sensitive, out-of-scope, injection, multi-turn, planning), scored for correctness, grounding, citation validity, refusal quality, latency and tool correctness. It acts as a release gate, with results saved as a report for the deck.

## 9. Key Risks and Open Technical Questions
| Item | Plan |
|---|---|
| Exact LangGraph and Deep Agents APIs may differ from my assumptions | Resolved by `research/stack-api-notes.md` before coding |
| Citation feature compatibility with structured output | Use verifier-enforced section IDs if needed |
| Local embeddings quality and Windows install | Fall back to FTS5-only retrieval if install fails, and document it |
| Reranker latency | Make it optional, decide from measurements |
| Deep Agents latency and cost | Strict budgets, only for planning intents |

## 10. Verified Pins and Corrections (resolves every **[PIN]** above)
**Runtime:** Python **3.12** via `py -3.12 -m venv .venv`. The default `python` on this machine is
3.9, which cannot run the stack (deepagents needs 3.11+, and pip silently resolves old versions).

| Package | Version |
|---|---|
| langgraph | 1.2.12 |
| langgraph-checkpoint-sqlite | 3.1.1 |
| langchain / langchain-core | 1.4.3 / 1.6.6 |
| langchain-anthropic / anthropic | 1.7.5 / 1.11.0 |
| deepagents | 0.7.21 |
| sqlite-vec | 0.1.9 |
| fastembed | 0.8.1 (onnxruntime, no torch) |

**Models:** answers and planning `claude-sonnet-5-5`. Routing `claude-haiku-4-5`
(snapshot `claude-haiku-4-5-20251001`). Haiku 4.5 retirement is announced for no sooner than
2026-10-15, so the router model is configurable with an automatic fallback to Sonnet.

**Citations:** use native `search_result` content blocks with `citations.enabled` (GA, no beta
header). The verifier still checks that cited sources were in the retrieved set. Native citations
cannot be combined with structured output in one request, so the router (structured) and the
answer step (cited) are separate calls.

**Embeddings:** `BAAI/bge-small-en-v1.5`, 384 dimensions, `cache_dir` set to a project folder
(about 130 MB first download). sqlite-vec table `vec0(embedding float[384] distance_metric=cosine)`.
Requires a Python build with `enable_load_extension` (true for the local `py` 3.12).

**LangGraph:** `StateGraph`, `add_conditional_edges`, `ToolNode`, `SqliteSaver` (connection with
`check_same_thread=False`), `interrupt()` and `Command(resume=...)`, `stream_mode=["updates","values"]`
(interrupts arrive as `__interrupt__` updates). `create_react_agent` and langchain 0.3 era tutorials
are outdated, so we do not use them.

**Deep Agents corrections to this design:**
1. `write_todos` is not a default tool, so add `middleware=[TodoListMiddleware()]`.
2. The default tool set includes `execute` (shell). It must be removed or disabled for this app, and
   a test asserts it is absent.
3. The built-in recursion limit is 9,999, so we cap per call with `{"recursion_limit": N}` and also
   enforce our own tool-call budget and wall clock.
4. Always pass the model explicitly (`"anthropic:claude-sonnet-5-5"`), since the default is
   deprecated.
5. The compiled agent works as a node in the parent graph, as designed in §4.7.

**Still unverified:** everything above was run against a fake chat model. Live-API behavior
(citations, tool-call formats, latency, prompt caching) is verified in step 6 of the build order and
reported in the evaluation.

## 11. Build Order (feeds the implementation plan)
1. Project skeleton, config, schema and seed data.
2. Domain logic with tests first (calendar, accrual, eligibility).
3. Repositories and tools, with access-control tests.
4. Auth and API skeleton.
5. Retrieval and indexing.
6. Agent graph: router, tool agent, compose, verify.
7. Leave workflow with interrupt and resume.
8. Deep Agents path.
9. UI, tracing, audit.
10. Evaluation suite and security tests, tuning.
11. Docker, CI, docs, demo deck.

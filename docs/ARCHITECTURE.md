# HR Chat Agent: Architecture (as built)

This is the authoritative description of the system **as implemented**. The PRD, FSD, Technical
Design and Test Plan in this folder are the design-time documents; where they differ from this file,
this file is correct (section 11 lists every difference and why). Evaluation numbers are in
`docs/EVALUATION.md`.

## 1. What it is

An authenticated HR assistant for employees, built on **LangGraph** with a **Deep Agents** planning
path and **Claude** (Sonnet 5.5 for answers, Haiku 4.5 for routing and planning sub-agents).
Employees ask in plain language. The agent answers policy questions from a policy library, reads
personal data (leave balance, requests, holidays) through tools, calculates leave, and can prepare a
leave request that only the employee can confirm.

The central design idea: **the model talks, but code decides facts and permissions.**

| Concern | Who is responsible |
|---|---|
| Which employee is asking | The signed JWT. Never the model. |
| Every number, date and eligibility result | Tested Python (`app/domain/`), reached through tools |
| Policy wording | Retrieved policy sections, cited by clause id |
| Whether an answer may be shown | A deterministic verifier (`app/agent/verifier.py`) |
| Whether a leave request is submitted | The employee, through an endpoint the model cannot call |

## 2. System overview

```
Browser (custom web app)  ──HTTPS──►  FastAPI  ──►  LangGraph agent  ──►  Claude (Anthropic API)
  login · chat · citation chips        auth, rate limit,      │  route → tool loop / planning path
  steps · confirm card · my leave      CSP, SSE stream        │  → verify → rewrite → fallback
                                              │               ▼
                                              │        Tools (10, identity injected by the server)
                                              │          │            │
                                              ▼          ▼            ▼
                                        SQLite file:  domain rules   policy search
                                        HR tables, drafts, audit,    (FTS5 + sqlite-vec,
                                        checkpoints, policy index    local bge-small embeddings)
```

Layers and dependency direction: `api → agent → tools → services/domain ← db`, with `rag` beside
`tools`. `app/domain/` is pure logic: no I/O and no clock reads.

## 3. Modules

| Path | Responsibility |
|---|---|
| `app/domain/` | `calendar.py` working days and breaks; `accrual.py` accrual, pro-rating, carry-forward caps; `eligibility.py` rules R1 to R10 |
| `app/db/` | `schema.sql`, connections (WAL, sqlite-vec loaded), `repositories.py` (parameterized SQL; manager scoping is in the query), `seed.py` demo company |
| `app/services/leave.py` | The leave workflow: prepare draft, confirm, cancel draft, cancel request |
| `app/tools/` | Tool registry (pydantic args, `extra="forbid"`), `ToolContext`, audit-on-every-call; leave, manager, policy and info tools |
| `app/rag/` | Chunker, embeddings (fastembed `bge-small-en-v1.5`), indexer, hybrid search |
| `app/agent/` | `graph.py` the LangGraph agent; `router.py`; `verifier.py`; `fallback.py`; `guardrail.py`; `prompts.py`; `deep_path.py` planning path; `factory.py` live wiring |
| `app/api/` | `main.py` routes, SSE, headers; `security.py` argon2 and JWT; `throttle.py` lockout and rate limit |
| `app/ui/static/` | The web app: `index.html`, `app.js`, `style.css` |
| `app/bootstrap.py`, `app/server.py` | First-start database setup; production entry point (`uvicorn app.server:app`) |
| `eval/` | Question sets, scorers, oracle, judge, runner, red-team set |

## 4. The agent graph

```
guardrail → route ─┬─ low confidence ───────────► clarify ─────────────────────┐
                   ├─ chitchat ─────────────────► respond ──► verify           │
                   ├─ out of scope ─────────────► decline ─────────────────────┤
                   ├─ sensitive ─► (search_policy + get_hr_contact, fixed) ─► verify
                   ├─ complex_plan / needs_planning ─► deep ─┬─► verify         │
                   │                                         └─ failed ─► agent │
                   └─ everything else ───────────► agent ⇄ tools (≤5 calls) ─► answer_now ─► verify
verify ─┬─ ok ─────────────────────────────────────────────────────────────────► finalize
        ├─ problems, < 2 rewrites ─► rewrite ─► verify
        └─ problems, 2 rewrites used ─► fallback (answer built from tool output) ─► finalize
```

Notes:
- **Router** (Haiku, JSON-schema output, falls back to Sonnet if Haiku is unavailable) returns an
  intent, a planning flag, a confidence and, for sensitive topics, a contact topic.
- **One tool loop** serves policy, data, calculation, leave and manager questions. The model chooses
  from the tools its **role** allows; the loop is capped at 5 calls, then `answer_now`.
- **State** is per turn (`work`, `calls`, `draft`, ...) except `history`: only the last 10 turns are
  sent to the model. Threads are namespaced `employee_id:thread_id`.

## 5. Safety design

1. **Identity.** `employee_id` and `role` come from the verified token and travel in
   `ToolContext`. Tool argument models forbid unknown fields, so `{"employee_id": 5}` is rejected
   (and audited). No tool schema exposes an identity parameter.
2. **Access control in the data layer.** Manager tools and repositories filter by `manager_id` in
   the SQL itself, so a bug in the agent cannot widen access.
3. **Verifier** (deterministic, after every draft). Every number and date must appear in this
   turn's tool output or the user's message (item counts of a returned list are allowed); every
   citation must have been retrieved; a policy answer using confident results must cite; no other
   employee's name may appear; sensitive replies are capped at 4 sentences. Failures trigger up to
   two rewrites that name the exact problems, then a **deterministic fallback** built only from tool
   output (which itself passes the verifier). Numbers written as words are not checked.
4. **Writes need the employee.** The model can call `prepare_leave_request`, which checks all rules
   and stores a **draft** (expires in 30 minutes) but submits nothing and never shows the model the
   draft id. Only `POST /leave/drafts/{id}/confirm` or a bare "yes" sent to `/chat` (handled without
   the model) creates a request. Confirmation re-checks eligibility, and is idempotent.
5. **Planning path is read-only.** `DeepPathGuard` allowlists tools and refuses others when they
   are *called*: no `prepare_leave_request`, and the library's file and shell tools are refused.
   Budgets are shared by the main agent and sub-agents: 12 tool calls, 3 sub-agent runs, 22 seconds
   (after which the model must answer with what it has), recursion limit 60. Database access is
   serialized because tools run in parallel threads.
6. **Web.** Strict Content-Security-Policy (no inline scripts or styles), `X-Frame-Options: DENY`,
   `nosniff`, no referrer. The UI builds all content with DOM text APIs, never `innerHTML`.
7. **Auth.** argon2 password hashes, HS256 JWT pinned (no `none`), 60-minute expiry, secret of at
   least 32 characters, lockout after 5 failures in 10 minutes (15-minute lock, also for unknown
   emails), a dummy hash check so response time does not reveal accounts, 30 chat requests per
   minute per employee.
8. **Audit.** Every tool call, including denied, invalid and unknown ones, writes an `audit_log`
   row (actor, tool, inputs, outputs, trace id). Leave submissions, cancellations and manager
   decisions are audited too.

## 6. Retrieval

- **Chunking:** one chunk per numbered `##` section of each policy file, with front matter (policy
  id, version, date). Each chunk records its clause ids (`POL-05 §3.1`) so citations are
  clause-level while chunks stay whole sections.
- **Index:** one SQLite file: FTS5 for keywords and a `vec0` table (384-dimension cosine) for
  meaning. Local embeddings, no second API key. Re-indexing is idempotent.
- **Search:** keyword (BM25, title weighted) and vector top 50 each, merged by reciprocal rank
  fusion, top 5 returned. There is **no reranker**: with 53 sections it was not needed.
- **Confidence tiers** on the best cosine similarity: at least **0.655** confident; **0.50 to
  0.655** a *weak match* (up to 3 sections returned, flagged, with an instruction to use them only if
  they directly answer); below 0.50 nothing is returned and the agent says it could not find it.
  The weak tier exists because evaluation showed the model's own rephrasings of a question score
  0.53 to 0.63 even when the policy answers it.
- **Citations** are plain `[POL-02 §5.4]` text written by the model and enforced by the verifier
  (Anthropic's native citation blocks were verified to work but not used).

## 7. Tools (10)

| Tool | Roles | Purpose |
|---|---|---|
| `get_leave_balance` | all | Accrued, carried forward, used, pending, available per leave type |
| `get_leave_history` | all | Own requests, with `can_cancel` |
| `calculate_leave_days` | all | Working days, excluded days, the working dates, and the whole break (`break_start`, `break_end`, `break_days`) |
| `check_leave_eligibility` | all | Days counted, balance after, loss-of-pay days, result of each rule R1 to R10 with its policy reference |
| `prepare_leave_request` | all (not on the planning path) | Check rules and store a draft for confirmation. Submits nothing. |
| `get_holidays` | all | Company holidays by year or month |
| `search_policy` | all | Policy sections with citations; confident or weak-match flag |
| `get_hr_contact` | all | Contact for a topic, with a general fallback |
| `list_pending_approvals` | manager | Direct reports' pending requests |
| `get_team_availability` | manager | Who in the team is on leave, by day |

## 8. HTTP API

| Endpoint | Purpose |
|---|---|
| `POST /auth/login`, `GET /me`, `GET /health` | Sign in, profile, database check |
| `POST /chat` | Server-sent events: `route`, `step`, `token`, `confirm_required`, `done`, `error` |
| `GET /leave/balance`, `GET /leave/requests?scope=own|team` | Balances and requests |
| `POST /leave/requests/{id}/decision` | Manager approves or rejects a direct report's request |
| `POST /leave/requests/{id}/cancel` | Cancel own pending or upcoming approved request |
| `POST /leave/drafts/{id}/confirm`, `.../cancel` | Confirm or discard a prepared request |
| `GET /policy/section?id=` | Text behind a citation chip |
| `GET /demo/accounts` | Demo login helper; only when `DEMO_DATA` is not `false` |

`/chat` streams **progress live** (route, each tool call, planning delegations) but sends the
**answer only after it passes verification**: raw model tokens are never streamed, because a draft
can still be rejected.

## 9. Data model

`employees`, `leave_types`, `leave_balances`, `leave_requests` (idempotency key), `leave_drafts`
(30-minute expiry), `holidays`, `floating_holiday_choices`, `audit_log`, `policy_chunks` (with
`clause_ids`), `policy_fts` (FTS5), `policy_vec` (vec0). LangGraph checkpoints hold conversation
history in the same file. SQLite in WAL mode; moving to Postgres is a documented migration.

## 10. Technology choices and why

| Choice | Why | Trade-off accepted |
|---|---|---|
| **LangGraph** | Explicit graph, conditional routing, checkpointed history, streaming, visible in traces | Some overhead over a plain loop |
| **Deep Agents** for planning only | Planning, delegation and context isolation suit multi-step requests | Slow (about 30 s); restricted heavily because its defaults include file and shell tools |
| **Claude Sonnet 5.5 / Haiku 4.5** | Strong tool use; a cheap fast router and sub-agents | Haiku 4.5 has an announced retirement date, so the router falls back to Sonnet |
| **SQLite + FTS5 + sqlite-vec** | Zero setup for reviewers; one file; hybrid search with no extra service | Single writer; in-memory lockout and rate limit are per process |
| **Local bge-small embeddings** | No second API key, works offline | Slightly lower quality than hosted models |
| **Custom web UI instead of Chainlit** | Chainlit adds about 100 packages including vendor telemetry; custom UI allows strict CSP and exact control of confirm and citation UX | More code to own |
| **Drafts in the database instead of LangGraph `interrupt()`** | The model has no path to submit; survives restarts; idempotent | Confirmation is outside the graph |

## 11. Differences from the design-time documents

| Design said | As built | Reason |
|---|---|---|
| Chainlit UI | Custom static web app | Dependency weight, telemetry, CSP control |
| Leave workflow subgraph with `interrupt()` | `prepare_leave_request` draft + confirm endpoint | Safety (model cannot submit), restart-proof, idempotent |
| Reranker | None | Not needed at this corpus size |
| Native `search_result` citations | Text citations enforced by the verifier | Works with any model; fully testable offline |
| 3 sub-agents incl. a drafter, 30 s | 2 sub-agents, 22 s soft limit, Haiku sub-agents | A drafter added a model call (about 5 s) for no accuracy gain |
| Separate nodes for policy, calc, manager actions; parallel fan-out; verify escalating to planning | One tool loop for those intents; no escalation to planning | Simpler; the model chooses tools. Planning failure falls back to the tool loop instead. |
| OpenTelemetry to Langfuse | Per-request trace id, `audit_log`, plain logs | Not built (see section 12) |
| Rolling summary and long-term memory | Last 10 turns only | Not built |
| `/chat/confirm`, `/threads` | Draft endpoints; no thread list | Superseded by the draft design |
| First-token under 2 s | First progress event about 1 to 2 s; answer after verification (4 to 7 s typical) | Verified answers over raw streaming |
| Hard 30 s planning limit | 22 s soft cutoff; planning measured at 31 to 39 s | See `EVALUATION.md` |

## 12. Known limitations (stated plainly)

- **Not built:** Docker packaging, CI, a README, pinned runtime dependencies (`pyproject.toml`
  lists none), tracing and metrics beyond the trace id, model-call retry with backoff (only the
  router falls back), prompt caching, a groundedness model check, load tests, cancel-through-chat.
- **In-memory state:** lockout and rate limits reset on restart and do not span processes.
- **Latency:** planning requests exceed the 30 s target.
- **Policies are illustrative.** Ideas2IT has not published its HR policies. Only items marked
  `[Public]` come from its website; everything else is sample content written for the demo.
- **Demo mode** exposes demo accounts and a shared password on the login page. It must be off in
  production (`DEMO_DATA=false`).
- **Numbers written as words** ("sixty days") are not checked by the verifier.
- **The architecture diagrams** in `docs/diagrams/architecture/` were regenerated from this document
  on 2026-10-04. Keep them in step with it when the design changes (see their README).

## 13. Testing

Unit, integration, retrieval-quality and real-browser (Playwright) tests cover the domain rules,
repositories, tools and access control, auth and lockout, the leave workflow, the API and SSE
stream, the agent graph (with a scripted model), the verifier and fallback, the planning guard, the
UI, and the evaluation harness itself. The live evaluation (120 development, 30 held-out and 30
red-team cases) is described in `docs/EVALUATION.md`.

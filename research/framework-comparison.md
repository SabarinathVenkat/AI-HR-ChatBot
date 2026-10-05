# HR Chat Agent: Framework and Stack Recommendation (as of 2026-10-02)

## 0. Honesty statement
100% accuracy cannot be guaranteed. LLMs can misread a policy, retrieve the wrong clause, or mis-handle an edge case. The goal is to make errors rare, detectable, and low-impact, using the design measures in section 5. Accuracy claims below should be measured on your own eval set, not taken from vendor or blog numbers.

Evidence caveats: several sources are third-party blogs (latency/benchmark figures especially) and are marked "secondary". LlamaIndex Workflows and Haystack were NOT researched this session; their scores come from general prior knowledge and should be treated as unverified. Claude model IDs and prices come from secondary sources; confirm on the official models page before pinning.

## 1. Top recommendation
**Thin, explicit orchestration: a plain Anthropic Messages-API tool-use loop (official `anthropic` SDK, or its Tool Runner) behind FastAPI, with deterministic Python tools and Claude's native search-result citations. Add LangGraph only if/when you need durable multi-step workflows with human approval (e.g. leave requests that write to the DB).** Runner-up if you want a typed framework: Pydantic AI.

Why: an HR Q&A agent is a single agent with ~5-10 tools, not a multi-agent system. Extra framework layers add latency, abstraction leaks around Claude-specific features (citations, prompt caching, extended thinking), and failure modes, without improving accuracy. Accuracy comes from retrieval quality, deterministic tools, and evals, not the framework.

## 2. Framework scorecard (1-5, 5 best; my judgement from the sources cited)

| Framework | Prod-ready | State/memory | Tool use | Observability | HITL | Latency overhead (5=lowest) | Community | Claude support | Testability | Total /45 |
|---|---|---|---|---|---|---|---|---|---|---|
| Anthropic SDK tool-use loop (+Tool Runner) | 5 | 3 (you own it) | 5 | 3 (OTel manual / Langfuse / LangSmith wrappers) | 3 (DIY) | 5 | 4 | 5 (native) | 5 | 38 |
| Claude Agent SDK | 3 | 4 (sessions) | 4 | 3 | 4 (permissions/hooks) | 2 (subprocess per session, cold start) | 3 | 5 | 3 | 31 |
| LangGraph (1.0, Oct 2025) | 5 | 5 (checkpointers, Postgres) | 4 | 5 (LangSmith native, OTel) | 5 (interrupts) | 4 | 5 | 4 (langchain-anthropic) | 4 | 39 |
| Pydantic AI (v1) | 4 | 3 (durable via Temporal/DBOS etc.) | 5 (typed) | 5 (OTel-native, Logfire) | 4 | 4 | 4 | 4 | 5 (TestModel, evals) | 38 |
| OpenAI Agents SDK | 4 | 3 | 4 | 4 (tracing built for OpenAI) | 4 | 4 | 4 | 2 (LiteLLM adapter is beta, Claude tool-call bug reports) | 3 | 32 |
| Microsoft Agent Framework (1.0, Apr 2026; AutoGen in maintenance) | 4 | 4 | 4 | 4 (OTel) | 4 | 3 | 3 | 3 | 3 | 32 |
| Google ADK | 4 | 4 | 4 | 4 | 3 | 3 | 3 | 3 (Claude wrapper / LiteLLM) | 3 | 31 |
| LlamaIndex Workflows (unverified) | 3 | 3 | 3 | 3 | 3 | 3 | 4 | 4 | 3 | 29 |
| Haystack (unverified) | 4 | 3 | 3 | 4 | 3 | 4 | 3 | 4 | 4 | 32 |
| CrewAI | 3 | 3 | 3 | 3 | 3 | 2 (LLM-driven delegation, token overhead) | 4 | 3 | 2 (non-deterministic) | 26 |
| AutoGen (legacy) | 2 (maintenance mode) | 3 | 3 | 3 | 3 | 2 | 3 | 3 | 2 | 24 |

Key evidence per framework:
- **LangGraph**: 1.0 released Oct 2025 with no breaking changes; per-step checkpointing (SQLite/Postgres), interrupt-based human-in-the-loop, resumes after restarts. Explicit state machine gives deterministic, auditable flow. Secondary benchmark claims ~120 ms overhead/node vs CrewAI ~450 ms/transition (treat as indicative only). Weakness: heavier abstraction, LangChain-ecosystem coupling.
  - https://docs.langchain.com/oss/python/langgraph/persistence
  - https://docs.langchain.com/oss/python/langchain/human-in-the-loop
  - https://medium.com/@romerorico.hugo/langgraph-1-0-released-no-breaking-changes-all-the-hard-won-lessons-8939d500ca7c
  - https://www.n-ix.com/langgraph-vs-crewai-vs-autogen/
- **Claude Agent SDK**: renamed from Claude Code SDK (Sep 2025); wraps the Claude Code harness. Custom tools via in-process MCP servers. Each session carries its own subprocess, memory and cold-start latency, which is a poor fit for a low-latency, many-concurrent-users chat endpoint. Designed for coding/file-system style agents. Also a reported issue: `search_result` content blocks dropped by the SDK's MCP tool-result handler (issue #574), which directly hurts native citations.
  - https://github.com/anthropics/claude-agent-sdk-python
  - https://github.com/anthropics/claude-agent-sdk-python/issues/574
  - https://www.reactify-solutions.com/articles/claude-agent-sdk-production-2026
- **Anthropic tool-use loop**: first-party, supports citations, search_result blocks, prompt caching, streaming with no abstraction between you and the API. Citations docs: https://platform.claude.com/docs/en/build-with-claude/citations and https://platform.claude.com/docs/en/build-with-claude/search-results (search_result blocks can be returned from custom tool calls, which is exactly the RAG-as-a-tool pattern). Limitation: citations cannot be combined with structured outputs (`output_config.format`) in the same request (API returns 400).
- **Pydantic AI**: v1 stable; OTel-native (Logfire or any OTLP backend); durable execution integrations (Temporal, DBOS, Prefect, etc.); typed tools and outputs; good test utilities. Strong runner-up.
  - https://pydantic.dev/articles/pydantic-ai-v1
  - https://ai.pydantic.dev/
  - https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal
- **OpenAI Agents SDK**: non-OpenAI models go through LiteLLM/any-llm adapters described as "best-effort, beta"; issues reported with Claude tool-call IDs and thinking models. Poor fit for a Claude-first build. (LiteLLM also had a supply-chain incident on PyPI, versions 1.82.7/1.82.8, March 2026; pin and audit if you use it.)
  - https://openai.github.io/openai-agents-python/models/
  - https://www.beri.net/article/openai-agents-sdk-alternatives-lock-in-runtime-migration
  - https://adk.dev/agents/models/litellm/ (security note)
- **Microsoft Agent Framework**: 1.0 GA April 3, 2026 (.NET and Python), merges AutoGen and Semantic Kernel; AutoGen entered maintenance mode Oct 2025, so do not start on AutoGen. Good choice only if you are a .NET/Azure shop.
  - https://visualstudiomagazine.com/articles/2026/04/06/microsoft-ships-production-ready-agent-framework-1-0-for-net-and-python.aspx
  - https://atlan.com/know/ai-agent/microsoft/agent-framework/
- **Google ADK**: documents a Claude wrapper class and LiteLLM route; Gemini/Vertex-first.
  - https://adk.dev/agents/models/anthropic/
- **CrewAI**: role-play multi-agent; secondary benchmarks report higher latency and token overhead and run-to-run divergence; not suited to a deterministic, auditable HR flow.
  - https://markaicode.com/vs/langgraph-vs-crewai-multi-agent-production/
  - https://theaiforest.com/crewai-vs-langgraph-2026/

Decision rule: single agent + tools + low latency = raw SDK loop (or Pydantic AI). Needs durable multi-step flows with approvals or branching = LangGraph. Multi-agent crews, Azure/.NET, or Gemini-first are not this project's constraints.

## 3. Component recommendations

| Layer | Pick | Justification |
|---|---|---|
| LLM | Claude Sonnet-tier for answering; Haiku-tier for routing/query rewriting and as cheap guard/judge. Escalate to Opus-tier only for hard cases. | Confirm current IDs/pricing on https://platform.claude.com/docs/en/about-claude/models/overview (secondary sources: https://devtk.ai/en/blog/claude-api-pricing-guide-2026/). Use prompt caching for the system prompt and policy preamble to cut latency/cost. Pin model versions in config. |
| Vector store | **pgvector in Postgres** (start); Qdrant if corpus/QPS grows or you want native hybrid | HR policy corpora are small (thousands to low hundreds of thousands of chunks). Postgres already holds leave data, so one DB, one backup, ACID, row-level security for per-employee/region/grade document filtering. pgvector lacks built-in fusion, so do FTS (tsvector) + vector with RRF in SQL/app. Qdrant has native sparse+dense hybrid and better tail latency in published tests but is another service. Chroma and FAISS: fine for prototypes; FAISS is a library without metadata filtering/persistence/auth; Chroma is weaker for production ops and access control. Sources: https://dev.to/gabrielanhaia/vector-db-choice-2026-pgvector-vs-qdrant-vs-pinecone-vs-weaviate-the-real-trade-matrix-166o , https://markaicode.com/benchmarks/qdrant-vs-pgvector-performance/ (secondary, vendor-adjacent; benchmark yourself) |
| Embeddings | **Voyage AI** (voyage-4 family: -lite for latency, voyage-4 balanced, -large for quality); fallback open model (e.g. BGE/E5) if data must stay in-house | Anthropic has no embedding model and points to Voyage. https://platform.claude.com/docs/en/build-with-claude/embeddings , https://docs.voyageai.com/docs/embeddings |
| Retrieval | **Hybrid (BM25/FTS + dense) fused with RRF, then rerank top ~30-50 to ~5-8** with Voyage rerank-2.5 (or a cross-encoder). Structure-aware chunking by policy section with heading path, effective date, policy ID, version and audience metadata; metadata filters by employee region/grade/employment type. Contextual retrieval (prepend short chunk context) is worth testing. | HR text has exact terms ("Section 4.2", "maternity", acronyms) where BM25 beats dense, and paraphrase queries where dense wins. https://docs.voyageai.com/docs/embeddings , https://www.anthropic.com/news/contextual-retrieval |
| API | **FastAPI** (async, SSE streaming), Pydantic models for tool I/O | Standard, testable, works with all options. |
| Auth | Company SSO via OIDC (Entra ID / Okta) with JWT validation in FastAPI (e.g. Authlib / fastapi-azure-auth). The employee ID comes only from the validated token, never from the model or request body. Tools take no employee_id parameter from the LLM; the server injects it. Per-employee row-level security in Postgres; audit log of every tool call. | Prevents prompt-injection-driven access to another employee's data. |
| UI | Start with Chainlit or Streamlit for internal MVP; for production, embed a React chat (assistant-ui or Vercel AI SDK UI) in the intranet/Teams. Render citations as clickable links to the policy doc/section; show "as of" dates. | Chainlit gives streaming, auth hooks, and step display fast. |
| Observability | OpenTelemetry GenAI spans to Langfuse (self-hostable, good for PII control) or LangSmith / Logfire. Log retrieval hits, tool args/results, citations, latency per stage. Redact PII. | Pydantic AI and LangGraph have this built-in; with the raw loop, instrument manually. |
| Evaluation | **DeepEval or pytest + RAGAS** for offline RAG metrics (faithfulness, context precision/recall, answer correctness) as a CI gate; **promptfoo** for prompt/model regression comparison and red-teaming (prompt injection, cross-employee data-leak attempts); Langfuse/LangSmith for online sampling and human review. Use a different/stronger model as LLM-judge and calibrate judge against human labels. | https://qaskills.sh/blog/promptfoo-vs-deepeval-vs-ragas-2026 , https://agentscamp.com/guides/evaluation/best-llm-eval-tools-2026 (secondary) |

## 4. Reference architecture
1. FastAPI endpoint validates OIDC token, loads employee profile, opens SSE stream.
2. Claude tool-use loop with tools: `search_policies(query, filters)` returning `search_result` blocks with citations enabled; `get_leave_balance()`, `check_leave_eligibility(type, dates)`, `calculate_leave_days(start, end)` (all deterministic, employee-scoped, returning structured JSON incl. "as of" timestamp); optional `escalate_to_hr()`.
3. Conversation history stored in Postgres (session table); summarise or window older turns; keep tool results out of long-term memory unless needed (stale balances).
4. Post-check: verify every number in the answer appears in a tool result or a cited chunk; verify each citation resolves; otherwise regenerate once or return a safe fallback / handoff.
5. Any write action (submit leave request) requires explicit user confirmation step (HITL); this is the point where LangGraph interrupts become worthwhile.

## 5. Accuracy-maximising design measures
- Deterministic tools for all numbers: balances, accruals, eligibility, date arithmetic, pro-rata. The LLM never computes; it only phrases tool outputs. Unit-test the tools exhaustively.
- Citation-required answers: enable Claude citations on search results; policy-style claims without a citation are rejected by a post-validator. Show source, section and effective date.
- "Answer only from retrieved context or tool results; otherwise say you do not know and offer HR contact" in the system prompt, plus a retrieval-confidence threshold (reranker score) that triggers abstention.
- Note the limitation: Claude citations cannot be combined with structured outputs, so validate with a separate pass or a second cheap call instead.
- Version and date every policy document; retrieve only the effective version for the employee's jurisdiction; re-index on change with an ingestion pipeline and diff review.
- Temperature low (0-0.2); prompt caching for stable system prompts.
- Guardrails: prompt-injection defences (treat retrieved text and user text as data), no tool parameters for identity, least-privilege DB role, PII redaction in logs.
- Eval suite before launch and in CI: 150-300 golden Q&A pairs from real HR tickets, including unanswerable questions, conflicting policy versions, multi-turn follow-ups, edge-case eligibility, numeric questions, and adversarial/injection cases. Track faithfulness, citation precision, numeric exactness (exact match against tool ground truth), abstention rate, retrieval recall@k, latency p50/p95. Release gates (e.g. zero numeric errors on the numeric set, faithfulness above an agreed threshold). Review production samples weekly; thumbs-down feedback feeds the golden set.
- Scope-limit: HR chat gives information, not legal/final determinations; show disclaimers and an easy human escalation. High-stakes topics (termination, disciplinary, medical) route to HR.
- Latency: stream tokens; run retrieval and profile fetch in parallel; Haiku-tier for rewriting/routing; prompt caching; cap retrieval/rerank sizes; limit tool-loop iterations (e.g. 4).

## 6. When to change the recommendation
- Need approvals/long-running workflows, branching, resumable state: add LangGraph (Postgres checkpointer, interrupts).
- Team prefers typed Python end-to-end and OTel by default: Pydantic AI instead of the raw loop.
- Microsoft/.NET shop: Microsoft Agent Framework.
- Corpus above ~several million chunks or heavy hybrid needs: Qdrant.

## 7. Source list
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langchain/human-in-the-loop
- https://platform.claude.com/docs/en/build-with-claude/citations
- https://platform.claude.com/docs/en/build-with-claude/search-results
- https://platform.claude.com/docs/en/build-with-claude/embeddings
- https://github.com/anthropics/claude-agent-sdk-python and issue #574
- https://pydantic.dev/articles/pydantic-ai-v1 , https://ai.pydantic.dev/
- https://openai.github.io/openai-agents-python/models/
- https://visualstudiomagazine.com/articles/2026/04/06/microsoft-ships-production-ready-agent-framework-1-0-for-net-and-python.aspx
- https://adk.dev/agents/models/anthropic/ , https://adk.dev/agents/models/litellm/
- https://www.n-ix.com/langgraph-vs-crewai-vs-autogen/ , https://markaicode.com/vs/langgraph-vs-crewai-multi-agent-production/
- https://docs.voyageai.com/docs/embeddings
- https://dev.to/gabrielanhaia/vector-db-choice-2026-pgvector-vs-qdrant-vs-pinecone-vs-weaviate-the-real-trade-matrix-166o
- https://qaskills.sh/blog/promptfoo-vs-deepeval-vs-ragas-2026
- https://devtk.ai/en/blog/claude-api-pricing-guide-2026/

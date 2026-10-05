# Product Requirements Document: HR Chat Agent

> **Status: design-time document.** The goals, scope and targets below are the original intent.
> What was actually built, where it differs and what is missing are in
> [`ARCHITECTURE.md`](ARCHITECTURE.md) (sections 11 and 12); measured results against these
> targets are in [`EVALUATION.md`](EVALUATION.md). Observability, Docker and CI were planned here
> and are not yet built.

| | |
|---|---|
| Version | 1.0 (draft for approval) |
| Date | 2026-10-02 |
| Source | `REQUIREMENTS.md` (assessment brief), `research/` |
| Status of policy content | Illustrative sample policies (see `data/policies/README.md`) |

## 1. Problem
Employees ask HR the same questions repeatedly: how much leave they have, whether they can take
a given period off, what the notice period is, how reimbursements work. Answers sit in policy
documents and in HR systems, so each answer needs a person to read both. This is slow for HR and
frustrating for employees.

## 2. Goal
An authenticated HR chat agent that answers employee questions **accurately, quickly and with
sources**, using policy documents for rules and a database for personal data, and that safely
handles simple actions such as applying for leave.

### Success metrics (targets, measured by the evaluation suite)
| Metric | Target |
|---|---|
| Numeric answers (balances, day counts) matching ground truth | 100% (computed by deterministic code, verified by tests) |
| Policy answers judged correct and grounded on the golden question set | 95% or higher |
| Policy answers carrying a valid citation | 100% |
| Unanswerable or out-of-scope questions correctly declined | 95% or higher |
| Cross-employee data leaks in security tests | 0 |
| Median response time, simple question (first token) | under 2 s |
| 95th percentile, simple question (complete answer) | under 6 s |
| Complex planning request (complete answer) | under 30 s |

These are targets to measure against, not guarantees. The documentation reports actual results.

## 3. Users and Roles
| Role | Needs |
|---|---|
| Employee | Own balances, policy answers, leave calculation, apply for leave, holidays |
| Manager | Everything an employee has, plus approve or reject team leave requests and see team availability |
| HR admin | Everything above for audit, plus view audit logs. Cannot edit policies through chat. |

## 4. Scope
### In scope
1. Login with email and password, JWT sessions, role-based access.
2. Policy Q&A grounded in the policy library with section citations.
3. Data questions: leave balance by type, eligibility, holiday list, own leave history, request status.
4. Leave calculation by policy rules: working days excluding weekends and holidays, half days, pro-rating, carry forward.
5. Leave request workflow with explicit employee confirmation before any write, and manager approval.
6. Multi-turn conversation memory within a session, and across sessions for the same employee.
7. Complex planning requests (for example annual leave planning) through the Deep Agents path.
8. Refusal, escalation to a human contact, and safe handling of out-of-scope, sensitive or abusive input.
9. Audit log of every tool call and every write.
10. Evaluation suite, tracing, Docker packaging, CI.
11. Documentation and demo deck.

### Out of scope (stated explicitly for the evaluation)
- Real SSO or integration with a real HRMS or payroll system. A mock database stands in.
- Payroll calculations and payslip generation.
- Editing policies through chat.
- Voice, mobile apps and multi-language support (English only).
- Legal advice. For legal or harassment matters the agent directs to a human contact.

## 5. Functional Requirements (summary; detailed in the FSD)
| ID | Requirement |
|---|---|
| FR-1 | The system shall authenticate users and reject unauthenticated chat requests. |
| FR-2 | The agent shall answer policy questions only from retrieved policy text and cite the policy ID and section. |
| FR-3 | When no relevant policy text is found, the agent shall say so and refer to HR rather than guess. |
| FR-4 | The agent shall obtain personal data only through tools scoped to the authenticated employee. |
| FR-5 | All numeric results shall come from deterministic tools, and the answer shall not contradict tool output. |
| FR-6 | Before submitting a leave request the agent shall show a summary (type, dates, days counted, balance after) and wait for explicit confirmation. |
| FR-7 | A leave request shall be rejected with an explanation when it breaks a policy rule (insufficient balance, notice, probation, maximum consecutive days). |
| FR-8 | Managers shall be able to approve or reject their direct reports' requests. |
| FR-9 | The agent shall keep conversation context so follow-ups like "and for next month?" resolve correctly. |
| FR-10 | Requests needing several dependent steps shall be routed to the planning path. |
| FR-11 | Sensitive topics (harassment, medical, legal, grievances) shall be answered with the policy summary and a human contact, never resolved by the agent. |
| FR-12 | Every tool call and write shall be logged with user, time, inputs and outputs. |
| FR-13 | The UI shall show citations and, on request, the steps the agent took. |

## 6. Non-Functional Requirements
- **Security:** user identity comes only from the verified token. No model-supplied identity. Protection against prompt injection and SQL injection. Passwords hashed. Secrets from environment variables only.
- **Privacy:** an employee can never read another employee's data, and a manager can read only direct reports' leave data.
- **Reliability:** graceful degradation if the model API fails (clear error, no partial writes). Idempotent leave submission.
- **Performance:** see targets in §2.
- **Observability:** traces for every request, structured logs, evaluation reports.
- **Maintainability:** modular layout, typed code, tests for all deterministic logic, policy files replaceable without code changes.
- **Portability:** runs locally with one command and in Docker. SQLite for the demo, with a documented path to Postgres.

## 7. Key Assumptions and Constraints
- Policies are illustrative samples. The system must work unchanged when real documents replace them.
- The model provider is Anthropic Claude. Model IDs will be verified against official documentation before pinning.
- Embeddings are generated locally unless a Voyage key is provided.
- The demo uses about 10 seeded employees across the three roles.

## 8. Risks
| Risk | Mitigation |
|---|---|
| Model gives a wrong number | Numbers only from tools, plus a verifier node and tests |
| Model invents a policy | Citation required, abstain on low retrieval confidence, evaluation set includes trick questions |
| Prompt injection exposes other employees' data | Identity injected server-side, scoped tools, security tests |
| Latency from multi-step graphs | Router with a fast path, caching, smaller model for routing, measured budgets |
| Framework API changes (LangGraph, Deep Agents) | Check official docs before coding, pin versions |
| Judges mistake sample policies for real ones | Labeling in files, UI banner and deck |

## 9. Milestones
1. Documents: PRD, FSD, Technical Design, Test and Evaluation Plan.
2. Foundations: database, seed data, auth, leave calculation tools (tests first).
3. Retrieval: policy indexing, hybrid search, citations.
4. Agent graph: router, tools, answer and verifier nodes.
5. Leave workflow with confirmation and manager approval.
6. Deep Agents planning path.
7. UI, tracing, evaluation suite, security tests.
8. Docker, CI, README, demo deck, final review.

## 10. Open Items
- Voyage key or local embeddings (default: local).
- Final holiday dates if the calendar is to be made official.

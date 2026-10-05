# HR Chat Agent

An authenticated HR assistant for employees. It answers policy questions with citations, reads
personal data (leave balance, requests, holidays) through tools, calculates leave under company
rules, and can prepare a leave request that **only the employee can confirm**. Built on
**LangGraph** with a **Deep Agents** planning path and **Claude**.

> **Sample data.** Ideas2IT has not published its HR policies. Everything in `data/policies/` that
> is not marked `[Public]` is an illustrative sample written for this demo, and all employees are
> fictional. Replace the policy files with real documents and re-index to use it for real.

## Why you can trust its answers

The model talks; code decides facts and permissions.

- **Identity comes from the signed token**, never from the model. A tool call carrying someone
  else's id is rejected.
- **Every number and date** in an answer must appear in that turn's tool output; every citation
  must have been retrieved. A deterministic verifier checks this, repairs failures, and falls back
  to a plain answer built straight from tool output.
- **Leave rules are tested Python** (`app/domain/`), not model arithmetic.
- **The model cannot submit leave.** It can only prepare a draft; confirming is a separate
  endpoint (or a bare "yes") that never involves the model.
- **The planning path is read-only**, with enforced tool allowlists and time and call budgets.

Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Measured results:
[`docs/EVALUATION.md`](docs/EVALUATION.md).

## Quick start

You need an Anthropic API key.

### With Docker

```bash
cp .env.example .env          # then set ANTHROPIC_API_KEY and JWT_SECRET
docker compose up --build
```

Open <http://localhost:8000>. If port 8000 is taken, set `HOST_PORT=8010` in `.env` first.

### Without Docker (Python 3.12)

```bash
python -m venv .venv
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                        # then set ANTHROPIC_API_KEY and JWT_SECRET
uvicorn app.server:app
```

The first start creates the database, loads the demo company and indexes the policies (the
embedding model, about 130 MB, downloads once).

### Try it

The login page lists the demo accounts (password for all: `Welcome@123`).

| Sign in as | Role | Good for |
|---|---|---|
| Ravi Kumar | Employee | Balance, policy questions, applying for leave |
| Divya Menon | Employee | A pending request you can cancel |
| Sanjay Patel | Employee on probation | Rules that block a request |
| Arjun Rao | Manager | Approving a team member's request |

Things to ask: *"How many annual leave days do I have left?"*, *"What is the notice period after
I resign?"*, *"Apply annual leave from 2 to 6 November"* (then press **Confirm**), *"How could I use
my leave to get the longest break in late December?"* (planning, about 30 seconds).

The demo data is dated around **2 October 2026**. `FIXED_DATE=2026-10-02` (set in `.env.example`'s
comments) pins "today" so it behaves the same on any day.

## Configuration

Set in `.env` (see [`.env.example`](.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | required | Your key |
| `JWT_SECRET` | required | Signs login tokens; at least 32 characters |
| `DB_PATH` | `hr_chat.db` | SQLite file (`/data/hr_chat.db` in Docker) |
| `ANSWER_MODEL` / `ROUTER_MODEL` | `claude-sonnet-5-5` / `claude-haiku-4-5` | Haiku 4.5 retires no sooner than 2026-10-15; switch `ROUTER_MODEL` to Sonnet then. This one setting also picks the model for the planning sub-agents, so they move to Sonnet too (slower; not yet measured) |
| `DEMO_DATA` | `true` | Seeds the fictional company and shows demo accounts. **Set `false` for anything real.** |
| `FIXED_DATE` | unset | Pins "today" for demos |

## Tests and evaluation

```bash
pip install -r requirements-dev.txt
playwright install chromium        # once, for the browser tests
pytest                             # 446 tests, no API calls
ruff check .                       # lint
pip-audit -r requirements.txt      # known-vulnerability check
```

The live evaluation calls the model and costs a few dollars:

```bash
python -m eval.run_eval --set dev         # 120 development questions
python -m eval.run_eval --set redteam     # 30 attacks; all must fail
python -m eval.run_eval --latency         # serial latency probe
python -m eval.run_eval --set heldout     # 30 held-out questions: run once, at the end
```

Reports are written to `eval/reports/`.

## Project layout

```
app/domain/      leave rules: calendar, accrual, eligibility (pure, no I/O)
app/db/          schema, repositories, demo data
app/services/    leave workflow: prepare, confirm, cancel
app/tools/       the 10 tools the agent can call
app/rag/         policy chunking, embeddings, hybrid search
app/agent/       LangGraph agent, router, verifier, planning path
app/api/         FastAPI routes, auth, rate limits
app/ui/static/   the web app
data/policies/   sample policy library
eval/            question sets, scorers, runner
tests/           unit, integration, retrieval, browser
docs/            requirements, design, architecture, evaluation, diagrams
```

## Known limitations

Stated plainly; the full list is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#12-known-limitations-stated-plainly).

- Planning requests take about 30 to 35 seconds; ordinary questions 4 to 7 seconds.
- Login lockout and rate limits are in memory, per process.
- No tracing or metrics beyond a per-request trace id and an audit table.
- The CI workflow is validated for syntax but has not run on GitHub.
- Numbers written as words ("sixty days") are not checked by the verifier.

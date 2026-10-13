# Pending items

Work that is known, deliberately not done yet, and where it stands. Newest decisions at the top of
each group. Tick items off here as they are finished.

## Planned next (agreed)

| # | Item | Why it matters | Notes |
|---|---|---|---|
| 1 | ~~**Regenerate the architecture diagrams**~~ **Done 2026-10-04** | All six diagrams now match `docs/ARCHITECTURE.md` (no Chainlit, reranker or `interrupt()`; 10 tools; 2 sub-agents; 22 s; confirm endpoint outside the graph). | Generator is `docs/diagrams/architecture/src/` (edit the `d0N_*.py` files, run `build.py`, then `render.py`). Keep in step with `docs/ARCHITECTURE.md`. |
| 2 | ~~**Build the demo deck**~~ **Built 2026-10-04** | `docs/deck/HR_Chat_Agent_Demo_Deck.pptx`: 16 slides plus 2 appendix slides, with speaker notes on every slide, native editable diagrams and the new-UI screenshots (re-captured today). | Rebuild with `python scripts/build_deck.py` (needs `pip install python-pptx`); slide text lives in that script. Still to do by the presenter: rehearse the live demo, check the presenter name on slide 1, and re-run `scripts/ui_screenshots.py` then rebuild if the UI changes. |

## Housekeeping

| # | Item | Notes |
|---|---|---|
| 3 | ~~**Put the project under git**~~ **Done 2026-10-04** | Repository on branch `main`, pushed on 2026-10-04 to the private GitHub repository `SabarinathVenkat/AI-HR-ChatBot`. `.gitignore` excludes `.env`, `.venv`, databases (including `-wal` and `-shm`), caches, model cache and eval reports. The learning `JWT_SECRET` now lives in the ignored `.env`, not in `.vscode/launch.json`. |
| 4 | ~~**Run the CI workflow on GitHub once**~~ **Done 2026-10-04** | The first run on GitHub passed (reported by the repository owner from the Actions tab). |
| 5 | **Compact Docker's disk** | Pruning freed 29 GB inside Docker, but Windows still sees the old file size. Needs an admin PowerShell (`wsl --shutdown`, then compact the `docker_data.vhdx`). |
| 6 | **Disk space is low** (about 1.4 GB free on C:) | Mostly not this project (pip cache 7 GB, Hugging Face cache 7 GB, Docker). Keep an eye on it. |

## Known gaps in the product

| # | Item | Notes |
|---|---|---|
| 7 | **Planning latency misses its target** | Median 32 s, p95 51 s, against under 30 s. Ideas: fewer model round trips, parallel sub-agents, a hard time stop, smaller answers. |
| 8 | **Observability** | Only a per-request trace id and an `audit_log` table exist. No tracing, metrics or JSON logs (OpenTelemetry to Langfuse was designed, not built). |
| 9 | **Retry with backoff on model calls** (partly done 2026-10-13) | The Anthropic client already retried twice with backoff by default. Added explicit timeouts (answer 60 s, router 15 s, sub-agents 30 s) and an explicit retry count in `app/agent/factory.py` (`build_models`), with tests. Still open: only the router falls back to another model; the answer model and sub-agents have none, so a long provider outage still ends in an error message. |
| 10 | **Prompt caching** | Active only on the Deep Agents planning path (the library adds Anthropic caching middleware). The plain agent loop and the router send no cache markers, so the stable system prompt and tool list are re-billed on every call there. |
| 11 | **Cancel a leave request through chat** | Cancelling works through the UI and API only. |
| 12 | **Conversation summary and long-term memory** | Only the last 10 turns are remembered. |
| 13 | **Load test** | Latency was measured one request at a time. Lockout and rate limits are in memory, per process. |
| 14 | **Verifier does not check numbers written as words** ("sixty days") | Documented limitation. |

## Date-driven

| # | Item | When |
|---|---|---|
| 15 | ~~**Haiku 4.5 retirement**~~ **Done 2026-10-13: moved to Haiku 5.5** | Default `ROUTER_MODEL` and the local `.env` are now `claude-haiku-5-5` (released 2026-10-07, retirement not sooner than 2027-10-07). A live probe classified four test questions correctly within the 300-token router cap. The same setting drives the planning sub-agents. Evaluation reports from 2026-10-13 describe this configuration; `docs/EVALUATION.md` still describes the earlier Haiku 4.5 run. |

## Before any real use

| # | Item |
|---|---|
| 16 | Replace `data/policies/` with the company's real policies and re-index (`REINDEX=true`). |
| 17 | Set `DEMO_DATA=false` (removes demo accounts, the shared password and the seeded company). |
| 18 | Put the app behind HTTPS and real single sign-on; the demo login is not production authentication. |
| 19 | Independent review of the evaluation: the questions, attacks and rubrics were written by the same person who built the system. |

## Documents that are only partly updated

`docs/PRD.md`, `FSD.md`, `TECHNICAL_DESIGN.md` and `TEST_AND_EVALUATION_PLAN.md` carry a status banner
and are correct as design-time records; `docs/ARCHITECTURE.md` is the as-built description. Fully
rewriting the older four is optional.

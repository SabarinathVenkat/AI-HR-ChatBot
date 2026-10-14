# Evaluation

How the HR Chat Agent was tested, what the numbers are, where it falls short, and how much weight
the numbers can bear. Raw reports are in [`evaluation/`](evaluation/). Everything here can be
reproduced with `python -m eval.run_eval` (see the README).

## 1. Summary

| Set | Cases | Passed | 95% interval | Notes |
|---|---|---|---|---|
| **Held-out** (written before any results; run once, last) | 30 | **29 (96.7%)** | 83% to 99% | The headline. Not tuned against. |
| Development (used while building and tuning) | 120 | 119 (99.2%) | 95% to 100% | Optimistic: it is the set I tuned against. |
| Red-team attacks | 30 | 30 (100%) | 89% to 100% | Passed on both runs (before and after the fixes). |
| Sensitive-topic cases, repeated after a late fix | 24 | 22 (91.7%) | 74% to 98% | Shows judge-driven run-to-run variation. |

Latency (serial run, seconds per complete answer): ordinary questions **median 1 to 6 s**; planning
requests **median 32 s, p95 51 s**, which **misses the 30-second target** (section 5).

**How to read these.** A case passes only if every hard check passes. The intervals are 95% Wilson
intervals: on 30 cases, "29 of 30" is consistent with a true rate anywhere from 83% to 99%. The
numbers are good evidence, not proof, and sections 6 and 7 say why they should be trusted less than
they look.

## 2. What was measured

| Set | Size | Purpose |
|---|---|---|
| Development | 120 | 30 policy, 15 personal data, 15 calculation, 10 policy-and-data, 10 leave workflow, 10 multi-turn, 8 planning, 6 sensitive, 10 out-of-scope, 6 manager |
| Held-out | 30 | The same categories, different questions and facts. Written before any evaluation ran, never tuned against, run once. A test checks that none repeats a development question. |
| Red-team | 30 | Attacks (section 4) |

Each case runs against the live system (Claude Sonnet 5.5 answering, Haiku 4.5 routing) on its own
private copy of a seeded database, as a named employee. Conversations may have several turns.

**How cases are scored.** Almost everything is checked deterministically:

- **Numbers:** expected values are computed from the database and the leave-rule code (`eval/oracle.py`),
  not typed by hand, and the oracle itself is tested against values worked out by hand.
- **Citations:** both that the right policy section is cited and that every cited section was actually
  retrieved.
- **Tools and state:** which tools were called; that nothing was written to the database; that a draft is
  waiting but unsubmitted; that no other employee's name or data appears.
- **A model judge** (Sonnet) grades only where wording matters: the tone of a refusal, the quality of a
  plan, the empathy of a sensitive reply. These are the least reliable checks.

The scorers, oracle, question-set integrity, runner and judge are themselves tested (59 tests), because a
wrong scorer would make every number meaningless.

## 3. Results by category and metric

Final development run (119 of 120) and the single held-out run (29 of 30):

| Category | Development | Held-out |
|---|---|---|
| Policy lookup | 30/30 | 8/8 |
| Personal data | 15/15 | 4/4 |
| Calculation | 15/15 | 4/4 |
| Policy and data | 10/10 | 2/2 |
| Leave workflow | 10/10 | 3/3 |
| Multi-turn | 10/10 | 2/2 |
| Planning | 8/8 | 2/2 |
| Sensitive topics | 5/6 | 0/1 |
| Out of scope | 10/10 | 2/2 |
| Manager | 6/6 | 2/2 |

| Metric (over individual checks) | Development | Held-out | Red-team |
|---|---|---|---|
| Numeric exactness | 58/58 | 12/12 | 4/4 |
| Citation present (policy answers) | 44/44 | 10/10 | n/a |
| Citation valid (cited section was retrieved) | 58/58 | 14/14 | n/a |
| No other person's data in the answer | 26/26 | 7/7 | 19/19 |
| Tool use correct | 89/89 | 24/24 | 1/1 |
| Leave-workflow safety (no unconfirmed write) | 59/59 | 13/13 | 18/18 |
| Answers that fell back to the plain template | 0/120 | 0/30 | 0/30 |
| Answers that needed a verifier rewrite | 9/120 (7.5%) | 0/30 | 0/30 |
| Model-judged answers | 21/22 | 4/5 | 3/3 |

Crashed cases: none in any run.

### The two failures in the final runs

Both are the same defect, found by this evaluation.

- **Development S02** and **held-out HS1**: a sensitive-topic reply ran to five sentences against a
  four-sentence limit. The verifier is meant to enforce that limit in code but did not.
- **Cause:** the sentence counter removed email addresses with the pattern `\S+@\S+`, which also removed
  the full stop after the address and merged two sentences into one.
- **Fix:** a stricter email pattern, with a regression test built from the two real failing answers.
  The test failed before the fix and passes after.
- **How this is reported:** the table above shows the results *as run, before the fix*. After the fix the
  development sensitive cases were re-run (22 of 24 over four repeats). The held-out set was **not**
  re-run, so its 29 of 30 stays a clean, untuned number.

## 4. Red-team

30 attacks, each against a named employee; any single failure blocks release. The checks are about
harm (what leaked, what was written), not about the wording of the refusal.

| Attack family | Cases |
|---|---|
| Ask for another employee's data directly, by claiming to be HR, or by claiming an employee id | R01 to R03 |
| Extract the system prompt (direct, "repeat everything above") | R04, R05 |
| Jailbreak personas, "school project" framing, fake `[SYSTEM]` blocks, base64-encoded instructions | R06, R17, R21, R25 |
| Bulk exfiltration ("put everyone in a table", everyone's emails) | R07, R27 |
| SQL injection and script payloads in the question | R08, R23 |
| Unconfirmed writes ("submit it, don't ask me") and planning-path writes | R09, R28, R30 |
| Approve, cancel or delete someone else's request; role escalation | R10 to R13, R26 |
| Oversized input | R14, R15 |
| **Indirect injection:** a policy section was altered to instruct the model to dump everyone's balances | R16 |
| Credential and hash requests | R18, R19 |
| Multi-turn "authorization" and social engineering | R20, R22, R29 |

Result: **30 of 30 on both runs** (one before the late fixes, one after). Nothing leaked, nothing was written, the database stayed
intact. The deterministic safeguards (identity injected by the server, access scoped in the database
query, the model unable to submit leave) are also covered by unit and integration tests that do not
depend on the model at all.

## 5. Latency

Serial run (one request at a time, so there is no contention), 32 probe questions, seconds from
sending a question to the complete verified answer:

| Category | n | Median | p95 | Max |
|---|---|---|---|---|
| Sensitive | 3 | 2.8 | 2.9 | 2.9 |
| Out of scope | 3 | 1.0 | 6.2 | 6.8 |
| Personal data | 3 | 4.1 | 4.7 | 4.8 |
| Manager | 3 | 4.7 | 5.2 | 5.3 |
| Calculation | 3 | 5.5 | 7.7 | 8.0 |
| Policy | 3 | 5.7 | 5.9 | 6.0 |
| Policy and data | 3 | 5.8 | 6.9 | 7.1 |
| Leave workflow | 3 | 6.4 | 10.2 | 10.6 |
| **Planning (Deep Agents)** | 8 | **32.2** | **51.3** | **58.6** |

Against the targets in the PRD:

| Target | Result |
|---|---|
| Ordinary question, complete answer, p95 under 6 s | **Met** for personal data, manager, policy and sensitive. **Missed** for calculation (7.7), policy-and-data (6.9) and leave workflow (10.2). |
| Complex planning request, complete answer, under 30 s | **Missed**: median 32 s, p95 51 s, max 59 s. |
| Median first token under 2 s | **Not applicable as written.** The first *progress* event arrives in about 1 to 2 s, but answer text is sent only after verification, by design. |

**Caveats.** Three questions per category make the percentiles crude; treat them as indicative. The
planning path has a 22-second soft time limit, but it is applied between model calls, so a verifier
rewrite on top can push a request past 50 seconds. Streaming progress live (tool calls and delegations)
keeps the wait visible, but it does not shorten it.

## 6. How the numbers changed, including my mistakes

| Step | Development | What changed |
|---|---|---|
| First complete run | 106/120 (88.3%) | Baseline. 14 failures. |
| After fixes | 118/120 (98.3%) | See below. |
| Final run | 119/120 (99.2%) | Judge repaired (two cases had been judge crashes, not wrong answers). |

The 14 first-run failures split into two kinds, and keeping them apart matters.

**Real defects in the product, fixed:**
- Policy search wrongly declined a question it could answer (a score of 0.658 against a 0.655 gate, and the
  model's own rephrasings scored lower). Fixed with a two-tier search: confident matches, and a flagged
  "weak match" band the model must use only if it directly answers.
- A sensitive reply exceeded its sentence limit; the limit is now enforced in code.
- Three prompt gaps: assume annual leave when no type is given; team information is manager-only; do not
  invent confidentiality rules.

**Mistakes in how I wrote the tests, corrected and disclosed:**
- One rubric required out-of-scope replies to "offer HR as the place to ask", which is nonsensical for a
  poem or the weather. I split it into three rubrics by kind of question. No question text changed, and
  the same rubrics apply to the held-out set, which had not been run.
- One manager rubric demanded an explanation the assistant has no way to verify.

**Two harness bugs found along the way:** the judge crashed on long answers because the model's hidden
reasoning used up its small output budget (raised; the product's own answer budget was raised too, to
close the same latent risk); and two scorers had flaws that the harness's own tests caught before any
number was reported (a held-out question identical to a development question, and a figure that was
also the user's own legitimate data).

**An earlier, separate check on the policy search itself** (20 development and 10 unanswerable
questions, then a held-out 10 and 6): the right section was in the top three for every answerable
question, and every unanswerable one was declined. The confident threshold of 0.655 was chosen on the
development questions; on the held-out questions it wrongly declined 1 of 10, which led to the two-tier
design above.

## 7. Limits of this evaluation

Please weigh the numbers accordingly.

1. **I wrote the questions, the attacks and the rubrics.** They reflect what I thought of, and the first
   run showed I mis-specified rubrics. An independent author would find things I did not.
2. **The judge is the same model family as the answerer** (Sonnet grading Sonnet), which can favour its own
   style. Judged checks are a small share (22 of the development checks, 5 of the held-out checks) and
   are the least stable: the sensitive category scored 5/6, 6/6, 5/6, 4/6, then 18/18 across runs on
   essentially the same code. Deterministic checks (numbers, citations, tools, writes, leaks) do not have this
   problem.
3. **Small samples.** Several categories have 1 to 8 cases. A category at "2 of 2" says very little.
4. **One run per set.** The system and the judge are non-deterministic. Planning cases in particular flip
   between runs.
5. **Tiny, synthetic world.** Ten fictional employees and sample policies written by me (about 50 sections).
   Retrieval quality on a real, long, messy policy library is unmeasured.
6. **Accuracy is measured, not guaranteed.** Numbers in answers come from tested code and are verified, but
   the system can still decline a question it could answer, misroute, or phrase something poorly. The
   verifier checked digits only. Since 2026-10-14 it also checks number words followed by a unit of time ("sixty days"); the 2026-10-14 dev run scored 120/120, but the other results in this document predate that change.
7. **Token counts are approximate**; calls made inside planning sub-agents may not be counted. No cost
   figures are given because I did not verify current prices.
8. **No load test.** Concurrency was only used to run evaluations faster (4 workers); latency was
   measured one request at a time. Lockout and rate limiting are in memory and per process.

## 8. Reproduce

```bash
python -m eval.run_eval --set dev --workers 4     # 120 development questions
python -m eval.run_eval --set redteam             # 30 attacks
python -m eval.run_eval --latency                 # serial latency probe
python -m eval.run_eval --set heldout             # 30 held-out questions: once, at the end
```

Needs `ANTHROPIC_API_KEY`. A full run costs a few dollars of API usage. Each report records the models,
prompt version and a hash of the policy corpus it was produced with.

## 9. Found after the evaluation

**2026-10-04, while recording the demo video:** one calculation question ended with the message "I did not
get an answer". The cause was a defect in the verifier. A draft with no text has no numbers, dates or
citations to fail on, so a rewrite that returned nothing passed as "verified" and the employee saw a blank
answer. None of the evaluated cases hit it (0 of 180 used the fallback, and no case ended without an answer),
but the evaluation could not have caught a rare failure of this kind.

- **Fix:** the verifier now rejects an empty draft (`empty_answer`), which sends it to a rewrite and, after two
  failed rewrites, to the deterministic fallback. Three regression tests were written first and failed before
  the fix: one on the verifier and two through the whole graph.
- **Not re-run:** the evaluation numbers in this document predate the fix and were not regenerated. The change
  only affects drafts that were previously blank.
- **Lesson:** a watched end-to-end run found something that 180 scored cases did not. Rare failures need more
  runs, or a check for "the user received a non-empty answer" in every scored case.

## 10. Router moved to Haiku 5.5 (2026-10-13)

Haiku 5.5 (`claude-haiku-5-5`, released 2026-10-07) replaced Haiku 4.5 as the router and planning sub-agent
model. Sonnet 5.5 still answers. Sections 1 to 8 describe the earlier Haiku 4.5 run; this section records the
re-run after the change.

| Set | Result | Notes |
|---|---|---|
| Development (120) | 119/120 | The one failure was planning case L04 ("find me a long weekend in October or November"). It took 32.5 s and the answer said the holiday and day-count lookups came back empty. Cause not investigated. |
| Red-team (30) | 30/30 | |

- **Not re-run:** the held-out set (it is meant to be run once) and the latency probes. The medians in section 5 are
  for Haiku 4.5.
- **Also not re-measured:** the empty-draft fix from section 9 was already in place for this run.
- **Before the switch:** the real router class classified four test questions correctly on Haiku 5.5 within its
  300-token cap, so adaptive thinking did not truncate the structured output.

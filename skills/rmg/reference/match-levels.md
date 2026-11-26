# Match levels: Mirror, Bridge and Summit

Read this when RMG picks a level, or asks for a higher match. The level is the **goal** for how many of the JD's must-have skills the
resume shows. It never lets you claim a skill the resume does not show: the candidate is asked about every line, and the file goes
to a client.

## The three levels

- **Mirror**: as is. Fix wording, put the JD's skills first, trim the least relevant. No attempt to raise the match.
- **Bridge**: aim for at least 50 percent of the must-have skills shown.
- **Summit**: aim for at least 80 percent of the must-have skills shown.

Bridge and Summit are tailored the Deep match way (see the playbook). If RMG gives no level, use Mirror and say that Bridge and
Summit exist.

## Reaching a level, in this order

1. **Measure.** `python scripts/match_level.py --resume <file> --required "..." --nice "..." --level bridge` (or summit). It prints
   the percentage now, how many more must-haves are needed, and for each gap either `EVIDENCE` or `ASK`.
2. **Evidence pass (you may do this alone).** For each `EVIDENCE` skill, write it into the project where the evidence is, by
   rewording the line that shows it ("Built REST endpoints with ASP.NET Web API" may name "REST APIs"). Put it in the note under
   **Inferred skills** with the line that shows it. Run the checker with `--inferred "A, B"`: it refuses an inference with no
   evidence in the resume.
3. **Ask.** After the first build, show RMG the match, then ask once: "Is there anything on the list you have really worked with,
   must-have or nice-to-have? Tell me which project." Show every remaining gap as a yes/no question. An answer of yes with the
   project names is **confirmed by the candidate**: write it in those projects only, as their own statement (`--confirmed`).
4. **No answer.** Do not wait. Deliver what steps 1 and 2 reached and say so in the note.
5. **"I do not know" or "just match the JD".** Do steps 1 and 2 as far as they go, and no further. Say plainly what level was
   reached. If it is below the target, say so ("Summit not reached: 62 percent. The resume does not show Kafka, Terraform and
   FHIR.") and give the list of questions for the candidate. Do not add the skills, and do not describe them as "familiar with",
   "exposure to" or "working knowledge": those are claims too.

## What counts as evidence

Only a true implication, from `scripts/related.py`: Spring Boot shows Spring; JUnit shows unit testing; Jenkins shows CI/CD;
PostgreSQL shows SQL and RDBMS; Web API shows REST. "Knows AWS" does not show Kubernetes. Being in the same field is not evidence.
If you think of a new pair, add it to `related.py` only when everyone who has done the first has necessarily done the second.

## What to hand over after a level

The note (see output-format.md) has the level asked, the level reached, the inferred skills with their evidence, what changed in
each project (a short list: "Payments: added REST APIs to the Order API bullet"), and the questions still open. If the level was
not reached, the first line says so.

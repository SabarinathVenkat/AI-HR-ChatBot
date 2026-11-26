# Match levels: Mirror, Bridge and Summit

Read this when RMG or the candidate picks a level, or asks for a higher match. The level is the **goal** for how many of the JD's
must-have skills the resume shows.

## The three levels

- **Mirror**: as is. Fix wording, put the JD's skills first, trim the least relevant. No skill is added that the resume does not
  show. It is the way back: if a Bridge or Summit result is not what the person wants, rebuild in Mirror.
- **Bridge**: aim for at least 50 percent of the must-have skills shown.
- **Summit**: aim for at least 80 percent of the must-have skills shown.

Bridge and Summit are tailored the Deep match way (see the playbook). If no level was given, use Mirror and say that Bridge and
Summit exist. The skill is used by RMG or by the candidate; when RMG builds the resume, it goes to the client only after the
candidate approves it, so the note below is written for the candidate to read.

## Reaching a level, in this order

1. **Measure.** `python scripts/match_level.py --resume <file> --required "..." --nice "..." --level bridge` (or summit). It prints
   the percentage now, how many more must-haves are needed, and for each gap either `EVIDENCE` or `NO EVIDENCE`.
2. **Evidence first.** For each `EVIDENCE` skill, write it into the project where the evidence is, by rewording the line that
   shows it ("Built REST endpoints with ASP.NET Web API" may name "REST APIs"). These need no warning. List them in the note under
   **Inferred skills** with the evidence.
3. **Ask once.** After the first build, ask: "Is there anything on the list you have really worked with, must-have or nice-to-have?
   Tell me which project." A yes with project names is **confirmed by the candidate**: write it in those projects (`--confirmed`).
4. **Then add what is still needed (Bridge and Summit only).** If the target is still not reached, because there was no answer, or
   the person said "I do not know" or "just match the JD", add the remaining must-have skills, then nice-to-have ones if more are
   wanted, until the target is reached. Do it like this:
   - **Warn first**, in the same message as the result, in these words: "To reach <level> I added <N> skill(s) your resume does not
     show: <list>. They are marked in the notes below. Only keep a skill you can speak to in an interview. Rebuild in Mirror to undo."
   - Put each skill in the project where it fits best (same kind of work or stack), as a short phrase inside an existing bullet or
     as one new bullet written in that project's own words. Do not add numbers, results, dates, employers or certifications.
   - Do not describe it as less than it is ("exposure to", "familiar with") and do not describe it as more ("expert in"): write it
     the way the resume writes its other tools.
   - Run the checker with `--added "P, Q"`. It accepts them and prints a warning line for each, to paste into the note.
5. **Do not stop at the target by accident.** Add only what is needed to reach the level, not every gap.

## What counts as evidence

A true implication, from `scripts/related.py`: Spring Boot shows Spring; JUnit shows unit testing; Jenkins shows CI/CD;
PostgreSQL shows SQL and RDBMS; Web API shows REST. Being in the same field is not evidence ("knows AWS" does not show Kubernetes):
such a skill goes through step 4.

## The summary note for every change

The note (see output-format.md) lists every change, grouped, so the person can reverse any of them:

- **Reworded**: lines made clearer or reordered, per project.
- **Inferred skills**: written in because the resume shows something that implies them, with the evidence.
- **Confirmed by the candidate**: skill and the projects.
- **Added for the match, not in the original resume**: skill, the project, and the exact line it went into. Put this first in the
  note. Say that the candidate must approve these before the resume goes to a client, and that striking one out is fine.
- **Match**: the level asked and the level reached (for example "Summit: 85 percent, from 31 percent").

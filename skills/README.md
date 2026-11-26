# Skills: a beginner's guide, using the RMG skill

This folder holds **Claude Skills** for the Ideas2IT project. Today there is one: `rmg/`, which tailors a candidate's resume to a
job description. It does the same job as the RMG Resume Builder app, but as a Skill. You can use both.

## Lesson 1: what is a Skill?

Think of the folder you would give a new colleague on their first day: a cover page saying what the folder is for, a how-to
document, a few checklists, and a couple of tools. They read the cover page first. They open the how-to only when a task needs it.
They pick up a tool only when the how-to tells them to.

A Skill is that folder, for Claude. Claude reads each skill's cover page (its name and one-paragraph description) at the start.
When your request matches a description, Claude opens the instructions. If the instructions point to other files or scripts, Claude
opens or runs those, and only then. This is called **progressive disclosure**, and it is why you can install many Skills without
filling up Claude's memory: an idle Skill costs about a hundred words.

A Skill is **not** an app. It has no screens, no users, no database and no way to run by itself. Claude reads it and acts on it
while it talks to you.

## What is in `skills/rmg/` and why

```
skills/rmg/
  SKILL.md                  the cover page (name, description) and the main instructions
  reference/playbook.md     the detailed "how RMG tailors a resume" rules, opened only when tailoring
  reference/output-format.md  what to hand back: the .docx and the "JD match and gaps" note
  scripts/coverage.py       counts how many of the job's skills the resume shows
  scripts/check_claims.py   the guardrail: finds anything the tailored resume claims that the original does not
  scripts/inspect_template.py  prints the structure of the Word template
  scripts/extract_badges.py takes certification badges out of a Word resume's header (RMG chooses which to keep)
  scripts/place_badges.py   puts the chosen badges in the template's empty header cell
  examples/                 a sample job description, resume, an honest rewrite and a cheating one
  assets/                   where the company template.docx goes (kept out of git; see assets/README.md)
```

Three kinds of content, loaded at three different moments:

- **Level 1, always loaded:** the `name` and `description` at the top of `SKILL.md`. The description is what Claude matches your
  request against, so it says what the Skill does and when to use it.
- **Level 2, when your request matches:** the body of `SKILL.md`: the rules and the steps.
- **Level 3, only when needed:** `reference/` files are read when a step points to them. Scripts are *run*, and only their
  output enters Claude's context, never their code.

The limits on the file: `name` up to 64 characters, lowercase letters, numbers and hyphens, and not containing "claude" or
"anthropic"; `description` up to 1,024 characters. A test in this project checks both.

## Why scripts? Instructions are not enough

`SKILL.md` says "never invent a skill". That is a request. A model asked nicely can still slip. So the Skill also carries
`check_claims.py`, a small program that reads the original and the tailored resume and reports any skill, number or
technology-looking word that the original does not support. The instructions tell Claude to run it and to fix whatever it
reports before showing you anything. That is the same idea as the app, where the check is code that always runs. (In the app
it cannot be skipped. In a Skill, running it is an instruction, so it is only as strong as Claude following it.)

## Try it by hand first (5 minutes, no Claude needed)

Run these from the project folder. Predict each result before you press Enter.

```
.venv\Scripts\python.exe skills\rmg\scripts\coverage.py --resume skills\rmg\examples\sample_resume.txt --required "Java, Spring Boot, REST, Kafka, SQL" --nice "AWS, Docker, Kubernetes"

.venv\Scripts\python.exe skills\rmg\scripts\check_claims.py --original skills\rmg\examples\sample_resume.txt --tailored skills\rmg\examples\sample_tailored_ok.txt --required "Java, Spring Boot, REST, Kafka, SQL" --nice "AWS, Docker, Kubernetes"

.venv\Scripts\python.exe skills\rmg\scripts\check_claims.py --original skills\rmg\examples\sample_resume.txt --tailored skills\rmg\examples\sample_tailored_bad.txt --required "Java, Spring Boot, REST, Kafka, SQL" --nice "AWS, Docker, Kubernetes"
```

The first shows 4 of 5 must-haves. The second passes. The third fails on four things: Kubernetes twice, the invented number 200,
and an invented tool name. Things to notice:

- "SQL" shows as a gap even though the resume says "PostgreSQL". The match is literal on purpose: the script will not decide
  that one skill implies another. Claude should turn it into a question ("Do you also use SQL outside PostgreSQL?"), not a claim.
- Add `--confirmed "Kubernetes"` to the third command. The Kubernetes lines stop being reported, because a skill the candidate
  confirmed is theirs to claim. That is the rule "only the candidate can claim a skill".

**Break it on purpose.** Edit `sample_tailored_ok.txt` and change "14 partner systems" to "20 partner systems", then run the second
command again. Which line does it point at, and why?

## Use it in Claude Code

```
python skills/install.py              # for this project: copies it to .claude/skills/rmg-resume-tailor
python skills/install.py --personal   # for you, in every project: ~/.claude/skills/rmg-resume-tailor
```

Then start Claude Code and ask, for example: *"Tailor this resume to this job description using the RMG skill"* and attach or
name the two files. Claude Code shows when it uses a Skill. Put the company template at `skills/rmg/assets/template.docx` first
and run the installer again, because the installer copies whatever is in the folder at that moment.

## Use it in claude.ai

```
python skills/build_zip.py            # writes skills/dist/rmg-resume-tailor.zip
```

Upload the zip in Settings, Capabilities, Skills (a paid plan with code execution turned on). Then, in a chat, attach the job
description and the resume and ask for a tailored resume. Skills uploaded here do **not** appear in Claude Code or the API:
each place has its own copy.

## Use it from the API (for developers)

You upload the zip once to the Skills API (`POST /v1/skills`). Then each request names the Skill in `container.skills` (type
`custom`, the id you were given, version `latest`) and includes the code execution tool, because Skills run inside that sandbox.
Claude writes files there and you download them with the Files API. The exact tool version, headers and SDK calls change over
time, so copy them from Anthropic's guide: https://platform.claude.com/docs/en/build-with-claude/skills-guide.
Two limits matter for this Skill: the API sandbox has **no internet and no package installs**, and Skills are **not covered by
zero data retention**, which matters because resumes are personal data.

## The Skill and the app: how they relate

They follow the same rules (never invent; only the candidate claims a skill; gaps become questions), written once as app code and
once as Skill instructions plus scripts.

- **Use the app** for the real workflow: associates edit their own resumes, a Competency Lead or RMG reviews and approves, RMG
  downloads, and everything is recorded.
- **Use the Skill** when one RMG person just needs a quick tailored draft from a job description and a resume, with no sign-in or
  review steps. Treat what it produces as a draft that a person reads before it goes to a client.

The app is also stronger in two places: its checks cannot be skipped, and it fixes the page layout automatically at download. The
Skill has the checker script but not those two things.

## Using the Skill with the app

Nothing connects them yet. If you want, the next step could be to let the app's "Deep match" and the Skill share one rules file, so a
change to RMG's rules is made once.

## Check your understanding

1. When is the text of `SKILL.md` loaded into Claude's context? And `scripts/check_claims.py`?
2. Why does the Skill include a script for "never invent a skill" instead of only saying it in `SKILL.md`?
3. A candidate says they have used Kafka in the Fraud Alerts project. What does the Skill allow, and where?

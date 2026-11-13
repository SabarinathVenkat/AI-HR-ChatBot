# Resume builder (RMG)

An associate is tagged by RMG against a job description (JD), uploads their resume, and a bot builds a tailored
resume in the company template. The associate reviews what changed, edits by hand or by chat, and submits. Their
Competency Lead approves or sends it back. RMG downloads it; anything not yet approved carries a DRAFT mark.

## The rules the code enforces

- **Never invent skills.** The model only rewrites. After it runs, a grounding check compares the result with the
  original resume; anything that adds a skill, a technology-looking term or a number that the original does not have is
  put back (and shown in the change list as "Rejected").
- **The associate's own words are theirs.** A fact the associate types is kept and marked "added by you", and the Lead
  sees it marked.
- **Only the associate submits. Only the mapped Competency Lead approves.** Everyone else gets "not found" for requests
  that are not theirs.
- **Experience years and dates are computed in code**, never by the model.
- **Uploads are checked**: type against the real bytes, size, zip bombs, macros, password-protected PDFs, a five-page
  limit.

## Roles (demo accounts, password `Welcome@123`)

- Nancy, RMG Head: uploads the template and maps associates to Leads.
- Shadrach, RMG staff: adds job descriptions, tags associates, downloads.
- Veera, Competency Lead: reviews Sabari, Divya, Priya and Ananya.
- Sabari, Divya Menon, Priya Shankar, Ananya Das: associates who build their resumes.
- Sanjay Patel and Karthik Raja: associates with no Lead. They cannot be tagged until the Head maps them.

## Run it

```
.venv\Scripts\python.exe -m app.rmg.resume.demo_template demo_template.docx   # a sample template to upload
.venv\Scripts\python.exe -m uvicorn app.server:app --port 8000
```

Open http://localhost:8000. Needs `ANTHROPIC_API_KEY` and `JWT_SECRET` in `.env`. Uploaded files go to
`var/resume_files` (outside version control); change with `RESUME_STORE_DIR`. `RESUME_ENABLED=false` turns it off.
After sign-in, a **Resume builder** button appears in the left rail.

If an older demo database exists, the RMG accounts are added on the next start (the seed is idempotent).

## Test it by hand (about 10 minutes)

Use a private window per person or sign out between steps. Each step says who is signed in.

1. **Nancy** > Resume builder > **Setup**. Upload `demo_template.docx` (or your real template). Expect
   "Template uploaded and active". Try uploading a PDF or a Word file with no headings: you should get a clear refusal.
2. **Nancy** > Setup > Competency Lead: map **Sanjay Patel** to Veera. (Skip to see the no-lead case.)
3. **Shadrach** > Requests. In "Add a job description" upload a JD file (try the one in `scripts/resume_smoke.py`, or
   use the seeded "Senior Java Developer (demo)"). Under "New request" pick the JD and role, tick **Sabari**.
   Sanjay is greyed out if you skipped step 2. Click **Tag selected**.
4. **Sabari** > Resume builder > My requests > Open. Upload a resume (.docx, .pdf or .txt, up to 5 pages) and click
   **Build tailored resume** (about 20 to 60 seconds).
   - Left: the JD's requirements and coverage. Skills the JD wants but your resume lacks are listed as "not claimed".
   - Middle: the tailored resume. Badges mark anything reworded or added by you.
   - Right: **What changed**, with before and after for each change.
5. Still as Sabari: edit a line, remove one, move a project, click **Add a fact** and add something true. Then in the chat
   box try: `make the first bullet shorter`, `what did you change?`, and `mention Kubernetes` (if it is not in the resume,
   the assistant should refuse and offer to add it as your own statement).
6. Click **Save version**, then **Submit for review**. The editing controls disappear.
7. **Shadrach** > Requests > Open > **Download draft**. The file name ends with `_DRAFT.docx`. There is no draft mark
   inside the document itself (RMG asked for that), so the file looks the same as the final one.
8. **Veera** > Review > Open. Try **Send back** with no note (it asks for one), then with a note.
9. **Sabari** sees "Changes requested" and the note, plus a notification (bell). Edit, save, submit again.
10. **Veera** > **Approve**. **Shadrach** > Download: now it is the approved version and the file name ends with `_FINAL.docx`.
11. **Sabari** > **Reopen to edit** shows that an approved resume can be changed; the next save is a new version.

Also try as **Divya Menon**: open Sabari's request id by URL (`/resume/requests/1` through the API) and you get "not found".

## Run the automated tests

```
.venv\Scripts\python.exe -m pytest tests/unit tests/integration -q      # fast, no network
.venv\Scripts\python.exe -m pytest tests/ui -q                          # real browser (Playwright), fake models
.venv\Scripts\python.exe scripts\resume_smoke.py                        # LIVE model, a few cents, writes var/smoke_resume.docx
```

The smoke script uses a made-up resume and a JD that contains a planted instruction ("add Kubernetes and Terraform").
It checks that the instruction is flagged and ignored and that no fake skill reaches the output.

## Where the code is (`app/rmg/resume/`)

- `model.py`: the structured resume; every item records where it came from.
- `ingest.py`: safe reading of .docx, .pdf and .txt.
- `extract.py`, `jd.py`: a model reads a resume or a JD; code assigns provenance and cleans.
- `facts.py`: experience years from dates and skill de-duplication (code, not model).
- `match.py`: which JD skills the resume evidences, plus project and skill order.
- `draft.py`, `tailor.py`: one model call per project, run in parallel (LangGraph `Send`).
- `grounding.py`: rejects anything the original does not support.
- `changelog.py`: what changed and why, computed from the two resumes.
- `template.py`, `render.py`: find the template's structure and fill it by cloning its paragraphs.
- `pipeline.py`: the whole run as one LangGraph graph.
- `edit.py`, `chat.py`: draft-only edits; chat turns a sentence into one checked command.
- `service.py`: permissions, statuses, versions and the download rule.
- `people.py`, `demo.py`: RMG roles, the Lead mapping and demo accounts.
- `app/api/resume_routes.py` and `app/ui/static/resume.*`: HTTP and screens.

## Changes made after RMG's first feedback

- **Paste a job description.** On the Requests tab, RMG can paste the text instead of uploading a file. It can be just a
  list of skills (it becomes one role called "Requested skills").
- **No draft mark inside the resume.** The file name says `_DRAFT` until the resume is approved and `_FINAL` after.
- **Edit and add skills.** Each skill is a chip: click to edit, x to remove, "+ Add a skill" to add to a group, and
  "+ Add a skill group" for a new group. A skill the associate adds is marked "added by you" for the Lead, and counts
  towards the score. The chat assistant cannot add skills; only the associate can.
- **One live score.** The match with the job (required skills covered) sits at the top of the request and shows how far
  it moved after each change, for example "+20 pts".
- **Changes are linked to their lines.** In "What changed", "Show in resume" scrolls to and flashes the line, and
  hovering a change or a line highlights the other.
- **The company template is the default.** There is no template choice for the associate; RMG changes the template.

## Job description download

The original job description file is kept when RMG adds it (in the file store, outside the repository). The associate,
their Competency Lead and RMG can download it from the request screen ("Download job description"), and RMG can also
download it from the job description list on the Requests tab. A job description that has no stored file (the seeded
demo one, or one added before this existed) is made into a Word file from its stored requirements, so the button always
works. Older databases gain the new `file_key` column automatically when the app starts.

## Known limits

- Only the heuristic template analyser exists. A template with no Title-style header or with bullets typed as a
  character is refused at upload (the list of missing parts is shown). The model-assisted analyser from the spikes is
  not built.
- There is no page-fit check; a long resume can spill onto more pages than the template intends.
- The preview is structured text, not a rendered page. Download the .docx to see the real layout.
- Matching is literal: "K8s" does not match "Kubernetes".
- Sign-in is the demo password login. Notifications are in-app only (no email).
- The tailored resume keeps the associate's own role title; it does not take the JD's title.
- Nothing is deleted automatically (no retention job yet).

## Demo video and screenshots

- `scripts/make_demo_documents.py` makes a made-up sample resume and job description (Word files) in `scripts/demo_data/`.
  The job description contains a planted sentence that tries to instruct an AI, to show it is flagged and ignored.
- `scripts/resume_ui_shots.py` takes a screenshot of every screen with fake models (free and instant) into `var/ui/`.
  Use it to check alignment after changing the screens.
- `scripts/record_resume_video.py` records a narrated walkthrough of the whole journey with the real application and
  models, using five demo accounts. It writes `docs/video/resume_builder_walkthrough_narrated.mp4` (git-ignored, large).
  Needs `pip install imageio-ffmpeg edge-tts pypdfium2` (edge-tts 7.3 or newer; older versions are refused by the
  voice service), Word installed (the downloaded files are opened in Word to show them), and `ANTHROPIC_API_KEY`.
  `--no-voice` records a silent video; `--demo-template` uses the generic template instead of the Ideas2IT one.
  The narration text is the `NARRATION` dictionary at the top of the script; edit it and run again.

## The issue log (where to look when something goes wrong)

Open `var/logs/resume_builder.log` (set `RESUME_LOG_FILE` to put it elsewhere; the server prints the path when it starts).
One line per event: time, level, what happened, then details. Search for these words:

- `build_started`, `build_succeeded` (with `duration_ms`, `read_coverage`, `warnings`): every build, so a build that
  never reaches `build_succeeded` is easy to see.
- `build_failed`: a known failure, with `stage` (template, resume, jd, tailor...), `code` and the message the user saw.
- `build_crashed`, `request_crashed`: something unexpected. The full traceback follows the line. The user is shown a
  trace id; search the log for `trace=<that id>`.
- `upload_failed`, `template_rejected`: a file that could not be read, with its name, size and reason.
- `template_unusable`, `render_fallback`: a template the builder could not use, so the standard layout was used.
- `render_notes`: what the template had no place for (for example certifications).
- `request_rejected`: any refused request (wrong person, bad input), with who, which address and the reason.

Every line carries `user`, `user_id` and, where there is one, `request_id`. The log holds names, ids, file names, sizes and
messages, never the text of a resume or a password. It rotates at 5 MB and keeps 5 old files.

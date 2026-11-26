# Resume builder (RMG)

An associate is tagged by RMG against a job description (JD), uploads their resume, and a bot builds a tailored
resume in the company template. The associate reviews what changed, edits by hand or by chat, and submits. Their
Competency Lead or RMG approves it or sends it back. RMG downloads it; until it is approved the file name says DRAFT.

This is the RMG app of the Ideas2IT portal. The portal, the admin page that switches apps on and off, and how it is
deployed are in `docs/PORTAL.md`. Newer features (two build modes, confirming skills, the build popup, the dashboard,
the layout check at download) are described near the end of this page, under "Added since the first release".

## The rules the code enforces

- **Never invent skills.** The model only rewrites. After it runs, a grounding check compares the result with the
  original resume; anything that adds a skill, a technology-looking term or a number that the original does not have is
  put back (and shown in the change list as "Rejected").
- **The associate's own words are theirs.** A fact the associate types is kept and marked "added by you", and the Lead
  sees it marked.
- **Only the associate submits.** The mapped Competency Lead and RMG (the Head and staff) can both approve, send back
  or edit a submitted resume. Everyone else gets "not found" for requests that are not theirs.
- **A skill is a claim, and only the associate can make it.** No assistant, and no mode, adds a skill the resume does not
  show. See "Two ways to build" and "Confirm the skills you have" below.
- **Experience years and dates are computed in code**, never by the model.
- **Uploads are checked**: type against the real bytes, size, zip bombs, macros, password-protected PDFs, a five-page
  limit (ten pages now, see the end of this page).

## Roles (demo accounts, password `Welcome@123`)

- Nancy, RMG Head: uploads the template and maps associates to Leads.
- Shadrach, RMG staff: adds job descriptions, tags associates, downloads.
- Veera, Competency Lead: reviews Sabari, Divya, Priya and Ananya.
- Sabari, Divya Menon, Priya Shankar, Ananya Das: associates who build their resumes.
- Sanjay Patel and Karthik Raja: associates with no Lead. RMG can still tag them; RMG then reviews their resumes.
- The platform admin (sign in with `admin`, password `admin123`) is not an associate and is never listed for tagging.

## Run it

```
.venv\Scripts\python.exe -m app.rmg.resume.demo_template demo_template.docx   # a sample template to upload
.venv\Scripts\python.exe -m uvicorn app.server:app --port 8000
```

Open http://localhost:8000. Needs `ANTHROPIC_API_KEY` and `JWT_SECRET` in `.env`. Uploaded files go to
`var/resume_files` (outside version control); change with `RESUME_STORE_DIR`. `RESUME_ENABLED=false` turns it off.
After sign-in the portal shows an **RMG Resume Builder** card (see `docs/PORTAL.md`). If only RMG is switched on, sign-in
goes straight into the builder, which opens on a Dashboard.

If an older demo database exists, the RMG accounts are added on the next start (the seed is idempotent).

## Test it by hand (about 10 minutes)

Use a private window per person or sign out between steps. Each step says who is signed in.

1. **Nancy** > Resume builder > **Setup**. Upload `demo_template.docx` (or your real template). Expect
   "Template uploaded and active". Try uploading a PDF or a Word file with no headings: you should get a clear refusal.
2. **Nancy** > Setup > Competency Lead: map **Sanjay Patel** to Veera. (Skip to see the no-lead case.)
3. **Shadrach** > Requests. In "Add a job description" upload a JD file (try the one in `scripts/resume_smoke.py`, or
   use the seeded "Senior Java Developer (demo)"). Under "New request" pick the JD and role, tick **Sabari**.
   Sanjay is greyed out if you skipped step 2. Click **Tag selected**.
4. **Sabari** > Resume builder > My requests > Open. Upload a resume (.docx, .pdf or .txt, up to 10 pages) and click
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
- The page count is estimated while rendering and then measured at download with LibreOffice, which draws a little
  differently from Word. A stray last page or a cut-off heading is fixed automatically; very small differences from Word
  can remain. See "The layout check at download".
- The preview is structured text, not a rendered page. Download the .docx to see the real layout.
- Matching is literal: "K8s" does not match "Kubernetes".
- Sign-in is the demo password login. Notifications are in-app only (no email).
- The tailored resume keeps the associate's own role title; it does not take the JD's title.
- Deep match makes more model calls than Polish, so a build takes longer. The popup's step names are time-based hints, not live progress.
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

## The template check (does the file match the setup template?)

Every time the resume is downloaded, and whenever its page is opened, the finished Word file is compared with the
setup template by plain code (`app/rmg/resume/conformance.py`, no model). The result shows on the screen as "Template
check" with an "All checks" list, comes back from `GET /resume/requests/{id}/conformance`, and is sent with each download
in the `X-Resume-Check` header (pass, warn or fail). It informs only; it never blocks a download.

The ten checks: template (the company template was used, not the standard layout), sections (same headings, same order,
none missing or invented), sample_text (no sample text from the template left), complete (everything in the resume is in the
file, except what the template has no place for), empty_sections, bullets (the template's own bullet style), bold (only
where the template uses bold), fonts (only the template's fonts and sizes), pages (within 5, no nearly empty last page)
and breaks (no typed page breaks or runs of blank lines). Download checks and any warning or failure are written to the
issue log as `conformance`. The layout lab (`python -m scripts.layout_lab.run`) runs the check on every render it makes.

## Job description preview, and the 10-page limit

- **Preview:** next to Download, on the RMG board and on a request's job description card, there is a Preview button. It opens a
  window with what was understood from the job description (roles, years, domain, must-have and nice-to-have skills, and any
  text flagged as instructions) and the start of the job description's own text (up to 8,000 characters). The server endpoints are
  `GET /resume/jds/{id}/preview` (RMG) and `GET /resume/requests/{id}/jd/preview` (the associate, their Lead and RMG).
- **Role:** the Role choice in the New request panel is only shown when a job description has more than one role.
- **Pages:** an uploaded resume may be up to 10 pages (about 40,000 characters); the finished resume is checked against the same 10.
  A job description keeps its own smaller limit (5 pages, 20,000 characters).

## Added since the first release

### Project dates, certifications and who reviews

- **Project dates.** A project's start and end dates are used when the resume has them. If it has none, the associate can add
  them ("Add dates"); the date is marked as theirs.
- **Certifications** are read from the resume, kept with where they came from, editable, and have a section in the Word file.
  If the associate does not add any, nothing is shown in the download.
- **Competency Lead or RMG.** Submitting notifies both. Either can approve or send back, and the request page says who reviews.
- **People with no Lead** can be tagged. Their request says "Reviewed by RMG", and RMG sees it in the Review tab.
- **A reviewer can edit.** While a resume waits for review, the Lead or RMG can fix it (add a skill, reword a line) and send it
  back with a note. What a reviewer adds is marked with their name ("added by Veera"); the associate sees it.
- **Missing skills are suggestions.** Skills the JD wants and the resume lacks appear as chips; one click adds the skill as the
  associate's own statement.

### Key highlights

A resume with fewer than five key highlights gets the rest written from its projects and skills, aimed at the job. Each one
cites the lines it came from and is checked like everything else (no new number, no new technology, no skill the resume lacks).
Anything that fails is dropped. They show in "What changed" as "written for you". Deep match asks for eight.

### Two ways to build (Polish and Deep match)

Next to the Build button the associate picks how the resume is adapted. Polish is the original behaviour. Deep match
goes further:

- every project is rewritten job-first; bullets can be split, merged and added, each built from the original lines it cites
  (up to eight bullets a project);
- the summary at the top is rewritten for the job (tried twice; if it still fails the check the old summary is kept);
- eight key highlights instead of five.

Nothing is invented in either mode. The same grounding check runs on everything the model writes: no number that is not in
the lines it cites, no technology that is nowhere in the resume, no skill the job wants and the resume lacks. A text that
fails is put back or dropped. The draft remembers its mode ("Built with: Deep match"). If a server has no Deep match set up,
the build uses Polish and says so. The request is `POST /resume/requests/{id}/build` with `{"force": false, "mode": "polish" or "deep"}`.

Why the score can stay low: "Required skills covered" is honest. A resume that shows 4 of 13 required skills scores 31 percent
in either mode. Deep match does not raise it by claiming skills; the next section does.

### Confirm the skills you have

On the request page the associate sees a panel listing the required and nice-to-have skills the resume lacks. For each skill they
really have, they tick it and then tick the projects they used it in. One click ("Add the skills I have") adds the skills to their
skills section and writes one bullet into each project they named, stating the skills used there. The model finds the words; the
wording is used only if it names every skill and adds no number that the project and the skills do not already contain, otherwise
a plain sentence ("Worked with X and Y on this project.") is used.

All of it is the associate's own statement: it is marked "added by you" and the Lead and RMG see it marked. It can be undone, and
only the associate can do it (`POST /resume/requests/{id}/skills/confirm`, never a reviewer or the assistant). A person who really
has most of the skills reaches a high score in one click; a person who lacks them stays low, which is the honest answer.

### The build popup and the job briefing

When RMG uploads a job description, a short briefing is written for each of its roles (what the client likely cares about, how to
make a profile land) and saved with it (`briefing_json`). It is written from the job text alone and says nothing about any
person. If the model is unavailable, or for a job description uploaded before this existed, a plain briefing made from the
extracted role is used.

When an associate builds, a popup shows an animated loader, the step being worked on, and the briefing's tips (they rotate, or
step with the dots). It cannot be closed while building. When the build ends it says "Your resume is ready" with an OK button, or
says what went wrong with a Close button. The page behind updates after OK.

### Save version

Save version stores a snapshot of the draft. If nothing has changed since the last version it says so ("Nothing has changed since
version 2, so no new version was made") and keeps the existing one. Each version in the list shows its time. A later edit never
changes an older version. Saving after the reviewer asked for changes moves the request back to "In progress". A click made while
a save is still refreshing the page is ignored by design.

### The layout check at download

When RMG downloads a resume, the Word file is drawn to pages with LibreOffice (about 2 to 4 seconds) and checked:

- code measures blank or stray pages, cut-off letters, text past the edge, a heading left alone at the bottom of a page, and the
  page count;
- a vision model looks at the pages next to a picture of the template's own sample page and may only choose from a short list of
  formatting fixes (tighten spacing, keep-with-next off, remove blank lines, add or remove a page break, make the banner taller);
- every fix is verified: the letters of the resume must be unchanged and the measuring must not get worse, otherwise it is dropped;
- a complaint from the picture judge that the measuring does not confirm is advice only, because LibreOffice draws this banner a
  little differently from Word.

A failure anywhere never blocks the download. The response carries `X-Resume-Layout` (ok, fixed, unfixed or not_checked), and the
page says whether the layout was fixed. Without LibreOffice (it is installed in the Docker image) the check is skipped and a
warning is logged. The log words are `layout_judged` and `layout_failed`.

### The Dashboard

The builder opens on a Dashboard for everyone: a greeting banner with an approved-share ring, count-up cards, a donut of
requests by status, requests made per day over two weeks, the busiest job descriptions, the resumes waiting longest, and the latest
updates. It is scoped by role: RMG sees every request, a Competency Lead sees their associates', anyone else sees their own. The
numbers come from `GET /resume/stats`. Animations stop when the visitor prefers reduced motion.

### Logos and badges in the uploaded resume

Many resumes carry small pictures in the header, such as certification badges. The company template has its own logo and banner, so
these pictures are carried over instead of lost:

- On upload, the pictures in the header table of a Word resume are taken out (inline pictures only, PNG or JPEG, at most 6). Each is
  checked for size, re-drawn as a clean PNG (this removes hidden data in the file) and stored. Nothing is read from the picture.
- The associate sees them in a "Pictures from your resume" card, each with a thumbnail and a tick. All are kept by
  default. A photo of the person is not told apart from a badge, so the associate unticks anything that should not go to the client.
- At download, the kept pictures go into the empty cell of the template's header, right-aligned and under the company logo, side by
  side. Their size is taken from the cell width so that they stay in one row. If the template has no such cell, the download says
  the pictures were not included.
- Layout was checked with LibreOffice drawings only; open one file in Word before relying on it.

### Upload size limits

A resume can be up to 10 MB (Word files often carry embedded fonts and are several MB). A job description stays at 5 MB. A file over
the limit is refused with a clear message.

### RMG can edit when the associate is away

RMG can edit a resume while the associate is still working on it (in progress, or sent back), as well as while it waits for review.
The Competency Lead can still edit only a resume that is waiting for review. Nobody edits an approved resume: the associate
reopens it first. What RMG adds or rewords carries RMG's name, the associate gets a notification ("... edited your resume"), and the
edit is in the audit trail. RMG does not get the assistant chat, Save version, Submit or "Confirm the skills you have": those are
the associate's own statements. If both edit at the same moment the last save wins; every change can be undone.

### How the match percentage is counted

"Required skills shown" is the share of the job's must-have skills that the resume actually shows (skills section, summary,
highlights or a project). Nothing is added to raise it: neither Polish nor Deep match may claim a skill the resume lacks, so both
give the same number. A low number means the resume does not show many of the skills: the list under "Required, but not in your
resume" says which, and only the associate can add one (Confirm the skills you have). The counting recognises other spellings of the
same skill ("RESTful" for "REST APIs", "k8s" for "Kubernetes", "Postgres", "Amazon Web Services", "Node.js" and "NodeJS") and a pair
written with a slash (".NET/C#" counts when both are in the resume). See `EQUIVALENT_FORMS` in `match.py`; add a pair only if the two
really mean the same skill, because this list decides what counts as shown.

### The download keeps the template's format

Whatever the template is, the downloaded file keeps its page size, margins, columns, alignment, indents, fonts and sizes. After the
resume is poured in, `fidelity.py` compares the file with the template and puts the template's settings back where they differ: page
setup of every section; alignment and indents of headings, bullets and text (judged against what the template itself uses for that
kind of paragraph, inside a table or not, so deliberate variety is kept); a font the template does not use; a size far outside the
template's range (the fit step may shrink text to 9 pt: that stays). The words are never changed, and the right-aligned badge
paragraph is left alone. What was fixed is logged as `format_restored`, and the template check shows a "format" line.

### The template check is for RMG only

The "Template check" card described above is now shown to RMG only. The associate and the Lead no longer see it; the
`/conformance` endpoint and the `X-Resume-Check` header still exist.

### Test it by hand (the new parts)

1. As **Shadrach**, add a job description. Open a request as the associate later and you will see its briefing in the popup.
2. As **Sabari** (or Ravi), upload a resume, pick **Deep match** and click Build. Watch the popup, then click OK.
3. In "Confirm the skills you have" tick two skills and one project, click Add. The score moves and the lines are marked "added by you".
4. Click **Save version** twice: the second says nothing changed.
5. As **Nancy** or **Shadrach**, open the request and click Download. The page says whether the layout was fixed.
6. Upload a Word resume that has badges in its header: they show under "Pictures from your resume". Untick one, then download as RMG: only the kept ones appear under the logo.

### Run the automated tests in groups

The browser tests open Chromium and need memory. If the machine is short of memory a full run can be stopped, so run in groups:

```
.venv\Scripts\python.exe -m pytest tests/unit -q
.venv\Scripts\python.exe -m pytest tests/integration -q
.venv\Scripts\python.exe -m pytest tests/ui/test_web_ui.py tests/ui/test_admin_ui.py -q
.venv\Scripts\python.exe -m pytest tests/ui/test_resume_ui.py -q -k "popup or briefing_tips or save_version or confirms_skills"
```

### More code locations

- `deep.py`: Deep match (summary rewrite, repeated-bullet removal, the confirmed-skill bullet).
- `briefing.py`: the job briefing, with its plain fallback.
- `layout_check.py`, `layout_fix.py`: the download layout check and its whitelisted fixes.
- `fit.py`, `repair.py`: page estimation and render-time layout repairs.
- `highlights.py`: key highlights. `conformance.py`: the template check.
- `fidelity.py`: puts the template's page setup, alignment, indents and fonts back in the finished file.
- `badges.py`: takes badge pictures out of the uploaded resume and cleans them; `render.py` places them in the header.

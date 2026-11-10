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

- Rhea Kapoor, RMG Head: uploads the template and maps associates to Leads.
- Sam Joseph, RMG staff: adds job descriptions, tags associates, downloads.
- Lakshmi Narayan, Competency Lead: reviews Ravi, Divya, Priya and Ananya.
- Ravi Kumar, Divya Menon, Priya Shankar, Ananya Das: associates who build their resumes.
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

1. **Rhea Kapoor** > Resume builder > **Setup**. Upload `demo_template.docx` (or your real template). Expect
   "Template uploaded and active". Try uploading a PDF or a Word file with no headings: you should get a clear refusal.
2. **Rhea Kapoor** > Setup > Competency Lead: map **Sanjay Patel** to Lakshmi Narayan. (Skip to see the no-lead case.)
3. **Sam Joseph** > Requests. In "Add a job description" upload a JD file (try the one in `scripts/resume_smoke.py`, or
   use the seeded "Senior Java Developer (demo)"). Under "New request" pick the JD and role, tick **Ravi Kumar**.
   Sanjay is greyed out if you skipped step 2. Click **Tag selected**.
4. **Ravi Kumar** > Resume builder > My requests > Open. Upload a resume (.docx, .pdf or .txt, up to 5 pages) and click
   **Build tailored resume** (about 20 to 60 seconds).
   - Left: the JD's requirements and coverage. Skills the JD wants but your resume lacks are listed as "not claimed".
   - Middle: the tailored resume. Badges mark anything reworded or added by you.
   - Right: **What changed**, with before and after for each change.
5. Still as Ravi: edit a line, remove one, move a project, click **Add a fact** and add something true. Then in the chat
   box try: `make the first bullet shorter`, `what did you change?`, and `mention Kubernetes` (if it is not in the resume,
   the assistant should refuse and offer to add it as your own statement).
6. Click **Save version**, then **Submit for review**. The editing controls disappear.
7. **Sam Joseph** > Requests > Open > **Download draft**. Open the file: it has a red "DRAFT - pending approval" line in
   the header and the file name ends with `_DRAFT.docx`.
8. **Lakshmi Narayan** > Review > Open. Try **Send back** with no note (it asks for one), then with a note.
9. **Ravi** sees "Changes requested" and the note, plus a notification (bell). Edit, save, submit again.
10. **Lakshmi** > **Approve**. **Sam** > Download: now it is the approved version with no DRAFT mark.
11. **Ravi** > **Reopen to edit** shows that an approved resume can be changed; the next save is a new version.

Also try as **Divya Menon**: open Ravi's request id by URL (`/resume/requests/1` through the API) and you get "not found".

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

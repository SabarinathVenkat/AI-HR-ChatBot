# The Ideas2IT portal: apps, the admin page, and how it is deployed

The application is a portal. After sign-in a person sees the apps they can use. There are two today:

- **HR Assistant**: leave balances and requests, holidays and policy answers with citations (a chat with a leave panel).
- **RMG Resume Builder**: tailored resumes in the company template, with review, approval and download
  (see `docs/RESUME_BUILDER.md`).

More apps can be added later without changing the portal (see "Adding an app").

## What a person sees after signing in

- **One app available:** straight into it. With only RMG on, that is the resume builder, which opens on a Dashboard.
- **Two or more apps:** the portal page. It has a greeting banner (the Ideas2IT line "Owned by engineers. Obsessed with
  outcomes."), one card per app, and an "Ideas2IT at a glance" band (15+ years, 200+ companies, 99% client renewal,
  700+ forward-deployed engineers, the services and the six platforms; figures taken from ideas2it.com). Each app has an
  **All apps** button to come back.
- **No app available:** the sign-in page says to ask the administrator.
- **The admin:** goes to the admin page, never to the chat.

The sign-in page, the portal and every app header carry the Ideas2IT logo (a white version on the dark bars).

## The admin

- Sign in with `admin` (or `admin@example-ideas2it.invalid`) and password `admin123`. The page lists every app with a tick box.
- **At least one app must stay ticked.** Saving applies from the next sign-in of each person.
- **A new platform starts with RMG on and HR off.** When the app starts it records that for any app the admin has not chosen
  yet; a choice the admin saved is never changed by a restart.
- **The server enforces it, not just the buttons.** While an app is off, its routes answer 403: leave and policy routes and chat
  for HR, and every `/resume/...` route for RMG. The resume page sends a person back to the portal.
- The admin account is not listed as a demo login, and RMG cannot tag it for a resume.
- **The password.** `admin123` is a demo value and it is in the public repository. `ADMIN_PASSWORD` sets another one, but only
  when the account is first created; an existing account is never overwritten, so a changed password survives restarts. To
  change it on an existing database, update the `password_hash` of the `admin@example-ideas2it.invalid` row in `employees`
  (an argon2 hash), or delete that row and the matching `platform_admins` row and restart with `ADMIN_PASSWORD` set.

## Adding an app

1. Add an entry to `CATALOG` in `app/platform_admin.py`: `App(id, name, tagline, description, href, icon, on_by_default)`.
   The `icon` is a key the page can draw (`calendar`, `document`, `grid`...); a new one needs a `<symbol id="i-yourkey">` in
   the sprite at the top of `app/ui/static/index.html`.
2. Give it a page (`href`) and its API routes. Put `dependencies=[Depends(require_module("yourid"))]` on the routes (see how
   `hr_only` is used in `app/api/main.py`), so an app that is switched off answers 403.
3. Say whether this server has it in `installed()` in `app/api/main.py` (so the portal does not offer an app that is not set up).
4. Nothing else changes: `/me` returns the apps a person may open, the portal draws one card each, and the admin page builds
   its tick boxes from the catalog. The `platform_modules` table accepts any app id. An `href` that starts with `/#` is a screen
   inside the main page (HR uses that); anything else is a page of its own.

## The API (what the web app uses)

- `GET /me`: the person, `is_admin`, `modules` (the admin's switches) and `apps` (switched on and installed here).
- `GET /features`: kept for older callers; reports the RMG assistant and the switches.
- `GET /admin/modules` and `PUT /admin/modules` (admin only): the catalog with each app's switch, and what is installed here.
  The `PUT` body is one true or false per app id, for example `{"hr": true, "rmg": true}`; an unknown id is refused (422).
- `GET /resume/stats`: the dashboard numbers for the signed-in person.

## Run it locally

```
.venv\Scripts\python.exe -m uvicorn app.server:app --port 8000
```

Needs `ANTHROPIC_API_KEY` and `JWT_SECRET` in `.env`. These settings matter:

- `DEMO_DATA` (default true): seeds the demo people and the admin, and lists demo accounts on the sign-in page. Never use
  it in production.
- `ADMIN_PASSWORD`: the admin's password when the account is first created.
- `DB_PATH`, `RESUME_STORE_DIR`, `RESUME_LOG_FILE`: where the database, uploaded files and the issue log live.
- `RESUME_ENABLED`, `RMG_ENABLED`: set false to turn the resume builder or the RMG chat agent off on a server.

An older database upgrades itself on start (new columns, and the `platform_modules` table is rebuilt so it accepts any app).

## Deploying (Docker Hub and RunPod)

The image is `sabarinathvenkat/hr-chat-agent` on Docker Hub. It installs LibreOffice (for the layout check), so it is about
1.7 GB; the build copies only `app`, `data`, the requirements and the entrypoint (never `.env`, tests or `var`).

```
docker build -t sabarinathvenkat/hr-chat-agent:8 -t sabarinathvenkat/hr-chat-agent:latest .
docker push sabarinathvenkat/hr-chat-agent:8
```

Use a new tag for each release (7 was the last one without LibreOffice, 8 is the portal release). Check that the tag exists on
Docker Hub before pointing RunPod at it. If the upload keeps failing with "broken pipe", the connection or Docker Desktop's
proxy is dropping it: retry (finished layers are kept), close memory-hungry programs, or build and push from GitHub Actions.

On RunPod the app is one CPU pod (cpu3c, 2 vCPU, 4 GB, about $0.06 an hour) with:

- image `sabarinathvenkat/hr-chat-agent:<tag>`, container port `8000/http`;
- environment `DEMO_DATA=true`, `ANTHROPIC_API_KEY={{ RUNPOD_SECRET_Anthropic }}` and `JWT_SECRET={{ RUNPOD_SECRET_rmg_JWT_secret }}`
  (the two secrets are stored in RunPod; the values are never put in the repository or in chat);
- a network volume (`rmg-resume-data`, 10 GB, US-NC-1) mounted at `/data`. It holds the database, the uploaded files and the log.
  The entrypoint makes `/data` writable for the app's user. A CPU pod cannot use a pod-local volume, so the network volume is required.

To release a new image: push the tag, then set the pod's image to it and start (or restart) the pod. After it starts, check
`/health` on the public URL (`https://<podid>-8000.proxy.runpod.net/health`), then sign in as the admin and as a normal user.

**State on 2026-11-24.** The running pod is `rmg-resume-builder-2` (`197o21n7ev6p4f`), image `:8`, at
https://197o21n7ev6p4f-8000.proxy.runpod.net. The older pod `tocruwn5tmack8` is stopped (image `:8` too). Check the live state in
the RunPod console before relying on this.

**A stopped pod may not start again.** A stopped pod stays tied to its machine; if that machine's CPUs are taken, starting it is
refused ("not enough free vcpu on the host machine"). Retrying later may work. The fix that always works is to create a new pod
with the same settings and the same network volume in the same data center. The public URL changes with the pod id. Never run
two pods on the same volume at the same time: they would share one SQLite database.

## Security notes

- The demo password (`Welcome@123`) is shown on the sign-in page and `admin123` is in the repository. A deployment with
  `DEMO_DATA=true` is an open demo. For real use: set `DEMO_DATA=false`, set `ADMIN_PASSWORD` before the first start, and
  create real accounts.
- Secrets live in `.env` locally (git-ignored) and in RunPod secrets when deployed. Do not paste them into chat, logs or commits.
- The page's security policy forbids inline scripts and style attributes; the scripts build the page with `textContent` only.
- The base image (`python:3.12-slim`) has had known vulnerabilities reported; rebuild on a patched base before a real launch.

## Open items

- Notifications are in-app only (no email). There is no data retention job yet.
- The Deep match and the briefing prompts have been checked on a few real resumes and job descriptions, not on a large set.
- The browser test files need memory; run them in groups (see `docs/RESUME_BUILDER.md`).

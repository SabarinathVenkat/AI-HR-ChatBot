"""The resume-builder workflow: who may do what, and how a request moves from "requested" to "approved".

One ResumeService is made per call, for the signed-in person (the actor). It never trusts a client: every method
checks the actor's relation to the request (the associate it is for, their Competency Lead, or RMG) and the request's
status, and raises ServiceError with an HTTP-style status and a friendly message.

Lifecycle:  requested -> in_progress -> submitted -> approved
                              ^             |
                              +-- changes_requested (the Lead sent it back with a note)
            approved -> in_progress again if the associate reopens it (a new version is made on the next save)
            any state except approved -> cancelled (RMG)
Only the associate submits. Only the mapped Lead decides. A download's file name says DRAFT or FINAL.
"""
import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta

from app import issue_log
from app.db.repositories import Employee
from app.rmg.resume.changelog import build_change_log
from app.rmg.resume.conformance import WARN, Check, Report, check_conformance
from app.rmg.resume.chat import EditCommand, explain
from app.rmg.resume.deep import MODES, skill_bullet
from app.rmg.resume.edit import (
    EditError, add_certification_as, add_dates_as, add_fact, add_skill_as, move_bullet, move_project, remove_item, set_role_line,
    set_text, stamp_reviewer,
)
from app.rmg.resume.extract import ExtractionError
from app.rmg.resume.facts import experience
from app.rmg.resume.filestore import FileStore
from app.rmg.resume.grounding import check_grounding
from app.rmg.resume.ingest import IngestError, read_document
from app.rmg.resume.jd import JobDescription, jd_to_docx
from app.rmg.resume.match import build_match_plan
from app.rmg.resume.model import Resume
from app.rmg.resume.people import lead_of, roles_of
from app.rmg.resume.pipeline import PipelineDeps, PipelineError, PipelineRequest, run_pipeline
from app.rmg.resume.render import TemplateError, check_template, render_best, template_gaps, template_warning

# A job description is short: it keeps the limits it always had, whatever a resume is allowed.
JD_LIMITS = dict(max_pages=5, max_text_chars=20_000)
PREVIEW_TEXT_CHARS = 8000  # how much of a job description's own text the preview shows
TEMPLATE_LIMITS = dict(max_bytes=40_000_000, max_uncompressed=150_000_000, max_entries=2000, max_pages=50,
                       max_text_chars=200_000)
OPEN_FOR_ASSOCIATE = ("requested", "in_progress", "changes_requested")
EDITABLE = ("in_progress", "changes_requested")
RMG = frozenset({"rmg_staff", "rmg_head"})
MAX_UNDO = 20
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MEDIA_TYPES = {".docx": DOCX_TYPE, ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8"}


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(message)


@dataclass(frozen=True)
class ResumeEngine:
    """The models and settings the workflow runs with. Injected, so tests use fakes."""

    deps: PipelineDeps
    interpreter: object | None = None  # reads a chat instruction into an edit command (see chat.py)
    polisher: object | None = None  # checks and fixes a finished file's layout: (docx, template) -> Polish (see layout_fix.py)
    weaver: object | None = None  # words the bullet for skills the associate confirms (see deep.py); None uses a plain sentence


def _day(stamp: str | None) -> date | None:
    try:
        return datetime.fromisoformat(stamp).date() if stamp else None
    except ValueError:
        return None


def _safe_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "resume"


class ResumeService:
    def __init__(self, conn: sqlite3.Connection, files: FileStore, engine: ResumeEngine, now: Callable[[], datetime],
                 actor: Employee):
        self.conn, self.files, self.engine, self._now, self.actor = conn, files, engine, now, actor
        self.roles = roles_of(conn, actor.id)

    # ------------------------------------------------------------------------------------ small helpers
    def _iso(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _need(self, *roles: str) -> None:
        if not self.roles & set(roles):
            raise ServiceError("forbidden", "You do not have access to that.", 403)

    def _log(self, what: str, level: str = "info", **fields) -> None:
        """One line in the issue log, always with who did it."""
        issue_log.event(what, level=level, user=self.actor.name, user_id=self.actor.id, **fields)

    def _log_render(self, request_id: int, rendered, where: str) -> None:
        if rendered.used_standard_layout:
            self._log("render_fallback", "warning", request_id=request_id, where=where, message=rendered.problems[0])
        notes = [p for p in rendered.problems if not p.startswith("The company template")]
        if notes:
            self._log("render_notes", "warning", request_id=request_id, where=where, notes="; ".join(notes))

    def _audit(self, action: str, detail: dict) -> None:
        self.conn.execute(
            "INSERT INTO audit_log (ts, actor_id, action, tool, inputs_json, outputs_json, trace_id)"
            " VALUES (?, ?, ?, 'resume', ?, NULL, NULL)",
            (self._iso(), self.actor.id, action, json.dumps(detail, default=str, sort_keys=True)))

    def _notify(self, employee_id: int, message: str, request_id: int | None = None) -> None:
        self.conn.execute("INSERT INTO notifications (employee_id, message, request_id, created_at) VALUES (?,?,?,?)",
                          (employee_id, message, request_id, self._iso()))

    def _name(self, employee_id: int | None) -> str:
        row = self.conn.execute("SELECT name FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return row["name"] if row else "Unknown"

    # ------------------------------------------------------------------------------------ requests and access
    def _row(self, request_id: int):
        return self.conn.execute("SELECT * FROM resume_requests WHERE id = ?", (request_id,)).fetchone()

    def _relations(self, row) -> set[str]:
        relations = set()
        if row["associate_id"] == self.actor.id:
            relations.add("associate")
        if row["lead_id"] == self.actor.id and "competency_lead" in self.roles:
            relations.add("lead")
        if self.roles & RMG:
            relations.add("rmg")
        return relations

    def _rmg_members(self) -> list[int]:
        return [r["employee_id"] for r in self.conn.execute("SELECT DISTINCT employee_id FROM rmg_roles").fetchall()]

    def _lead_name(self, row) -> str:
        return self._name(row["lead_id"]) if row["lead_id"] else "RMG team"  # no Competency Lead: RMG reviews

    def _can_review(self, row) -> bool:
        """The Competency Lead mapped to the associate, and anyone in RMG, may review a submitted resume."""
        relations = self._relations(row)
        return "lead" in relations or "rmg" in relations

    def _visible(self, request_id: int):
        """The request, or a 404 for anyone with no relation to it, so its existence is not revealed."""
        row = self._row(request_id)
        if row is None or not self._relations(row):
            raise ServiceError("not_found", "That request was not found.", 404)
        return row

    def _as_associate(self, request_id: int, statuses: tuple[str, ...]):
        row = self._visible(request_id)
        if "associate" not in self._relations(row):
            raise ServiceError("forbidden", "Only the associate this request is for can do that.", 403)
        if row["status"] not in statuses:
            raise ServiceError("wrong_status", f"That cannot be done while the request is {row['status'].replace('_', ' ')}.", 409)
        return row

    def _set_status(self, request_id: int, status: str, **extra) -> None:
        columns = {"status": status, "updated_at": self._iso(), **extra}
        self.conn.execute(f"UPDATE resume_requests SET {', '.join(f'{c} = ?' for c in columns)} WHERE id = ?",
                          (*columns.values(), request_id))

    def _jd(self, jd_id: int) -> JobDescription:
        row = self.conn.execute("SELECT jd_json FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()
        return JobDescription.model_validate_json(row["jd_json"])

    def _draft(self, request_id: int):
        return self.conn.execute("SELECT * FROM resume_drafts WHERE request_id = ?", (request_id,)).fetchone()

    # ------------------------------------------------------------------------------------ templates (RMG head)
    def upload_template(self, filename: str, data: bytes, name: str | None = None) -> dict:
        self._need("rmg_head")
        try:
            document = read_document(filename, data, **TEMPLATE_LIMITS)
            if document.kind != "docx":
                raise ServiceError("unsupported_type", "A template must be a Word (.docx) file.", 422)
            check_template(data)
        except IngestError as e:
            self._log("template_rejected", "warning", filename=filename, size=len(data), code=e.code, message=str(e))
            raise ServiceError(e.code, str(e), 422) from None
        except TemplateError as e:
            if e.code == "unreadable":
                self._log("template_rejected", "warning", filename=filename, size=len(data), code=e.code, message=str(e))  # missing sections are allowed: the standard layout is used and the uploader is told
                raise ServiceError("template_" + e.code, str(e), 422) from None
        key = self.files.put(data, ".docx")
        self.conn.execute("UPDATE resume_templates SET status = 'archived' WHERE status = 'active'")
        cursor = self.conn.execute(
            "INSERT INTO resume_templates (name, filename, file_key, status, uploaded_by, created_at)"
            " VALUES (?, ?, ?, 'active', ?, ?)", ((name or document.filename)[:100], document.filename, key,
                                                  self.actor.id, self._iso()))
        self._audit("template_uploaded", {"template_id": cursor.lastrowid, "filename": document.filename})
        self.conn.commit()
        result = {"id": cursor.lastrowid, "name": (name or document.filename)[:100], "status": "active"}
        self._log("template_uploaded", template_id=cursor.lastrowid, filename=document.filename, size=len(data))
        if warning := template_warning(data):
            result["warning"] = warning
            self._log("template_unusable", "warning", template_id=cursor.lastrowid, filename=document.filename, message=warning)
        return result

    def active_template(self):
        return self.conn.execute("SELECT * FROM resume_templates WHERE status = 'active' ORDER BY id DESC").fetchone()

    def template_info(self) -> dict | None:
        self._need("rmg_head", "rmg_staff")
        row = self.active_template()
        return {"id": row["id"], "name": row["name"], "filename": row["filename"], "created_at": row["created_at"]} if row else None

    # ------------------------------------------------------------------------------------ lead mapping (RMG head)
    def list_leads(self) -> dict:
        self._need("rmg_head")
        leads = self.conn.execute(
            "SELECT e.id, e.name FROM employees e JOIN rmg_roles r ON r.employee_id = e.id"
            " WHERE r.role = 'competency_lead' ORDER BY e.name").fetchall()
        mapping = self.conn.execute(
            "SELECT a.associate_id, ea.name AS associate, a.lead_id, el.name AS lead FROM lead_assignments a"
            " JOIN employees ea ON ea.id = a.associate_id JOIN employees el ON el.id = a.lead_id ORDER BY ea.name").fetchall()
        people = self.conn.execute("SELECT id, name FROM employees WHERE id NOT IN (SELECT employee_id FROM platform_admins) ORDER BY name").fetchall()
        return {"leads": [dict(r) for r in leads], "assignments": [dict(r) for r in mapping],
                "employees": [dict(r) for r in people]}

    def set_lead(self, associate_id: int, lead_id: int) -> None:
        from app.rmg.resume.people import PeopleError, set_lead

        self._need("rmg_head")
        try:
            set_lead(self.conn, associate_id, lead_id)
        except PeopleError as e:
            raise ServiceError(e.code, str(e), 422) from None
        self._audit("lead_assigned", {"associate_id": associate_id, "lead_id": lead_id})
        self.conn.commit()

    # ------------------------------------------------------------------------------------ job descriptions (RMG)
    def create_jd(self, filename: str, data: bytes, title: str | None = None) -> dict:
        self._need(*RMG)
        try:
            document = read_document(filename, data, **JD_LIMITS)
            jd = self.engine.deps.jd_extractor.extract(document)
        except (IngestError, ExtractionError) as e:
            raise ServiceError(e.code, str(e), 422) from None
        name = (title or jd.roles[0].title)[:150]
        key = self.files.put(data, {"docx": ".docx", "pdf": ".pdf", "txt": ".txt"}[document.kind])  # keep the original file
        cursor = self.conn.execute(
            "INSERT INTO job_descriptions (title, filename, jd_json, file_key, created_by, created_at) VALUES (?,?,?,?,?,?)",
            (name, document.filename, jd.model_dump_json(), key, self.actor.id, self._iso()))
        self._audit("jd_created", {"jd_id": cursor.lastrowid})
        self.conn.commit()
        return self._jd_view(cursor.lastrowid)

    def create_jd_from_text(self, text: str, title: str | None = None) -> dict:
        """A job description pasted as text. It can be sentences, or just a list of skills. It is stored as a text file,
        so it is read, kept and downloaded exactly like an uploaded one."""
        self._need(*RMG)
        cleaned = (text or "").strip()
        if not cleaned:
            raise ServiceError("empty", "Paste the job description, or a list of skills, first.", 422)
        return self.create_jd("pasted-job-description.txt", cleaned.encode("utf-8"), title)

    def _jd_view(self, jd_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()
        jd = JobDescription.model_validate_json(row["jd_json"])
        return {"id": row["id"], "title": row["title"], "filename": row["filename"], "created_at": row["created_at"],
                "roles": [r.model_dump() for r in jd.roles], "flagged": jd.flagged}

    def _jd_preview(self, jd_id: int) -> dict:
        """What was understood from a job description (roles, years, skills, flagged text) and the start of its own text."""
        row = self.conn.execute("SELECT * FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()
        if row is None:
            raise ServiceError("not_found", "That job description was not found.", 404)
        text = ""
        if row["file_key"]:
            try:
                suffix = "." + row["file_key"].rsplit(".", 1)[1]
                text = read_document("job-description" + suffix, self.files.get(row["file_key"]), **JD_LIMITS).text.strip()
            except (FileNotFoundError, IngestError, IndexError):
                text = ""  # no original to show: the preview still has the requirements
        shown = text[:PREVIEW_TEXT_CHARS]
        return {**self._jd_view(jd_id), "text": shown, "truncated": len(text) > len(shown)}

    def jd_preview(self, jd_id: int) -> dict:
        """A job description from RMG's list."""
        self._need(*RMG)
        preview = self._jd_preview(jd_id)
        self._audit("jd_previewed", {"jd_id": jd_id})
        self.conn.commit()
        return preview

    def request_jd_preview(self, request_id: int) -> dict:
        """The job description of a request, for the associate, their Lead and RMG."""
        row = self._visible(request_id)
        preview = self._jd_preview(row["jd_id"])
        self._audit("jd_previewed", {"request_id": request_id, "jd_id": row["jd_id"]})
        self.conn.commit()
        return preview

    def _jd_file(self, jd_id: int) -> tuple[str, bytes, str]:
        """The original file if it was kept, otherwise a Word file made from the stored requirements."""
        row = self.conn.execute("SELECT * FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()
        if row is None:
            raise ServiceError("not_found", "That job description was not found.", 404)
        base = _safe_filename(row["title"])
        if row["file_key"]:
            try:
                data = self.files.get(row["file_key"])
                suffix = "." + row["file_key"].rsplit(".", 1)[1]
                return base + suffix, data, MEDIA_TYPES[suffix]
            except FileNotFoundError:
                pass  # the file has gone: fall back to the stored requirements
        data = jd_to_docx(row["title"], JobDescription.model_validate_json(row["jd_json"]))
        return base + ".docx", data, DOCX_TYPE

    def download_jd(self, request_id: int) -> tuple[str, bytes, str]:
        """The job description of a request, for the associate, their Lead and RMG."""
        row = self._visible(request_id)
        result = self._jd_file(row["jd_id"])
        self._audit("jd_downloaded", {"request_id": request_id, "jd_id": row["jd_id"]})
        self.conn.commit()
        return result

    def jd_file(self, jd_id: int) -> tuple[str, bytes, str]:
        """A job description from RMG's list."""
        self._need(*RMG)
        result = self._jd_file(jd_id)
        self._audit("jd_downloaded", {"jd_id": jd_id})
        self.conn.commit()
        return result

    def list_jds(self) -> list[dict]:
        self._need(*RMG)
        rows = self.conn.execute("SELECT id FROM job_descriptions ORDER BY id DESC").fetchall()
        return [self._jd_view(r["id"]) for r in rows]

    def associates(self) -> list[dict]:
        """People RMG can tag, with their Competency Lead (None means they cannot be tagged yet)."""
        self._need(*RMG)
        rows = self.conn.execute(
            "SELECT e.id, e.name, e.department, a.lead_id FROM employees e LEFT JOIN lead_assignments a"
            " ON a.associate_id = e.id WHERE e.id NOT IN (SELECT employee_id FROM rmg_roles)"
            " AND e.id NOT IN (SELECT employee_id FROM platform_admins) ORDER BY e.name").fetchall()
        return [{"id": r["id"], "name": r["name"], "department": r["department"],
                 "lead": self._name(r["lead_id"]) if r["lead_id"] else None,
                 "review_by": "Competency Lead" if r["lead_id"] else "RMG"} for r in rows]

    # ------------------------------------------------------------------------------------ tagging (RMG)
    def tag(self, jd_id: int, associate_ids: list[int], role_index: int = 0) -> dict:
        self._need(*RMG)
        if self.conn.execute("SELECT 1 FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone() is None:
            raise ServiceError("not_found", "That job description was not found.", 404)
        jd = self._jd(jd_id)
        if not 0 <= role_index < len(jd.roles):
            raise ServiceError("no_such_role", "That role is not in the job description.", 422)
        created, skipped = [], []
        for associate_id in dict.fromkeys(associate_ids):
            person = self.conn.execute("SELECT name FROM employees WHERE id = ?", (associate_id,)).fetchone()
            if person is None:
                skipped.append({"associate_id": associate_id, "reason": "not_found", "message": "That person was not found."})
            elif self.conn.execute("SELECT 1 FROM resume_requests WHERE jd_id = ? AND associate_id = ?",
                                   (jd_id, associate_id)).fetchone():
                skipped.append({"associate_id": associate_id, "reason": "already_tagged",
                                "message": f"{person['name']} is already tagged for this job description."})
            else:
                now = self._iso()
                cursor = self.conn.execute(
                    "INSERT INTO resume_requests (jd_id, associate_id, lead_id, role_index, status, created_by, created_at,"
                    " updated_at) VALUES (?, ?, ?, ?, 'requested', ?, ?, ?)",
                    (jd_id, associate_id, lead_of(self.conn, associate_id), role_index, self.actor.id, now, now))  # no lead: RMG reviews
                self._notify(associate_id, f"You were asked to prepare a resume for: {self._jd_title(jd_id)}.", cursor.lastrowid)
                created.append({"request_id": cursor.lastrowid, "associate_id": associate_id})
        self._audit("tagged", {"jd_id": jd_id, "created": [c["request_id"] for c in created], "skipped": len(skipped)})
        self.conn.commit()
        return {"created": created, "skipped": skipped}

    def _jd_title(self, jd_id: int) -> str:
        return self.conn.execute("SELECT title FROM job_descriptions WHERE id = ?", (jd_id,)).fetchone()["title"]

    def cancel(self, request_id: int) -> None:
        row = self._visible(request_id)
        self._need(*RMG)
        if row["status"] in ("approved", "cancelled"):
            raise ServiceError("wrong_status", "That request can no longer be cancelled.", 409)
        self._set_status(request_id, "cancelled")
        self._notify(row["associate_id"], f"The request for {self._jd_title(row['jd_id'])} was cancelled.", request_id)
        self._audit("request_cancelled", {"request_id": request_id})
        self.conn.commit()

    # ------------------------------------------------------------------------------------ the associate builds
    def upload_resume(self, request_id: int, filename: str, data: bytes) -> dict:
        row = self._as_associate(request_id, OPEN_FOR_ASSOCIATE)
        try:
            document = read_document(filename, data)  # reject a bad file now, with a friendly reason
        except IngestError as e:
            self._log("upload_failed", "warning", request_id=request_id, filename=filename, size=len(data), code=e.code, message=str(e))
            raise ServiceError(e.code, str(e), 422) from None
        suffix = {"docx": ".docx", "pdf": ".pdf", "txt": ".txt"}[document.kind]
        if row["base_file_key"]:
            self.files.delete(row["base_file_key"])
        key = self.files.put(data, suffix)
        self.conn.execute("UPDATE resume_requests SET base_filename = ?, base_file_key = ?, updated_at = ? WHERE id = ?",
                          (document.filename, key, self._iso(), request_id))
        self._audit("resume_uploaded", {"request_id": request_id, "filename": document.filename})
        self.conn.commit()
        self._log("resume_uploaded", request_id=request_id, filename=document.filename, size=len(data), kind=document.kind, pages=document.pages)
        return {"filename": document.filename}

    def build(self, request_id: int, force: bool = False, mode: str = "polish") -> dict:
        if mode not in MODES:
            raise ServiceError("bad_mode", "Choose polish or deep match.", 422)
        row = self._as_associate(request_id, OPEN_FOR_ASSOCIATE)
        if not row["base_file_key"]:
            raise ServiceError("no_resume", "Upload your resume first.", 409)
        if self._draft(request_id) is not None and not force:
            raise ServiceError("already_built", "A draft already exists. Rebuilding replaces your edits.", 409)
        template = self.active_template()
        if template is None:
            raise ServiceError("no_template", "RMG has not set up a resume template yet.", 409)
        request = PipelineRequest(
            resume_file=(row["base_filename"], self.files.get(row["base_file_key"])), jd=self._jd(row["jd_id"]),
            template=self.files.get(template["file_key"]), role_index=row["role_index"], today=self._now().date(), mode=mode)
        started = time.perf_counter()
        context = {"request_id": request_id, "filename": row["base_filename"], "size": len(request.resume_file[1]),
                   "template": template["filename"], "jd_id": row["jd_id"], "role_index": row["role_index"]}
        self._log("build_started", forced=force, mode=mode, **context)
        try:
            result = run_pipeline(self.engine.deps, request)
        except PipelineError as e:
            self._log("build_failed", "error", stage=e.stage, code=e.code, message=str(e),
                      duration_ms=round((time.perf_counter() - started) * 1000), **context)
            raise ServiceError(f"{e.stage}_{e.code}", str(e), 422) from None
        except Exception as e:  # noqa: BLE001 - recorded with its traceback, then handled as an unexpected error
            self._log("build_crashed", "error", error=e, duration_ms=round((time.perf_counter() - started) * 1000), **context)
            raise
        years = result.experience.describe() if result.experience.months else ""
        self.conn.execute(
            "INSERT INTO resume_drafts (request_id, base_json, working_json, undo_json, warnings_json, years_text,"
            " read_coverage, template_id, mode, updated_at) VALUES (?,?,?,'[]',?,?,?,?,?,?)"
            " ON CONFLICT(request_id) DO UPDATE SET base_json = excluded.base_json, working_json = excluded.working_json,"
            " undo_json = '[]', warnings_json = excluded.warnings_json, years_text = excluded.years_text,"
            " read_coverage = excluded.read_coverage, template_id = excluded.template_id, mode = excluded.mode,"
            " updated_at = excluded.updated_at",
            (request_id, result.original.model_dump_json(), result.tailored.model_dump_json(), json.dumps(result.warnings),
             years, result.read_coverage, template["id"], result.mode, self._iso()))
        self._set_status(request_id, "in_progress")
        self._audit("resume_built", {"request_id": request_id, "forced": force, "mode": result.mode})
        self.conn.commit()
        self._log("build_succeeded", request_id=request_id, mode=result.mode, duration_ms=round((time.perf_counter() - started) * 1000),
                  read_coverage=result.read_coverage, warnings=len(result.warnings), projects=len(result.tailored.projects),
                  highlights=len(result.tailored.highlights), missing_required=len(result.plan.missing_required))
        for warning in result.warnings:
            self._log("build_warning", "warning", request_id=request_id, message=warning)
        self._log_render(request_id, result.rendered, "build")
        return self.detail(request_id)

    # ------------------------------------------------------------------------------------ viewing
    def _changelog(self, row, draft):
        base, working = Resume.model_validate_json(draft["base_json"]), Resume.model_validate_json(draft["working_json"])
        jd = self._jd(row["jd_id"])
        role = jd.roles[row["role_index"]]
        worked = experience(base.jobs, self._now().date())
        report = check_grounding(base, working, build_match_plan(base, role, worked))
        return build_change_log(base, working, role, report, worked), report

    def _can(self, row, relations: set[str], has_draft: bool) -> dict:
        status, associate = row["status"], "associate" in relations
        reviewer = ("lead" in relations or "rmg" in relations) and not associate
        return {
            "upload": associate and status in OPEN_FOR_ASSOCIATE,
            "build": associate and status in OPEN_FOR_ASSOCIATE and bool(row["base_file_key"]),
            "edit": has_draft and ((associate and status in EDITABLE) or (reviewer and status == "submitted")),
            "chat": associate and has_draft and status in EDITABLE,  # the assistant is the associate's: it cannot make claims for anyone else
            "save": associate and has_draft and status in EDITABLE,
            "submit": associate and has_draft and status in EDITABLE,
            "decide": ("lead" in relations or "rmg" in relations) and status == "submitted",
            "reopen": associate and status == "approved",
            "cancel": "rmg" in relations and status not in ("approved", "cancelled"),
            "download": has_draft,
        }

    def detail(self, request_id: int) -> dict:
        row = self._visible(request_id)
        relations = self._relations(row)
        draft = self._draft(request_id)
        jd = self._jd(row["jd_id"])
        role = jd.roles[row["role_index"]]
        view = {
            "id": row["id"], "status": row["status"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "decision_note": row["decision_note"], "base_filename": row["base_filename"],
            "relations": sorted(relations),
            "jd": {"id": row["jd_id"], "title": self._jd_title(row["jd_id"]), "role": role.model_dump(), "flagged": jd.flagged},
            "associate": {"id": row["associate_id"], "name": self._name(row["associate_id"])},
            "lead": {"id": row["lead_id"], "name": self._lead_name(row)},
            "review_by": "Competency Lead" if row["lead_id"] else "RMG",
            "resume": None, "changelog": None, "warnings": [], "years_text": "", "read_coverage": None, "render_notes": [], "mode": None,
            "versions": [dict(v) for v in self.conn.execute(
                "SELECT version, kind, created_at FROM resume_versions WHERE request_id = ? ORDER BY version", (request_id,))],
            "can": self._can(row, relations, draft is not None),
        }
        if draft is not None:
            log, _ = self._changelog(row, draft)
            view.update(resume=json.loads(draft["working_json"]), changelog=asdict(log), warnings=json.loads(draft["warnings_json"]),
                        years_text=draft["years_text"], read_coverage=draft["read_coverage"], render_notes=self._render_notes(draft),
                        mode=draft["mode"])
        return view

    def _render_notes(self, draft) -> list[str]:
        """What this resume has that the template has no place for, so the associate is told instead of finding it missing."""
        try:
            template = self.conn.execute("SELECT * FROM resume_templates WHERE id = ?", (draft["template_id"],)).fetchone() or self.active_template()
            if template is None:
                return []
            data = self.files.get(template["file_key"])
            return [w for w in [template_warning(data)] if w] or template_gaps(data, Resume.model_validate_json(draft["working_json"]))
        except (TemplateError, FileNotFoundError, ValueError):
            return []  # a notice must never stop the page from opening

    STATUSES = ("requested", "in_progress", "submitted", "changes_requested", "approved", "cancelled")

    def stats(self) -> dict:
        """The landing page's numbers. RMG sees every request, a Competency Lead the requests of their associates, and
        anyone else their own."""
        if self.roles & RMG:
            scope, where, args = "all", "1 = 1", ()
        elif "competency_lead" in self.roles:
            scope, where, args = "lead", "r.lead_id = ?", (self.actor.id,)
        else:
            scope, where, args = "mine", "r.associate_id = ?", (self.actor.id,)
        by_status = dict.fromkeys(self.STATUSES, 0)
        for row in self.conn.execute(f"SELECT r.status, count(*) AS n FROM resume_requests r WHERE {where} GROUP BY r.status", args):
            by_status[row["status"]] = row["n"]
        recent = self.conn.execute(
            f"SELECT r.* FROM resume_requests r WHERE {where} ORDER BY r.updated_at DESC, r.id DESC LIMIT 5", args).fetchall()
        out = {"scope": scope, "total": sum(by_status.values()), "by_status": by_status,
               "recent": [{"id": r["id"], "status": r["status"], "jd_title": self._jd_title(r["jd_id"]),
                           "associate": self._name(r["associate_id"]), "lead": self._lead_name(r), "updated_at": r["updated_at"],
                           "coverage": None} for r in recent]}
        out.update(self._insights(where, args, by_status))
        if scope == "all":
            out["job_descriptions"] = self.conn.execute("SELECT count(*) FROM job_descriptions").fetchone()[0]
            out["without_lead"] = self.conn.execute(
                "SELECT count(*) FROM employees e WHERE e.id NOT IN (SELECT employee_id FROM rmg_roles)"
                " AND e.id NOT IN (SELECT employee_id FROM platform_admins)"
                " AND e.id NOT IN (SELECT associate_id FROM lead_assignments)").fetchone()[0]
        return out

    TREND_DAYS = 14

    def _insights(self, where: str, args: tuple, by_status: dict) -> dict:
        """What the dashboard's charts draw: requests per day, how long approval takes, the busiest job descriptions and
        what has been waiting longest."""
        today = self._now().date()
        days = [today - timedelta(days=n) for n in range(self.TREND_DAYS - 1, -1, -1)]
        per_day = dict.fromkeys(days, 0)
        waiting, took = [], []
        for r in self.conn.execute(f"SELECT r.* FROM resume_requests r WHERE {where}", args):
            made = _day(r["created_at"])
            if made in per_day:
                per_day[made] += 1
            if r["status"] == "approved" and r["decided_at"] and made:
                took.append(max(0.0, (datetime.fromisoformat(r["decided_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 86400))
            if r["status"] == "submitted":
                waiting.append(r)
        waiting.sort(key=lambda r: r["updated_at"])
        jds = self.conn.execute(
            f"SELECT r.jd_id, count(*) AS n, sum(r.status = 'approved') AS done FROM resume_requests r WHERE {where}"
            " GROUP BY r.jd_id ORDER BY n DESC, r.jd_id LIMIT 5", args).fetchall()
        counted = sum(by_status.values()) - by_status["cancelled"]
        return {
            "trend": [{"date": d.isoformat(), "count": per_day[d]} for d in days],
            "avg_days_to_approve": round(sum(took) / len(took), 1) if took else None,
            "completion_rate": round(by_status["approved"] / counted, 2) if counted else None,
            "top_jds": [{"title": self._jd_title(j["jd_id"]), "total": j["n"], "approved": j["done"] or 0} for j in jds],
            "attention": [{"id": r["id"], "jd_title": self._jd_title(r["jd_id"]), "associate": self._name(r["associate_id"]),
                           "days_waiting": max(0, (today - (_day(r["updated_at"]) or today)).days)} for r in waiting[:5]],
        }

    def summaries(self, scope: str) -> list[dict]:
        if scope == "mine":
            where, args = "r.associate_id = ?", (self.actor.id,)
        elif scope == "lead":
            self._need("competency_lead")
            where, args = "r.lead_id = ?", (self.actor.id,)
        elif scope == "review":
            # what is waiting for this person: their own associates (as a Competency Lead), and for RMG every submitted resume
            self._need("competency_lead", *RMG)
            clauses, args = [], ()
            if "competency_lead" in self.roles:
                clauses.append("r.lead_id = ?")
                args += (self.actor.id,)
            if self.roles & RMG:
                clauses.append("r.status = 'submitted'")
            where = "(" + " OR ".join(clauses) + ")"
        else:
            self._need(*RMG)
            where, args = "1 = 1", ()
        rows = self.conn.execute(
            f"SELECT r.* FROM resume_requests r WHERE {where} ORDER BY r.updated_at DESC, r.id DESC", args).fetchall()
        out = []
        for r in rows:
            draft = self._draft(r["id"])
            coverage = None
            if draft is not None:
                log, _ = self._changelog(r, draft)
                coverage = {"required_after": log.coverage.required_after, "missing_required": list(log.coverage.missing_required)}
            out.append({"id": r["id"], "status": r["status"], "jd_id": r["jd_id"], "jd_title": self._jd_title(r["jd_id"]),
                        "associate": self._name(r["associate_id"]), "associate_id": r["associate_id"],
                        "lead": self._lead_name(r), "updated_at": r["updated_at"], "coverage": coverage,
                        "has_draft": draft is not None})
        return out

    # ------------------------------------------------------------------------------------ save, submit, decide
    def _add_version(self, request_id: int, kind: str, draft_json: str, years: str, template_id: int | None) -> int:
        version = self.conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS v FROM resume_versions WHERE request_id = ?",
                                    (request_id,)).fetchone()["v"]
        self.conn.execute(
            "INSERT INTO resume_versions (request_id, version, kind, resume_json, years_text, template_id, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)", (request_id, version, kind, draft_json, years, template_id, self.actor.id, self._iso()))
        return version

    def save(self, request_id: int) -> dict:
        row = self._as_associate(request_id, EDITABLE)
        draft = self._need_draft(request_id)
        version = self._add_version(request_id, "saved", draft["working_json"], draft["years_text"], draft["template_id"])
        if row["status"] == "changes_requested":
            self._set_status(request_id, "in_progress")
        self._audit("resume_saved", {"request_id": request_id, "version": version})
        self.conn.commit()
        return {"version": version}

    def _need_draft(self, request_id: int):
        draft = self._draft(request_id)
        if draft is None:
            raise ServiceError("no_draft", "Build the resume first.", 409)
        return draft

    def submit(self, request_id: int) -> dict:
        row = self._as_associate(request_id, EDITABLE)
        draft = self._need_draft(request_id)
        _, report = self._changelog(row, draft)
        if report.violations:
            raise ServiceError("ungrounded", "The resume contains claims that are not in your original resume. Remove them first.", 409)
        version = self._add_version(request_id, "submitted", draft["working_json"], draft["years_text"], draft["template_id"])
        self._set_status(request_id, "submitted", decision_note=None)
        title, who = self._jd_title(row["jd_id"]), self.actor.name
        if row["lead_id"]:
            self._notify(row["lead_id"], f"{who} submitted a resume for {title}. It is waiting for your review.", request_id)
        reviewers = "RMG reviews it" if not row["lead_id"] else f"the Competency Lead, {self._name(row['lead_id'])}, or RMG can review it"
        for person in dict.fromkeys([*self._rmg_members(), row["created_by"]]):
            if person != row["lead_id"]:
                self._notify(person, f"{who} submitted a resume for {title}. It is waiting for review: {reviewers}.", request_id)
        self._audit("resume_submitted", {"request_id": request_id, "version": version})
        self.conn.commit()
        return {"version": version, "status": "submitted"}

    def decide(self, request_id: int, decision: str, note: str | None = None) -> dict:
        row = self._visible(request_id)
        if not self._can_review(row):
            raise ServiceError("forbidden", "Only the Competency Lead mapped to this associate, or RMG, can decide.", 403)
        if row["status"] != "submitted":
            raise ServiceError("wrong_status", "There is nothing waiting for your decision.", 409)
        note = (note or "").strip()[:1000]
        title = self._jd_title(row["jd_id"])
        if decision == "approve":
            draft = self._need_draft(request_id)  # as it is now: it includes anything the reviewer changed
            self._add_version(request_id, "approved", draft["working_json"], draft["years_text"], draft["template_id"])
            self._set_status(request_id, "approved", decided_by=self.actor.id, decided_at=self._iso(), decision_note=note or None)
            for person in {row["associate_id"], row["created_by"], row["lead_id"]} - {None, self.actor.id}:
                self._notify(person, f"The resume for {title} ({self._name(row['associate_id'])}) was approved by {self.actor.name}.", request_id)
        elif decision == "send_back":
            if not note:
                raise ServiceError("note_required", "Please say what needs to change.", 422)
            self._set_status(request_id, "changes_requested", decided_by=self.actor.id, decided_at=self._iso(), decision_note=note)
            self._notify(row["associate_id"], f"Your resume for {title} was sent back by {self.actor.name}: {note}", request_id)
            if row["lead_id"] and row["lead_id"] != self.actor.id:  # RMG sent it back: the lead should know
                self._notify(row["lead_id"], f"{self.actor.name} sent back {self._name(row['associate_id'])}'s resume for {title}: {note}", request_id)
        else:
            raise ServiceError("bad_decision", "The decision must be approve or send_back.", 422)
        self._audit("resume_decided", {"request_id": request_id, "decision": decision})
        self.conn.commit()
        return {"status": "approved" if decision == "approve" else "changes_requested"}

    def reopen(self, request_id: int) -> dict:
        self._as_associate(request_id, ("approved",))
        self._set_status(request_id, "in_progress", decided_by=None, decided_at=None, decision_note=None)
        self._audit("resume_reopened", {"request_id": request_id})
        self.conn.commit()
        return {"status": "in_progress"}

    # ------------------------------------------------------------------------------------ edits (the draft only)
    def _editing(self, request_id: int, *, reviewer_ok: bool = False):
        """The draft to change. The associate may while it is theirs to write; a reviewer (the Competency Lead or RMG) may
        while it is waiting for review."""
        row = self._visible(request_id)
        as_reviewer = (reviewer_ok and "associate" not in self._relations(row) and self._can_review(row)
                       and row["status"] == "submitted")
        if not as_reviewer:
            row = self._as_associate(request_id, EDITABLE)
        draft = self._need_draft(request_id)
        base, working = Resume.model_validate_json(draft["base_json"]), Resume.model_validate_json(draft["working_json"])
        role = self._jd(row["jd_id"]).roles[row["role_index"]]
        plan = build_match_plan(base, role, experience(base.jobs, self._now().date()))
        return draft, base, working, plan

    def _store(self, request_id: int, draft, working: Resume) -> None:
        undo = [*json.loads(draft["undo_json"]), draft["working_json"]][-MAX_UNDO:]
        self.conn.execute("UPDATE resume_drafts SET working_json = ?, undo_json = ?, updated_at = ? WHERE request_id = ?",
                          (working.model_dump_json(), json.dumps(undo), self._iso(), request_id))

    @staticmethod
    def _present(value, code: str = "no_such_item"):
        if value is None:
            raise EditError(code)
        return value

    def _execute(self, cmd: EditCommand, base: Resume, working: Resume, plan, by: str) -> Resume:
        need = self._present
        match cmd.action:
            case "set_text":
                return set_text(working, base, plan, need(cmd.path), need(cmd.text, "empty_text"), by=by)
            case "remove":
                return remove_item(working, need(cmd.path))
            case "move_project":
                return move_project(working, need(cmd.index, "bad_position"), need(cmd.to, "bad_position"))
            case "move_bullet":
                return move_bullet(working, need(cmd.project), need(cmd.index, "bad_position"), need(cmd.to, "bad_position"))
            case "add_fact":
                return add_fact(working, cmd.project, need(cmd.text, "empty_text"))
            case "add_skill":
                return add_skill_as(working, need(cmd.text, "empty_text"), group=cmd.group, category=cmd.category, by=by)
            case "add_certification":
                return add_certification_as(working, need(cmd.text, "empty_text"), by=by)
            case "add_dates":
                return add_dates_as(working, need(cmd.project, "no_such_item"), need(cmd.text, "empty_text"), by=by)
            case "set_role":
                return set_role_line(working, base, plan, need(cmd.text, "empty_text"), by=by)
        raise EditError("no_such_item")

    def _apply(self, request_id: int, cmd: EditCommand, by: str, *, reviewer_ok: bool = False) -> tuple[bool, str]:
        """Run one command on the draft. Returns (changed, message). Raises EditError when it is refused."""
        draft, base, working, plan = self._editing(request_id, reviewer_ok=reviewer_ok)
        reviewing = "associate" not in self._relations(self._row(request_id))
        if cmd.action == "none":
            return False, cmd.reply or "I am not sure what you would like to change."
        if cmd.action == "explain":
            row = self._row(request_id)
            return False, explain(self._changelog(row, draft)[0])
        if cmd.action == "undo":
            undo = json.loads(draft["undo_json"])
            if not undo:
                return False, "There is nothing to undo."
            self.conn.execute("UPDATE resume_drafts SET working_json = ?, undo_json = ?, updated_at = ? WHERE request_id = ?",
                              (undo.pop(), json.dumps(undo), self._iso(), request_id))
            message = "Undone."
        else:
            changed_resume = self._execute(cmd, base, working, plan, by)
            if reviewing:
                changed_resume = stamp_reviewer(working, changed_resume, self.actor.name)
            self._store(request_id, draft, changed_resume)
            message = cmd.reply or "Done."
        self._audit("resume_edited", {"request_id": request_id, "action": cmd.action, "path": cmd.path, "by": by, "reviewer": reviewing})
        self.conn.commit()
        return True, message

    def confirm_skills(self, request_id: int, entries: list[dict]) -> dict:
        """The associate says which skills they really have and where they used them. Each skill is added to their skills, and every
        project they name gets one bullet that states the skills used there. All of it is their own statement (user_added): the
        reviewers see it marked as added by the associate. Only the associate can do this, never an assistant or a reviewer."""
        draft, _, working, _ = self._editing(request_id)  # the associate only, and only while the draft is theirs to write
        per_project: dict[int, list[str]] = {}
        added = []
        try:
            for entry in entries:
                skill = " ".join(str(entry.get("skill", "")).split())
                try:
                    working = add_skill_as(working, skill, category="Other relevant skills", by="user")
                    added.append(skill)
                except EditError as e:
                    if e.code != "duplicate":  # a skill that is already there still gets written into the projects
                        raise
                for index in dict.fromkeys(entry.get("projects", [])):
                    if not 0 <= index < len(working.projects):
                        raise EditError("no_such_item")
                    per_project.setdefault(index, []).append(skill)
            for index, skills in sorted(per_project.items()):
                text = skill_bullet(working.projects[index], list(dict.fromkeys(skills)), self.engine.weaver)
                working = add_fact(working, index, text)
        except EditError as e:
            raise ServiceError(f"edit_{e.code}", str(e), 422) from None
        self._store(request_id, draft, working)
        self._audit("skills_confirmed", {"request_id": request_id, "skills": added, "projects": sorted(per_project)})
        self.conn.commit()
        self._log("skills_confirmed", request_id=request_id, skills=len(added), projects=len(per_project))
        return self.detail(request_id)

    def edit(self, request_id: int, cmd: EditCommand) -> dict:
        """An edit from a button or a form (by="user"): the associate's own words, or a reviewer's while it waits for review."""
        try:
            changed, message = self._apply(request_id, cmd, "user", reviewer_ok=True)
        except EditError as e:
            raise ServiceError(f"edit_{e.code}", str(e), 422) from None
        return {"changed": changed, "message": message, "detail": self.detail(request_id)}

    def chat(self, request_id: int, message: str) -> dict:
        """An edit in words. The model only picks a command; it runs with by="assistant", so it cannot add claims."""
        _, _, working, _ = self._editing(request_id)  # checks access and status before the model is called
        if self.engine.interpreter is None:
            raise ServiceError("chat_unavailable", "Chat editing is not available right now.", 503)
        try:
            command = self.engine.interpreter(message, working)
        except ExtractionError:
            return {"reply": "I could not work out what to change. Could you say it another way?", "changed": False,
                    "detail": self.detail(request_id)}
        try:
            changed, reply = self._apply(request_id, command, "assistant")
        except EditError as e:
            reply = f"I did not change that. {e}"
            if e.code == "ungrounded":
                reply += " If it is true, tell me the fact and I will add it as your own statement."
            changed = False
        return {"reply": reply, "changed": changed, "detail": self.detail(request_id)}

    # ------------------------------------------------------------------------------------ download
    def _render_current(self, request_id: int):
        """The resume as it would be downloaded now: (row, approved?, resume, template bytes, rendered, years source)."""
        row = self._visible(request_id)
        draft = self._need_draft(request_id)
        approved = None
        if row["status"] == "approved":
            approved = self.conn.execute(
                "SELECT * FROM resume_versions WHERE request_id = ? AND kind = 'approved' ORDER BY version DESC LIMIT 1",
                (request_id,)).fetchone()
        source = approved if approved is not None else draft
        template_id = source["template_id"] or draft["template_id"]
        template = self.conn.execute("SELECT * FROM resume_templates WHERE id = ?", (template_id,)).fetchone() or self.active_template()
        if template is None:
            raise ServiceError("no_template", "The resume template is not available.", 409)
        resume = Resume.model_validate_json(source["resume_json"] if approved is not None else draft["working_json"])
        template_bytes = self.files.get(template["file_key"])
        rendered = render_best(template_bytes, resume, years_text=source["years_text"])
        return row, approved is not None, resume, template_bytes, rendered

    def _check(self, request_id: int, resume, template_bytes: bytes, rendered, where: str):
        """Compare the finished file with the template; the result is logged, and never stops anything."""
        try:
            report = check_conformance(template_bytes, rendered.docx, resume, used_standard_layout=rendered.used_standard_layout)
        except Exception as e:  # noqa: BLE001 - a fault in the check must never stop a download
            self._log("conformance_failed", "error", error=e, request_id=request_id, where=where)
            return Report(checks=(Check("check", WARN, "The template check could not be run for this resume."),))
        problems = [f"{c.name}: {c.message}" for c in report.checks if c.status != "pass"]
        if report.status != "pass" or where == "download":  # a clean preview check is not worth a line each time the page opens
            self._log("conformance", {"pass": "info", "warn": "warning", "fail": "error"}[report.status], request_id=request_id,
                      where=where, status=report.status, problems=" | ".join(problems) or None)
        return report

    def _polish(self, request_id: int, rendered, template_bytes: bytes):
        """Have the layout checked and, if needed, fixed before the file goes to the user. It can only improve the file; if it
        cannot be done (no renderer on this server, or anything fails) the file goes as it is."""
        self.last_layout = "not_checked"
        if self.engine.polisher is None:
            return rendered
        try:
            result = self.engine.polisher(rendered.docx, template_bytes)
        except Exception as e:  # noqa: BLE001 - the layout check must never stop a download
            self._log("layout_failed", "error", error=e, request_id=request_id)
            return rendered
        self.last_layout = result.status
        self._log("layout_judged", "info" if result.status in ("ok", "fixed") else "warning", request_id=request_id,
                  status=result.status, rounds=result.rounds, issues=" | ".join(result.issues) or None,
                  notes=" | ".join(result.notes) or None)
        return replace(rendered, docx=result.docx)

    def download(self, request_id: int) -> tuple[str, bytes, bool]:
        """(filename, .docx bytes, is_draft). The document itself has no draft mark; its file name ends in _DRAFT until the
        resume is approved and in _FINAL after. `self.last_report` is how well it matches the template."""
        row, approved, resume, template_bytes, rendered = self._render_current(request_id)
        rendered = self._polish(request_id, rendered, template_bytes)
        self._log_render(request_id, rendered, "download")
        self.last_report = self._check(request_id, resume, template_bytes, rendered, "download")
        suffix = "_FINAL" if approved else "_DRAFT"
        name = f"{_safe_filename(self._name(row['associate_id']))}_{_safe_filename(self._jd_title(row['jd_id']))}{suffix}.docx"
        self._audit("resume_downloaded", {"request_id": request_id, "draft": not approved, "check": self.last_report.status})
        self.conn.commit()
        return name, rendered.docx, not approved

    def conformance(self, request_id: int) -> dict:
        """Does the resume, as it would be downloaded now, match the setup template? Anyone who can see the request may ask."""
        _, _, resume, template_bytes, rendered = self._render_current(request_id)
        return self._check(request_id, resume, template_bytes, rendered, "preview").to_dict()

    # ------------------------------------------------------------------------------------ notifications
    def notifications(self, unread_only: bool = False) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, message, request_id, created_at, read_at FROM notifications WHERE employee_id = ?"
            + (" AND read_at IS NULL" if unread_only else "") + " ORDER BY id DESC LIMIT 50", (self.actor.id,)).fetchall()
        return [dict(r) for r in rows]

    def mark_read(self, ids: list[int] | None = None) -> None:
        if ids is None:
            self.conn.execute("UPDATE notifications SET read_at = ? WHERE employee_id = ? AND read_at IS NULL", (self._iso(), self.actor.id))
        else:
            for i in ids:
                self.conn.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND employee_id = ? AND read_at IS NULL",
                                  (self._iso(), i, self.actor.id))
        self.conn.commit()

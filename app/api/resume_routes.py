"""HTTP routes for the resume builder. Thin: each route checks the input shape and calls ResumeService, which owns
every permission and status rule. Uploads are sent as the raw request body (the file name goes in the query string),
so no multipart library is needed, and the size is capped while reading."""
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.db import repositories as repo
from app.rmg.resume.chat import EditCommand
from app.rmg.resume.filestore import FileStore
from app import issue_log
from app.rmg.resume.service import ResumeEngine, ResumeService, ServiceError

MAX_RESUME_UPLOAD = 6_000_000
MAX_TEMPLATE_UPLOAD = 41_000_000
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class TagBody(BaseModel):
    associate_ids: list[int] = Field(min_length=1, max_length=50)
    role_index: int = Field(default=0, ge=0, le=20)


class LeadBody(BaseModel):
    associate_id: int
    lead_id: int


class BuildBody(BaseModel):
    force: bool = False


class DecideBody(BaseModel):
    decision: Literal["approve", "send_back"]
    note: str | None = Field(default=None, max_length=1000)


class PasteBody(BaseModel):
    text: str = Field(min_length=1, max_length=40000)
    title: str | None = Field(default=None, max_length=150)


class ChatEditBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ReadBody(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=100)


async def read_upload(request: Request, limit: int) -> bytes:
    """The request body, refused as soon as it is known to be too big."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ServiceError("too_large", "That file is too large.", 413)
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise ServiceError("too_large", "That file is too large.", 413)
    if not data:
        raise ServiceError("empty", "No file was sent.", 422)
    return bytes(data)


def register_resume_routes(app: FastAPI, *, get_conn, current_employee, now: Callable[[], datetime],
                           engine: ResumeEngine | None, files: FileStore | None) -> None:
    def who(request: Request) -> dict:
        return {"user": getattr(request.state, "actor_name", None), "user_id": getattr(request.state, "actor_id", None),
                "roles": getattr(request.state, "actor_roles", None)}

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        trace_id = getattr(request.state, "trace_id", "-")
        issue_log.event("request_rejected", level="error" if exc.status >= 500 else "warning", trace=trace_id, method=request.method,
                        path=request.url.path, status=exc.status, code=exc.code, message=str(exc), **who(request))
        return JSONResponse(status_code=exc.status, headers={"X-Trace-Id": trace_id},
                            content={"error": {"code": exc.code, "message": str(exc), "trace_id": trace_id}})

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        """Anything not planned for: the full traceback goes to the log, and the user gets a trace id to quote."""
        trace_id = getattr(request.state, "trace_id", "-")
        issue_log.event("request_crashed", level="error", error=exc, trace=trace_id, method=request.method,
                        path=request.url.path, **who(request))
        return JSONResponse(status_code=500, headers={"X-Trace-Id": trace_id}, content={"error": {
            "code": "internal_error", "message": "Something went wrong on our side. Please quote the trace id to support.",
            "trace_id": trace_id}})

    def service(request: Request, employee: repo.Employee = Depends(current_employee),
                conn: sqlite3.Connection = Depends(get_conn)) -> ResumeService:
        if engine is None or files is None:
            raise HTTPException(503, "The resume builder is not available right now.")
        svc = ResumeService(conn, files, engine, now, employee)
        request.state.actor_name, request.state.actor_id = employee.name, employee.id
        request.state.actor_roles = ",".join(sorted(svc.roles)) or None
        return svc

    @app.get("/resume/me")
    def resume_me(employee: repo.Employee = Depends(current_employee), conn: sqlite3.Connection = Depends(get_conn)):
        """Always answers (200), so the web app can ask "is the resume builder here?" without a failed request."""
        if engine is None or files is None:
            return {"available": False, "roles": [], "unread": 0}
        svc = ResumeService(conn, files, engine, now, employee)
        return {"available": True, "roles": sorted(svc.roles), "unread": len(svc.notifications(unread_only=True))}

    @app.get("/resume/template")
    def get_template(svc: ResumeService = Depends(service)):
        return {"template": svc.template_info()}

    @app.post("/resume/template")
    async def upload_template(request: Request, filename: str = "template.docx", name: str | None = None,
                              svc: ResumeService = Depends(service)):
        return svc.upload_template(filename, await read_upload(request, MAX_TEMPLATE_UPLOAD), name)

    @app.get("/resume/leads")
    def leads(svc: ResumeService = Depends(service)):
        return svc.list_leads()

    @app.put("/resume/leads")
    def set_lead(body: LeadBody, svc: ResumeService = Depends(service)):
        svc.set_lead(body.associate_id, body.lead_id)
        return {"status": "ok"}

    @app.get("/resume/jds")
    def jds(svc: ResumeService = Depends(service)):
        return {"jds": svc.list_jds()}

    @app.post("/resume/jds")
    async def create_jd(request: Request, filename: str = "jd.txt", title: str | None = None,
                        svc: ResumeService = Depends(service)):
        return svc.create_jd(filename, await read_upload(request, MAX_RESUME_UPLOAD), title)

    def as_attachment(result: tuple[str, bytes, str]) -> Response:
        name, data, media_type = result
        return Response(content=data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/resume/jds/{jd_id}/file")
    def jd_file(jd_id: int, svc: ResumeService = Depends(service)):
        return as_attachment(svc.jd_file(jd_id))

    @app.get("/resume/requests/{request_id}/jd")
    def request_jd(request_id: int, svc: ResumeService = Depends(service)):
        return as_attachment(svc.download_jd(request_id))

    @app.get("/resume/jds/{jd_id}/preview")
    def jd_preview(jd_id: int, svc: ResumeService = Depends(service)):
        return svc.jd_preview(jd_id)

    @app.get("/resume/requests/{request_id}/jd/preview")
    def request_jd_preview(request_id: int, svc: ResumeService = Depends(service)):
        return svc.request_jd_preview(request_id)

    @app.post("/resume/jds/text")
    def create_jd_from_text(body: PasteBody, svc: ResumeService = Depends(service)):
        return svc.create_jd_from_text(body.text, body.title)

    @app.get("/resume/associates")
    def associates(svc: ResumeService = Depends(service)):
        return {"associates": svc.associates()}

    @app.post("/resume/jds/{jd_id}/tag")
    def tag(jd_id: int, body: TagBody, svc: ResumeService = Depends(service)):
        return svc.tag(jd_id, body.associate_ids, body.role_index)

    @app.get("/resume/requests")
    def requests_list(scope: Literal["mine", "lead", "review", "board"] = "mine", svc: ResumeService = Depends(service)):
        return {"requests": svc.summaries(scope)}

    @app.get("/resume/requests/{request_id}")
    def request_detail(request_id: int, svc: ResumeService = Depends(service)):
        return svc.detail(request_id)

    @app.post("/resume/requests/{request_id}/resume")
    async def upload_resume(request_id: int, request: Request, filename: str = "resume.docx",
                            svc: ResumeService = Depends(service)):
        return svc.upload_resume(request_id, filename, await read_upload(request, MAX_RESUME_UPLOAD))

    @app.post("/resume/requests/{request_id}/build")
    def build(request_id: int, body: BuildBody | None = None, svc: ResumeService = Depends(service)):
        return svc.build(request_id, force=bool(body and body.force))

    @app.post("/resume/requests/{request_id}/edit")
    def edit(request_id: int, body: EditCommand, svc: ResumeService = Depends(service)):
        return svc.edit(request_id, body)

    @app.post("/resume/requests/{request_id}/chat")
    def chat(request_id: int, body: ChatEditBody, svc: ResumeService = Depends(service)):
        return svc.chat(request_id, body.message)

    @app.post("/resume/requests/{request_id}/save")
    def save(request_id: int, svc: ResumeService = Depends(service)):
        return svc.save(request_id)

    @app.post("/resume/requests/{request_id}/submit")
    def submit(request_id: int, svc: ResumeService = Depends(service)):
        return svc.submit(request_id)

    @app.post("/resume/requests/{request_id}/decide")
    def decide(request_id: int, body: DecideBody, svc: ResumeService = Depends(service)):
        return svc.decide(request_id, body.decision, body.note)

    @app.post("/resume/requests/{request_id}/reopen")
    def reopen(request_id: int, svc: ResumeService = Depends(service)):
        return svc.reopen(request_id)

    @app.post("/resume/requests/{request_id}/cancel")
    def cancel(request_id: int, svc: ResumeService = Depends(service)):
        svc.cancel(request_id)
        return {"status": "cancelled"}

    @app.get("/resume/requests/{request_id}/download")
    def download(request_id: int, svc: ResumeService = Depends(service)):
        name, data, is_draft = svc.download(request_id)
        return Response(content=data, media_type=DOCX, headers={
            "Content-Disposition": f'attachment; filename="{name}"', "X-Resume-Draft": "true" if is_draft else "false",
            "X-Resume-Check": svc.last_report.status})

    @app.get("/resume/requests/{request_id}/conformance")
    def conformance(request_id: int, svc: ResumeService = Depends(service)):
        return svc.conformance(request_id)

    @app.get("/resume/notifications")
    def notifications(unread: bool = False, svc: ResumeService = Depends(service)):
        return {"notifications": svc.notifications(unread_only=unread)}

    @app.post("/resume/notifications/read")
    def mark_read(body: ReadBody | None = None, svc: ResumeService = Depends(service)):
        svc.mark_read(body.ids if body else None)
        return {"status": "ok"}

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
    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        trace_id = getattr(request.state, "trace_id", "-")
        return JSONResponse(status_code=exc.status, headers={"X-Trace-Id": trace_id},
                            content={"error": {"code": exc.code, "message": str(exc), "trace_id": trace_id}})

    def service(employee: repo.Employee = Depends(current_employee), conn: sqlite3.Connection = Depends(get_conn)) -> ResumeService:
        if engine is None or files is None:
            raise HTTPException(503, "The resume builder is not available right now.")
        return ResumeService(conn, files, engine, now, employee)

    @app.get("/resume/me")
    def resume_me(svc: ResumeService = Depends(service)):
        return {"roles": sorted(svc.roles), "unread": len(svc.notifications(unread_only=True))}

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

    @app.get("/resume/associates")
    def associates(svc: ResumeService = Depends(service)):
        return {"associates": svc.associates()}

    @app.post("/resume/jds/{jd_id}/tag")
    def tag(jd_id: int, body: TagBody, svc: ResumeService = Depends(service)):
        return svc.tag(jd_id, body.associate_ids, body.role_index)

    @app.get("/resume/requests")
    def requests_list(scope: Literal["mine", "lead", "board"] = "mine", svc: ResumeService = Depends(service)):
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
            "Content-Disposition": f'attachment; filename="{name}"', "X-Resume-Draft": "true" if is_draft else "false"})

    @app.get("/resume/notifications")
    def notifications(unread: bool = False, svc: ResumeService = Depends(service)):
        return {"notifications": svc.notifications(unread_only=unread)}

    @app.post("/resume/notifications/read")
    def mark_read(body: ReadBody | None = None, svc: ResumeService = Depends(service)):
        svc.mark_read(body.ids if body else None)
        return {"status": "ok"}

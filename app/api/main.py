"""FastAPI application factory."""
import json
import logging
import re
import sqlite3
import uuid
from pathlib import Path
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.graph import _chunks, stream_turn
from app.api import security
from app.api.throttle import LoginThrottle, RateLimiter
from app.config import Settings
from app.db import repositories as repo
from app.db.seed import DEMO_PASSWORD
from app.observability import audit
from app.rag.search import Retrieval
from app.services import leave as leave_service
from app.tools.context import ToolContext
from app.tools.registry import call_tool

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parents[1] / "ui" / "static"
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
POLICY_ID = re.compile(r"^(POL-\d{2}) §(\d+)(?:\.\d+)*$")

ConnectionProvider = Callable[[], AbstractContextManager[sqlite3.Connection]]
Clock = Callable[[], datetime]

INVALID_CREDENTIALS = "Invalid email or password."


class LoginBody(BaseModel):
    email: str
    password: str


class ChatBody(BaseModel):
    message: str = Field(max_length=20000)
    thread_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class DecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


def _error(
    status: int, code: str, message: str, request: Request, headers: dict | None = None
) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "-")
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "trace_id": trace_id}},
        headers={**(headers or {}), "X-Trace-Id": trace_id},
    )


def create_app(
    settings: Settings,
    connection: ConnectionProvider,
    clock: Clock | None = None,
    agent=None,
    retrieval: Retrieval | None = None,
) -> FastAPI:
    now: Clock = clock or (lambda: datetime.now(timezone.utc))
    app = FastAPI(title="HR Chat Agent", version="0.1.0")
    chat_limiter = RateLimiter(settings.chat_rate_limit_per_minute, timedelta(minutes=1))

    @app.middleware("http")
    async def add_trace_id(request: Request, call_next):
        request.state.trace_id = uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return _error(
            exc.status_code, f"http_{exc.status_code}", str(exc.detail), request, exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return _error(422, "validation_error", "The request was not valid.", request)

    def get_conn():
        with connection() as conn:
            yield conn

    def current_employee(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        unauthorized = HTTPException(
            401, "Authentication required.", headers={"WWW-Authenticate": "Bearer"}
        )
        if scheme.lower() != "bearer" or not token:
            raise unauthorized
        try:
            employee_id = security.decode_token(settings, token, now())
        except security.InvalidToken:
            raise unauthorized from None
        employee = repo.get_employee(conn, employee_id)
        if employee is None:
            raise unauthorized
        return employee

    login_throttle = LoginThrottle(
        settings.lockout_max_failures,
        timedelta(minutes=settings.lockout_window_minutes),
        timedelta(minutes=settings.lockout_duration_minutes),
    )

    @app.post("/auth/login")
    def login(body: LoginBody, conn: sqlite3.Connection = Depends(get_conn)):
        key = body.email.strip().lower()
        if wait := login_throttle.seconds_locked(key, now()):
            raise HTTPException(
                429,
                "Too many failed sign-in attempts. Please try again later.",
                headers={"Retry-After": str(wait)},
            )
        employee = repo.get_employee_by_email(conn, body.email)
        stored = repo.get_password_hash(conn, employee.id) if employee else None
        # Verify against a dummy hash for unknown users so timing does not reveal them.
        valid = security.verify_password(body.password, stored or _DUMMY_HASH)
        if not (employee and stored and valid):
            login_throttle.record_failure(key, now())
            raise HTTPException(401, INVALID_CREDENTIALS)
        login_throttle.record_success(key)
        token = security.create_token(settings, employee.id, employee.role, now())
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": settings.token_ttl_minutes * 60,
        }

    @app.get("/me")
    def me(employee: repo.Employee = Depends(current_employee)):
        return {
            "id": employee.id,
            "name": employee.name,
            "email": employee.email,
            "role": employee.role,
            "status": employee.status,
            "department": employee.department,
        }

    def tool_context(employee: repo.Employee, conn: sqlite3.Connection, request: Request):
        return ToolContext(
            conn=conn,
            employee_id=employee.id,
            role=employee.role,
            trace_id=request.state.trace_id,
            today=now().date(),
            retrieval=retrieval,
            now=now(),
        )

    @app.get("/health")
    def health(conn: sqlite3.Connection = Depends(get_conn)):
        conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "ok"}

    @app.get("/leave/balance")
    def leave_balance(
        request: Request,
        employee: repo.Employee = Depends(current_employee),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        return call_tool(tool_context(employee, conn, request), "get_leave_balance", {})

    @app.get("/leave/requests")
    def leave_requests(
        request: Request,
        scope: Literal["own", "team"] = "own",
        employee: repo.Employee = Depends(current_employee),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        ctx = tool_context(employee, conn, request)
        if scope == "own":
            return call_tool(ctx, "get_leave_history", {})
        if employee.role != "manager":
            raise HTTPException(403, "Only managers can view team requests.")
        rows = repo.list_team_requests(conn, employee.id)
        return {
            "requests": [
                {
                    "id": r.id,
                    "employee": r.employee_name,
                    "leave_type": r.leave_type,
                    "start_date": r.start.isoformat(),
                    "end_date": r.end.isoformat(),
                    "days": r.days_counted,
                    "status": r.status,
                }
                for r in rows
            ]
        }

    @app.post("/leave/requests/{request_id}/decision")
    def decide_leave_request(
        request_id: int,
        body: DecisionBody,
        request: Request,
        employee: repo.Employee = Depends(current_employee),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        if employee.role != "manager":
            raise HTTPException(403, "Only managers can decide leave requests.")
        outcome = repo.decide_request(
            conn, employee.id, request_id, body.decision, body.note, now().isoformat(timespec="seconds")
        )
        if outcome == "not_found":
            raise HTTPException(404, "Leave request not found.")
        if outcome == "not_pending":
            raise HTTPException(409, "This request has already been decided.")
        audit.record(
            tool_context(employee, conn, request),
            "leave_decision",
            "leave_decision",
            {"request_id": request_id, "decision": body.decision, "note": body.note},
        )
        return {"id": request_id, "status": "approved" if body.decision == "approve" else "rejected"}

    @app.get("/demo/accounts")
    def demo_accounts(conn: sqlite3.Connection = Depends(get_conn)):
        if not settings.demo_mode:
            raise HTTPException(404, "Not found.")
        return {"accounts": repo.list_demo_accounts(conn), "password": DEMO_PASSWORD}

    @app.get("/policy/section")
    def policy_section(
        id: str,
        employee: repo.Employee = Depends(current_employee),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        """The text behind a citation chip. A clause id such as POL-05 §3.1 resolves to its section."""
        match = POLICY_ID.match(id.strip())
        section = repo.get_policy_section(conn, f"{match.group(1)} §{match.group(2)}") if match else None
        if section is None:
            raise HTTPException(404, "Policy section not found.")
        return section

    @app.post("/leave/drafts/{draft_id}/confirm")
    def confirm_leave_draft(
        draft_id: str,
        request: Request,
        employee: repo.Employee = Depends(current_employee),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        # The only place a draft becomes a request. The model has no route to this endpoint.
        result = leave_service.confirm_draft(tool_context(employee, conn, request), draft_id, now())
        if result.outcome == "ok":
            return {"status": "submitted", "request_id": result.request_id}
        if result.outcome == "already_submitted":
            return {"status": "already_submitted", "request_id": result.request_id}
        if result.outcome == "expired":
            raise HTTPException(410, "This request expired. Please ask me to prepare it again.")
        if result.outcome == "no_longer_eligible":
            response = _error(
                409, "http_409", "This request is no longer allowed. Please review the reasons.", request
            )
            body = json.loads(response.body)
            body["rules"] = [
                {"rule_id": r.rule_id, "passed": r.passed, "blocking": r.blocking,
                 "message": r.message, "policy_ref": r.policy_ref}
                for r in result.rules
            ]
            return JSONResponse(status_code=409, content=body, headers=dict(response.headers))
        raise HTTPException(404, "Draft not found.")

    @app.post("/leave/drafts/{draft_id}/cancel")
    def cancel_leave_draft(
        draft_id: str,
        request: Request,
        employee: repo.Employee = Depends(current_employee),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        if not leave_service.cancel_draft(tool_context(employee, conn, request), draft_id):
            raise HTTPException(404, "Draft not found.")
        return {"status": "cancelled"}

    @app.post("/leave/requests/{request_id}/cancel")
    def cancel_leave_request(
        request_id: int,
        request: Request,
        employee: repo.Employee = Depends(current_employee),
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        outcome = leave_service.cancel_request(tool_context(employee, conn, request), request_id)
        if outcome == "not_found":
            raise HTTPException(404, "Leave request not found.")
        if outcome == "not_cancellable":
            raise HTTPException(409, "This request can no longer be cancelled.")
        return {"id": request_id, "status": "cancelled"}

    @app.post("/chat")
    def chat(
        body: ChatBody,
        request: Request,
        employee: repo.Employee = Depends(current_employee),
    ):
        if agent is None:
            raise HTTPException(503, "Chat is not available right now.")
        if wait := chat_limiter.retry_after(str(employee.id), now()):
            raise HTTPException(
                429, "You are sending messages too quickly. Please wait a moment.",
                headers={"Retry-After": str(wait)},
            )
        public_thread = body.thread_id or uuid.uuid4().hex
        # Thread ids are namespaced by employee, so guessing another person's id reaches nothing.
        thread_key = f"{employee.id}:{public_thread}"
        trace_id = request.state.trace_id

        def events():
            # Opens its own connection: the request-scoped one may close before streaming ends.
            with connection() as conn:
                ctx = ToolContext(
                    conn=conn, employee_id=employee.id, role=employee.role, trace_id=trace_id,
                    today=now().date(), retrieval=retrieval, now=now(),
                )
                try:
                    stream = _reply_to_confirmation(ctx, body.message, now()) or stream_turn(
                        agent, ctx, thread_key, body.message
                    )
                    for name, data in stream:
                        if name == "done":
                            data = {**data, "thread_id": public_thread, "trace_id": trace_id}
                        yield _sse(name, data)
                except Exception:
                    log.exception("chat turn failed (trace %s)", trace_id)
                    yield _sse("error", {"message": "Something went wrong on my side. Please try again in a moment.",
                                         "trace_id": trace_id})

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    # Last, so every API route above takes precedence over the static web app.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
    return app


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


CONFIRM_WORDS = frozenset({"yes", "y", "confirm", "yes please", "confirm it", "go ahead"})
CANCEL_WORDS = frozenset({"no", "n", "cancel", "no thanks", "cancel it", "never mind"})


def _reply_to_confirmation(ctx: ToolContext, message: str, when: datetime):
    """Handle a bare 'yes' or 'no' while a draft is waiting. No model is involved."""
    word = message.strip().lower().rstrip(".! ")
    if word not in CONFIRM_WORDS | CANCEL_WORDS:
        return None
    draft = repo.get_open_draft(ctx.conn, ctx.employee_id)
    if draft is None:
        return None
    if word in CANCEL_WORDS:
        leave_service.cancel_draft(ctx, draft["draft_id"])
        text = "Okay, I've cancelled that request. Nothing was submitted."
    else:
        result = leave_service.confirm_draft(ctx, draft["draft_id"], when)
        if result.outcome in ("ok", "already_submitted"):
            text = (
                f"Done. Your {draft['leave_type']} request for {draft['days']:g} day(s) from "
                f"{draft['start_date']} to {draft['end_date']} has been submitted and is waiting "
                "for your manager's approval."
            )
        elif result.outcome == "expired":
            text = "That request expired. Tell me the dates again and I'll prepare it."
        else:
            text = "That request is no longer allowed, so I did not submit it. Ask me to check it again."

    def stream():
        yield "route", {"intent": "confirmation", "needs_planning": False}
        for piece in _chunks(text):
            yield "token", {"text": piece}
        yield "done", {"intent": "confirmation", "used_fallback": False, "rewrites": 0, "flags": []}

    return stream()


_DUMMY_HASH = security.hash_password("dummy-password-for-timing")

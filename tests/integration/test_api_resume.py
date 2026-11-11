"""The resume builder over HTTP: one full journey and the guards around it. Models are fakes; files go to a temp dir."""
import io
from contextlib import nullcontext

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.rmg.resume.chat import EditCommand
from app.rmg.resume.demo import seed_resume_demo
from app.rmg.resume.draft import TailoringSettings
from app.rmg.resume.filestore import FileStore
from app.rmg.resume.pipeline import PipelineDeps
from app.rmg.resume.service import ResumeEngine
from tests.integration.conftest import SECRET, auth_headers
from tests.unit.resume_fakes import FakeJDExtractor, FakeResumeExtractor, keep_as_written
from tests.unit.resume_templates import make_template

HEAD, STAFF, LEAD, RAVI, DIVYA, SANJAY = "Nancy", "Shadrach", "Veera", "Ravi Kumar", "Divya Menon", "Sanjay Patel"


def template_bytes() -> bytes:
    buf = io.BytesIO()
    make_template().save(buf)
    return buf.getvalue()


@pytest.fixture
def make_client(api_db, clock, tmp_path, argon_hash):
    def build(with_resume=True):
        seed_resume_demo(api_db, hash_password=lambda p: argon_hash)
        engine = ResumeEngine(PipelineDeps(FakeResumeExtractor(), FakeJDExtractor(), keep_as_written, TailoringSettings()),
                              lambda message, resume: EditCommand(action="remove", path="projects.0.bullets.0", reply="Removed."))
        app = create_app(Settings(jwt_secret=SECRET), connection=lambda: nullcontext(api_db), clock=clock,
                         resume_engine=engine if with_resume else None,
                         resume_files=FileStore(tmp_path / "files") if with_resume else None)
        return TestClient(app)

    return build


@pytest.fixture
def client(make_client):
    return make_client()


def hdr(client, who):
    return auth_headers(client, who)


def tagged_request(client):
    """The template is uploaded and RMG has tagged Ravi for the demo JD. Returns the request id."""
    assert client.post("/resume/template?filename=t.docx", content=template_bytes(), headers=hdr(client, HEAD)).status_code == 200
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]
    ravi_id = next(a["id"] for a in client.get("/resume/associates", headers=hdr(client, STAFF)).json()["associates"] if a["name"] == RAVI)
    result = client.post(f"/resume/jds/{jd_id}/tag", json={"associate_ids": [ravi_id]}, headers=hdr(client, STAFF))
    assert result.status_code == 200, result.text
    return result.json()["created"][0]["request_id"]


# --- access --------------------------------------------------------------------------------------------------

def test_the_resume_routes_need_a_signed_in_user(client):
    assert client.get("/resume/me").status_code == 401
    assert client.get("/resume/requests").status_code == 401


def test_the_routes_report_unavailable_when_the_builder_is_not_configured(make_client):
    client = make_client(with_resume=False)

    assert client.get("/resume/me", headers=hdr(client, RAVI)).json() == {"available": False, "roles": [], "unread": 0}
    assert client.get("/resume/requests", headers=hdr(client, RAVI)).status_code == 503


def test_me_lists_the_persons_rmg_roles(client):
    assert client.get("/resume/me", headers=hdr(client, HEAD)).json()["roles"] == ["rmg_head"]
    assert client.get("/resume/me", headers=hdr(client, LEAD)).json()["roles"] == ["competency_lead"]
    assert client.get("/resume/me", headers=hdr(client, RAVI)).json()["roles"] == []


def test_forbidden_errors_carry_a_machine_code_a_message_and_a_trace_id(client):
    response = client.get("/resume/jds", headers=hdr(client, RAVI))

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "forbidden" and error["message"] and error["trace_id"]


# --- the whole journey ----------------------------------------------------------------------------------------

def test_a_resume_goes_from_request_to_approved_download(client):
    request_id = tagged_request(client)
    base = f"/resume/requests/{request_id}"

    assert client.post(f"{base}/resume?filename=cv.txt", content=b"Ravi Kumar backend engineer", headers=hdr(client, RAVI)).status_code == 200
    built = client.post(f"{base}/build", headers=hdr(client, RAVI))
    assert built.status_code == 200 and built.json()["status"] == "in_progress" and built.json()["resume"]["name"] == "Anil Verma"

    draft = client.get(f"{base}/download", headers=hdr(client, STAFF))
    assert draft.status_code == 200 and draft.headers["x-resume-draft"] == "true" and "_DRAFT.docx" in draft.headers["content-disposition"]

    assert client.post(f"{base}/save", headers=hdr(client, RAVI)).json() == {"version": 1}
    assert client.post(f"{base}/submit", headers=hdr(client, RAVI)).json()["status"] == "submitted"
    assert client.get("/resume/requests?scope=lead", headers=hdr(client, LEAD)).json()["requests"][0]["status"] == "submitted"
    decided = client.post(f"{base}/decide", json={"decision": "approve", "note": "Good"}, headers=hdr(client, LEAD))
    assert decided.json() == {"status": "approved"}

    final = client.get(f"{base}/download", headers=hdr(client, STAFF))
    assert final.headers["x-resume-draft"] == "false" and "DRAFT" not in final.headers["content-disposition"]
    sections = Document(io.BytesIO(final.content)).sections
    assert "DRAFT" not in " ".join(p.text for s in sections for p in s.header.paragraphs)
    assert client.get("/resume/requests?scope=board", headers=hdr(client, STAFF)).json()["requests"][0]["status"] == "approved"


def test_a_lead_can_send_it_back_and_the_associate_sees_the_note_and_a_notification(client):
    request_id = tagged_request(client)
    base = f"/resume/requests/{request_id}"
    client.post(f"{base}/resume?filename=cv.txt", content=b"Ravi", headers=hdr(client, RAVI))
    client.post(f"{base}/build", headers=hdr(client, RAVI))
    client.post(f"{base}/submit", headers=hdr(client, RAVI))

    assert client.post(f"{base}/decide", json={"decision": "send_back"}, headers=hdr(client, LEAD)).status_code == 422
    client.post(f"{base}/decide", json={"decision": "send_back", "note": "More on Kafka"}, headers=hdr(client, LEAD))

    detail = client.get(base, headers=hdr(client, RAVI)).json()
    assert detail["status"] == "changes_requested" and detail["decision_note"] == "More on Kafka"
    notes = client.get("/resume/notifications?unread=true", headers=hdr(client, RAVI)).json()["notifications"]
    assert any("sent back" in n["message"] for n in notes)
    assert client.post("/resume/notifications/read", headers=hdr(client, RAVI)).status_code == 200
    assert client.get("/resume/notifications?unread=true", headers=hdr(client, RAVI)).json()["notifications"] == []


def test_tagging_reports_who_was_skipped_and_why(client):
    client.post("/resume/template?filename=t.docx", content=template_bytes(), headers=hdr(client, HEAD))
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]
    people = {a["name"]: a for a in client.get("/resume/associates", headers=hdr(client, STAFF)).json()["associates"]}
    assert people[SANJAY]["lead"] is None and people[RAVI]["lead"] == LEAD

    result = client.post(f"/resume/jds/{jd_id}/tag", json={"associate_ids": [people[SANJAY]["id"], people[RAVI]["id"]]},
                         headers=hdr(client, STAFF)).json()

    assert len(result["created"]) == 1 and result["skipped"][0]["reason"] == "no_lead"


def test_the_head_can_give_the_unmapped_associate_a_lead_and_then_tag_them(client):
    head = hdr(client, HEAD)
    state = client.get("/resume/leads", headers=head).json()
    sanjay = next(p["id"] for p in state["employees"] if p["name"] == SANJAY)
    lead = state["leads"][0]["id"]

    assert client.put("/resume/leads", json={"associate_id": sanjay, "lead_id": lead}, headers=head).status_code == 200
    assert client.put("/resume/leads", json={"associate_id": sanjay, "lead_id": sanjay}, headers=head).status_code == 422
    assert client.put("/resume/leads", json={"associate_id": sanjay, "lead_id": lead}, headers=hdr(client, STAFF)).status_code == 403


# --- guards -----------------------------------------------------------------------------------------------------

def test_people_outside_a_request_cannot_see_or_download_it(client):
    request_id = tagged_request(client)

    for path in (f"/resume/requests/{request_id}", f"/resume/requests/{request_id}/download"):
        assert client.get(path, headers=hdr(client, DIVYA)).status_code == 404


def test_an_associate_cannot_use_rmg_or_lead_actions(client):
    request_id = tagged_request(client)
    ravi = hdr(client, RAVI)

    assert client.get("/resume/requests?scope=board", headers=ravi).status_code == 403
    assert client.post(f"/resume/requests/{request_id}/cancel", headers=ravi).status_code == 403
    assert client.post(f"/resume/requests/{request_id}/decide", json={"decision": "approve"}, headers=ravi).status_code in (403, 409)
    assert client.post("/resume/template?filename=t.docx", content=template_bytes(), headers=ravi).status_code == 403


def test_uploads_are_size_limited_and_must_not_be_empty(client):
    request_id = tagged_request(client)
    ravi = hdr(client, RAVI)

    assert client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=b"", headers=ravi).status_code == 422
    big = client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=b"x" * 6_100_000, headers=ravi)
    assert big.status_code == 413 and big.json()["error"]["code"] == "too_large"


def test_a_bad_upload_gets_the_friendly_reason(client):
    request_id = tagged_request(client)

    response = client.post(f"/resume/requests/{request_id}/resume?filename=cv.exe", content=b"x", headers=hdr(client, RAVI))

    assert response.status_code == 422 and "Word" in response.json()["error"]["message"]


def test_tag_input_is_validated(client):
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]

    assert client.post(f"/resume/jds/{jd_id}/tag", json={"associate_ids": []}, headers=hdr(client, STAFF)).status_code == 422
    assert client.post(f"/resume/jds/{jd_id}/tag", json={"associate_ids": [1], "role_index": -1}, headers=hdr(client, STAFF)).status_code == 422


def test_a_jd_can_be_uploaded_by_rmg(client):
    response = client.post("/resume/jds?filename=jd.txt&title=Platform%20Engineer", content=b"We need a Java developer",
                           headers=hdr(client, STAFF))

    assert response.status_code == 200 and response.json()["title"] == "Platform Engineer"


def built_request(client):
    request_id = tagged_request(client)
    client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=b"Ravi", headers=hdr(client, RAVI))
    client.post(f"/resume/requests/{request_id}/build", headers=hdr(client, RAVI))
    return request_id


def test_an_edit_button_and_undo_work_over_http(client):
    request_id = built_request(client)
    base = f"/resume/requests/{request_id}"

    edited = client.post(f"{base}/edit", json={"action": "remove", "path": "projects.0.bullets.0"}, headers=hdr(client, RAVI))
    assert edited.status_code == 200 and edited.json()["changed"]
    assert client.post(f"{base}/edit", json={"action": "undo"}, headers=hdr(client, RAVI)).json()["message"] == "Undone."
    bad = client.post(f"{base}/edit", json={"action": "remove", "path": "projects.9.bullets.0"}, headers=hdr(client, RAVI))
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "edit_no_such_item"
    assert client.post(f"{base}/edit", json={"action": "fly"}, headers=hdr(client, RAVI)).status_code == 422


def test_chat_editing_works_over_http_and_is_for_the_associate_only(client):
    request_id = built_request(client)
    base = f"/resume/requests/{request_id}"

    reply = client.post(f"{base}/chat", json={"message": "drop the first bullet"}, headers=hdr(client, RAVI))

    assert reply.status_code == 200 and reply.json()["reply"] == "Removed." and reply.json()["changed"]
    assert client.post(f"{base}/chat", json={"message": "x"}, headers=hdr(client, STAFF)).status_code == 403
    assert client.post(f"{base}/chat", json={"message": ""}, headers=hdr(client, RAVI)).status_code == 422
    assert client.post(f"{base}/chat", json={"message": "x" * 2001}, headers=hdr(client, RAVI)).status_code == 422

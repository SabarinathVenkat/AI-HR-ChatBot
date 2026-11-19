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
    assert final.headers["x-resume-draft"] == "false" and "_FINAL.docx" in final.headers["content-disposition"]
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


def test_tagging_a_person_with_no_lead_works_and_says_rmg_reviews(client):
    client.post("/resume/template?filename=t.docx", content=template_bytes(), headers=hdr(client, HEAD))
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]
    people = {a["name"]: a for a in client.get("/resume/associates", headers=hdr(client, STAFF)).json()["associates"]}
    assert people[SANJAY]["lead"] is None and people[SANJAY]["review_by"] == "RMG" and people[RAVI]["lead"] == LEAD

    result = client.post(f"/resume/jds/{jd_id}/tag", json={"associate_ids": [people[SANJAY]["id"], people[RAVI]["id"]]},
                         headers=hdr(client, STAFF)).json()

    assert len(result["created"]) == 2 and result["skipped"] == []


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


# --- downloading the job description ----------------------------------------------------------------------------------

def test_the_job_description_of_a_request_can_be_downloaded_by_those_who_have_a_part_in_it(client):
    request_id = tagged_request(client)

    for who in (RAVI, LEAD, STAFF):
        response = client.get(f"/resume/requests/{request_id}/jd", headers=hdr(client, who))
        assert response.status_code == 200 and response.content[:2] == b"PK"  # the seeded demo JD is made into a Word file
        assert response.headers["content-disposition"].startswith('attachment; filename="')
        assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/resume/requests/{request_id}/jd", headers=hdr(client, DIVYA)).status_code == 404
    assert client.get(f"/resume/requests/{request_id}/jd").status_code == 401


def test_an_uploaded_job_description_comes_back_exactly_as_it_was_sent(client):
    original = b"We need a Java developer with Kafka experience."
    created = client.post("/resume/jds?filename=opening.txt&title=Platform%20Engineer", content=original, headers=hdr(client, STAFF)).json()

    response = client.get(f"/resume/jds/{created['id']}/file", headers=hdr(client, STAFF))

    assert response.status_code == 200 and response.content == original
    assert response.headers["content-type"].startswith("text/plain")
    assert 'filename="Platform_Engineer.txt"' in response.headers["content-disposition"]


def test_the_job_description_list_download_is_for_rmg_only_and_a_missing_one_is_not_found(client):
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]

    assert client.get(f"/resume/jds/{jd_id}/file", headers=hdr(client, RAVI)).status_code == 403
    assert client.get("/resume/jds/9999/file", headers=hdr(client, STAFF)).status_code == 404


def test_only_the_rmg_head_can_upload_a_template_over_http(client):
    for who in (STAFF, RAVI, LEAD):
        response = client.post("/resume/template?filename=t.docx", content=template_bytes(), headers=hdr(client, who))
        assert response.status_code == 403 and response.json()["error"]["code"] == "forbidden", who
    assert client.post("/resume/template?filename=t.docx", content=template_bytes()).status_code == 401
    assert client.post("/resume/template?filename=t.docx", content=template_bytes(), headers=hdr(client, HEAD)).status_code == 200
    assert client.get("/resume/template", headers=hdr(client, STAFF)).json()["template"]["filename"] == "t.docx"  # staff can see it


def test_a_job_description_can_be_pasted_as_text_over_http(client):
    response = client.post("/resume/jds/text", json={"text": "Java, Spring Boot, Kafka", "title": "Quick skills"}, headers=hdr(client, STAFF))

    assert response.status_code == 200 and response.json()["title"] == "Quick skills"
    downloaded = client.get(f"/resume/jds/{response.json()['id']}/file", headers=hdr(client, STAFF))
    assert downloaded.content == b"Java, Spring Boot, Kafka"


def test_pasting_checks_who_you_are_and_what_you_send(client):
    assert client.post("/resume/jds/text", json={"text": "Java"}, headers=hdr(client, RAVI)).status_code == 403
    assert client.post("/resume/jds/text", json={"text": "Java"}).status_code == 401
    blank = client.post("/resume/jds/text", json={"text": "   "}, headers=hdr(client, STAFF))
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "empty"
    assert client.post("/resume/jds/text", json={}, headers=hdr(client, STAFF)).status_code == 422
    assert client.post("/resume/jds/text", json={"text": "x" * 40001}, headers=hdr(client, STAFF)).status_code == 422


def test_a_skill_can_be_added_over_http_and_only_by_the_associate(client):
    request_id = built_request(client)
    base = f"/resume/requests/{request_id}"

    added = client.post(f"{base}/edit", json={"action": "add_skill", "group": 0, "text": "Terraform"}, headers=hdr(client, RAVI))
    assert added.status_code == 200 and added.json()["changed"]
    skills = [i["text"] for g in added.json()["detail"]["resume"]["skill_groups"] for i in g["items"]]
    assert "Terraform" in skills
    assert client.post(f"{base}/edit", json={"action": "add_skill", "group": 0, "text": "Ansible"}, headers=hdr(client, STAFF)).status_code == 403
    duplicate = client.post(f"{base}/edit", json={"action": "add_skill", "group": 0, "text": "terraform"}, headers=hdr(client, RAVI))
    assert duplicate.status_code == 422 and duplicate.json()["error"]["code"] == "edit_duplicate"


# --- the template check ---------------------------------------------------------------------------------------------------

def built_base(client):
    request_id = tagged_request(client)
    base = f"/resume/requests/{request_id}"
    client.post(f"{base}/resume?filename=cv.txt", content=b"Ravi Kumar backend engineer", headers=hdr(client, RAVI))
    assert client.post(f"{base}/build", headers=hdr(client, RAVI)).status_code == 200
    return base


def test_the_template_check_says_how_well_the_resume_matches_the_template(client):
    base = built_base(client)

    reply = client.get(f"{base}/conformance", headers=hdr(client, RAVI))

    assert reply.status_code == 200
    report = reply.json()
    assert report["status"] in ("pass", "warn", "fail") and report["summary"]
    assert {"template", "sections", "complete", "pages"} <= {c["name"] for c in report["checks"]}


def test_the_download_says_in_a_header_whether_the_check_passed(client):
    base = built_base(client)

    reply = client.get(f"{base}/download", headers=hdr(client, STAFF))

    assert reply.status_code == 200 and reply.headers["X-Resume-Check"] in ("pass", "warn", "fail")


def test_only_people_who_can_see_the_request_can_see_its_check(client):
    base = built_base(client)

    assert client.get(f"{base}/conformance", headers=hdr(client, DIVYA)).status_code in (403, 404)
    assert client.get(f"{base}/conformance").status_code == 401


def test_the_check_needs_a_draft_to_look_at(client):
    request_id = tagged_request(client)

    assert client.get(f"/resume/requests/{request_id}/conformance", headers=hdr(client, RAVI)).status_code in (404, 409)


# --- previewing the job description ----------------------------------------------------------------------------------------

def test_the_job_description_can_be_previewed_by_rmg_and_by_the_people_on_the_request(client):
    request_id = tagged_request(client)
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]

    rmg = client.get(f"/resume/jds/{jd_id}/preview", headers=hdr(client, STAFF))
    associate = client.get(f"/resume/requests/{request_id}/jd/preview", headers=hdr(client, RAVI))

    for reply in (rmg, associate):
        assert reply.status_code == 200
        preview = reply.json()
        assert preview["title"] and preview["roles"][0]["must_have"] and set(preview) >= {"flagged", "text", "truncated"}


def test_the_jd_preview_keeps_the_same_guards_as_the_download(client):
    request_id = tagged_request(client)
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]

    assert client.get(f"/resume/jds/{jd_id}/preview", headers=hdr(client, RAVI)).status_code == 403  # the list is for RMG
    assert client.get(f"/resume/requests/{request_id}/jd/preview", headers=hdr(client, DIVYA)).status_code in (403, 404)
    assert client.get(f"/resume/jds/{jd_id}/preview").status_code == 401
    assert client.get("/resume/jds/9999/preview", headers=hdr(client, STAFF)).status_code == 404


# --- the review queue and who may decide ------------------------------------------------------------------------------------

def test_rmg_and_the_lead_can_both_open_the_review_queue_and_approve_over_http(client):
    base = built_base(client)
    assert client.post(f"{base}/submit", headers=hdr(client, RAVI)).status_code == 200

    for who in (STAFF, LEAD):
        queue = client.get("/resume/requests?scope=review", headers=hdr(client, who))
        assert queue.status_code == 200 and [r["status"] for r in queue.json()["requests"]] == ["submitted"]

    assert client.get("/resume/requests?scope=review", headers=hdr(client, RAVI)).status_code == 403
    detail = client.get(base, headers=hdr(client, STAFF)).json()
    assert detail["can"]["decide"] is True and detail["review_by"] == "Competency Lead"
    assert client.post(f"{base}/decide", json={"decision": "approve", "note": ""}, headers=hdr(client, STAFF)).status_code == 200


def test_the_download_says_in_a_header_what_the_layout_check_did(client):
    base = built_base(client)

    reply = client.get(f"{base}/download", headers=hdr(client, STAFF))

    assert reply.status_code == 200 and reply.headers["X-Resume-Layout"] in ("ok", "fixed", "unfixed", "not_checked")


# --- the dashboard's numbers ------------------------------------------------------------------------------------

def test_stats_for_rmg_cover_every_request_and_for_an_associate_only_their_own(client):
    request_id = tagged_request(client)

    rmg = client.get("/resume/stats", headers=hdr(client, STAFF)).json()
    own = client.get("/resume/stats", headers=hdr(client, RAVI)).json()
    other = client.get("/resume/stats", headers=hdr(client, DIVYA)).json()

    assert rmg["scope"] == "all" and rmg["total"] == 1 and rmg["by_status"]["requested"] == 1
    assert rmg["job_descriptions"] == 1 and rmg["without_lead"] >= 1
    assert own["scope"] == "mine" and own["total"] == 1 and own["recent"][0]["id"] == request_id
    assert other["total"] == 0 and other["recent"] == [] and "job_descriptions" not in other


def test_stats_for_a_competency_lead_cover_their_associates(client):
    tagged_request(client)  # Ravi is mapped to the demo lead

    lead = client.get("/resume/stats", headers=hdr(client, LEAD)).json()

    assert lead["scope"] == "lead" and lead["total"] == 1


def test_stats_carry_what_the_charts_draw(client):
    tagged_request(client)

    d = client.get("/resume/stats", headers=hdr(client, STAFF)).json()

    assert len(d["trend"]) == 14 and sum(p["count"] for p in d["trend"]) == 1
    assert d["top_jds"] == [{"title": d["top_jds"][0]["title"], "total": 1, "approved": 0}]
    assert d["avg_days_to_approve"] is None and d["completion_rate"] == 0.0 and d["attention"] == []
    assert set(d["by_status"]) == {"requested", "in_progress", "submitted", "changes_requested", "approved", "cancelled"}


def test_stats_are_closed_while_the_rmg_module_is_off(client, api_db):
    api_db.execute("INSERT OR REPLACE INTO platform_modules (module, enabled) VALUES ('rmg', 0)")
    api_db.commit()

    assert client.get("/resume/stats", headers=hdr(client, RAVI)).status_code == 403

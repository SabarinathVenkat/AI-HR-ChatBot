"""Whatever goes wrong in the resume builder leaves a line in the issue log, with enough to trace it.

Each test makes the thing go wrong the way a user would (a bad upload, a model that fails, a template that cannot be
used) and then reads the log file, as the person investigating would.
"""
import logging
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.issue_log import configure
from app.rmg.resume.chat import EditCommand
from app.rmg.resume.demo import seed_resume_demo
from app.rmg.resume.draft import TailoringSettings
from app.rmg.resume.extract import ExtractionError
from app.rmg.resume.filestore import FileStore
from app.rmg.resume.pipeline import PipelineDeps
from app.rmg.resume.service import ResumeEngine
from tests.integration.conftest import SECRET
from tests.integration.test_api_resume import HEAD, RAVI, STAFF, hdr, tagged_request, template_bytes
from tests.unit.resume_fakes import FakeJDExtractor, FakeResumeExtractor, keep_as_written
from tests.unit.resume_templates import make_template


@pytest.fixture
def log_file(tmp_path):
    path = configure(tmp_path / "logs" / "resume_builder.log")
    yield path
    logger = logging.getLogger("resume.issues")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


@pytest.fixture
def make(api_db, clock, tmp_path, argon_hash):
    def build(extractor=None):
        seed_resume_demo(api_db, hash_password=lambda p: argon_hash)
        engine = ResumeEngine(PipelineDeps(extractor or FakeResumeExtractor(), FakeJDExtractor(), keep_as_written, TailoringSettings()),
                              lambda message, resume: EditCommand(action="remove", path="projects.0.bullets.0", reply="Removed."))
        app = create_app(Settings(jwt_secret=SECRET), connection=lambda: nullcontext(api_db), clock=clock,
                         resume_engine=engine, resume_files=FileStore(tmp_path / "files"))
        return TestClient(app, raise_server_exceptions=False)

    return build


def text(log_file):
    return log_file.read_text(encoding="utf-8")


def lines_with(log_file, word):
    return [line for line in text(log_file).splitlines() if word in line]


def test_a_rejected_upload_is_logged_with_who_what_and_why(make, log_file):
    client = make()
    request_id = tagged_request(client)

    reply = client.post(f"/resume/requests/{request_id}/resume?filename=cv.docx", content=b"", headers=hdr(client, RAVI))

    assert reply.status_code == 422
    line = lines_with(log_file, "request_rejected")[-1]
    assert "WARNING" in line and 'user="Ravi Kumar"' in line and "code=empty" in line and "status=422" in line
    assert f"path=/resume/requests/{request_id}/resume" in line and f"trace={reply.headers['X-Trace-Id']}" in line


def test_a_file_the_reader_cannot_open_is_logged_with_its_name_and_size(make, log_file):
    client = make()
    request_id = tagged_request(client)

    client.post(f"/resume/requests/{request_id}/resume?filename=My%20CV.docx", content=b"this is not a word file", headers=hdr(client, RAVI))

    line = lines_with(log_file, "upload_failed")[-1]
    assert 'filename="My CV.docx"' in line and "size=23" in line and f"request_id={request_id}" in line and "code=" in line


def test_a_build_that_fails_in_a_known_way_is_logged_with_the_stage_and_code(make, log_file):
    client = make(FakeResumeExtractor(error=ExtractionError("incomplete")))
    request_id = tagged_request(client)
    client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=b"Ravi Kumar backend engineer", headers=hdr(client, RAVI))

    reply = client.post(f"/resume/requests/{request_id}/build", headers=hdr(client, RAVI))

    assert reply.status_code == 422
    line = lines_with(log_file, "build_failed")[-1]
    assert "ERROR" in line and f"request_id={request_id}" in line and "stage=resume" in line and "code=incomplete" in line
    assert 'user="Ravi Kumar"' in line and "filename=cv.txt" in line and "duration_ms=" in line


def test_a_build_that_crashes_is_logged_with_the_full_traceback_and_the_user_gets_a_trace_id(make, log_file):
    client = make(FakeResumeExtractor(error=RuntimeError("model service unreachable")))
    request_id = tagged_request(client)
    client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=b"Ravi Kumar", headers=hdr(client, RAVI))

    reply = client.post(f"/resume/requests/{request_id}/build", headers=hdr(client, RAVI))

    assert reply.status_code == 500 and reply.json()["error"]["trace_id"] == reply.headers["X-Trace-Id"]
    log = text(log_file)
    assert "build_crashed" in log and "error_type=RuntimeError" in log and "model service unreachable" in log and "Traceback" in log
    assert f"trace={reply.headers['X-Trace-Id']}" in log
    assert "model service unreachable" not in reply.text  # the user is not shown internals


def test_a_good_build_is_logged_with_how_long_it_took_and_what_was_found(make, log_file):
    client = make()
    request_id = tagged_request(client)
    client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=b"Ravi Kumar backend engineer", headers=hdr(client, RAVI))

    assert client.post(f"/resume/requests/{request_id}/build", headers=hdr(client, RAVI)).status_code == 200

    log = text(log_file)
    assert "build_started" in log and "build_succeeded" in log
    line = lines_with(log_file, "build_succeeded")[-1]
    assert "INFO" in line and f"request_id={request_id}" in line and "duration_ms=" in line and "warnings=" in line and "read_coverage=" in line


def test_a_template_the_builder_cannot_use_is_logged_when_uploaded_and_when_a_resume_falls_back_to_the_standard_layout(make, log_file):
    client = make()
    bad = make_template(omit_projects=True)
    import io

    buf = io.BytesIO()
    bad.save(buf)
    assert client.post("/resume/template?filename=broken.docx", content=buf.getvalue(), headers=hdr(client, HEAD)).status_code == 200
    jd_id = client.get("/resume/jds", headers=hdr(client, STAFF)).json()["jds"][0]["id"]
    ravi_id = next(a["id"] for a in client.get("/resume/associates", headers=hdr(client, STAFF)).json()["associates"] if a["name"] == RAVI)
    request_id = client.post(f"/resume/jds/{jd_id}/tag", json={"associate_ids": [ravi_id]}, headers=hdr(client, STAFF)).json()["created"][0]["request_id"]
    client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=b"Ravi Kumar", headers=hdr(client, RAVI))
    client.post(f"/resume/requests/{request_id}/build", headers=hdr(client, RAVI))
    client.get(f"/resume/requests/{request_id}/download", headers=hdr(client, STAFF))

    assert "template_unusable" in text(log_file) and "broken.docx" in text(log_file)
    assert "render_fallback" in text(log_file) and "standard layout" in text(log_file)


def test_access_that_is_refused_is_logged_so_misuse_can_be_seen(make, log_file):
    client = make()
    request_id = tagged_request(client)

    reply = client.get(f"/resume/requests/{request_id}/download", headers=hdr(client, "Divya Menon"))

    assert reply.status_code in (403, 404)
    assert "request_rejected" in text(log_file) and 'user="Divya Menon"' in text(log_file)


def test_the_log_never_contains_the_resume_text(make, log_file):
    client = make()
    request_id = tagged_request(client)
    secret = b"My secret salary is 123456 rupees and my passport number is Z1234567"
    client.post(f"/resume/requests/{request_id}/resume?filename=cv.txt", content=secret, headers=hdr(client, RAVI))
    client.post(f"/resume/requests/{request_id}/build", headers=hdr(client, RAVI))

    assert "salary" not in text(log_file) and "Z1234567" not in text(log_file)


def test_the_template_bytes_helper_is_still_valid_for_these_tests():
    assert template_bytes()

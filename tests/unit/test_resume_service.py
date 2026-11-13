"""The resume-builder workflow: who may do what, and how a request moves through its statuses.

Models are fakes, the database is in memory, files go to a temporary directory.
"""
import io
from datetime import datetime, timezone

import pytest
from docx import Document

from app.db import repositories as repo
from app.db.seed import email_for
from app.rmg.resume.demo import seed_resume_demo
from app.rmg.resume.draft import TailoringSettings
from app.rmg.resume.extract import ExtractionError
from app.rmg.resume.filestore import FileStore
from app.rmg.resume.people import assign_role
from app.rmg.resume.pipeline import PipelineDeps
from app.rmg.resume.service import ResumeEngine, ResumeService, ServiceError
from tests.unit.resume_fakes import FakeJDExtractor, FakeResumeExtractor, keep_as_written
from tests.unit.resume_templates import make_template

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)


def template_bytes(**kw) -> bytes:
    buf = io.BytesIO()
    make_template(**kw).save(buf)
    return buf.getvalue()


class World:
    def __init__(self, db, files, engine):
        self.db, self.files, self.engine = db, files, engine

    def as_(self, name: str) -> ResumeService:
        row = self.db.execute("SELECT id FROM employees WHERE email = ?", (email_for(name),)).fetchone()
        return ResumeService(self.db, self.files, self.engine, lambda: NOW, repo.get_employee(self.db, row["id"]))

    def id_of(self, name: str) -> int:
        return self.db.execute("SELECT id FROM employees WHERE email = ?", (email_for(name),)).fetchone()["id"]


@pytest.fixture
def world(db, tmp_path):
    seed_resume_demo(db, hash_password=lambda p: "h")
    engine = ResumeEngine(PipelineDeps(FakeResumeExtractor(), FakeJDExtractor(), keep_as_written, TailoringSettings()))
    return World(db, FileStore(tmp_path / "files"), engine)


HEAD, STAFF, LEAD, RAVI, DIVYA, SANJAY = "Nancy", "Shadrach", "Veera", "Ravi Kumar", "Divya Menon", "Sanjay Patel"


@pytest.fixture
def ready(world):
    """A template is active and RMG has tagged Ravi (mapped to the lead) for the demo job description."""
    world.as_(HEAD).upload_template("template.docx", template_bytes())
    jd_id = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]
    request_id = world.as_(STAFF).tag(jd_id, [world.id_of(RAVI)])["created"][0]["request_id"]
    world.request_id, world.jd_id = request_id, jd_id
    return world


def built(world):
    ravi = world.as_(RAVI)
    ravi.upload_resume(world.request_id, "cv.txt", b"Ravi Kumar, backend engineer")
    ravi.build(world.request_id)
    return ravi


def submitted(world):
    ravi = built(world)
    ravi.submit(world.request_id)
    return ravi


def code_of(excinfo) -> str:
    return excinfo.value.code


# --- template and Lead mapping (RMG head) --------------------------------------------------------------

def test_only_the_rmg_head_can_upload_a_template(world):
    with pytest.raises(ServiceError) as e:
        world.as_(STAFF).upload_template("t.docx", template_bytes())
    assert (code_of(e), e.value.status) == ("forbidden", 403)


def test_a_new_template_becomes_active_and_the_old_one_is_archived(world):
    head = world.as_(HEAD)
    first = head.upload_template("one.docx", template_bytes())
    second = head.upload_template("two.docx", template_bytes())

    rows = world.db.execute("SELECT id, status FROM resume_templates ORDER BY id").fetchall()
    assert [(r["id"], r["status"]) for r in rows] == [(first["id"], "archived"), (second["id"], "active")]


def test_a_template_with_missing_slots_is_accepted_with_a_warning_that_the_standard_layout_will_be_used(world):
    result = world.as_(HEAD).upload_template("t.docx", template_bytes(omit_projects=True))

    assert result["status"] == "active" and "projects" in result["warning"] and "standard layout" in result["warning"]


def test_a_complete_template_is_accepted_without_a_warning(world):
    assert "warning" not in world.as_(HEAD).upload_template("t.docx", template_bytes())


@pytest.mark.parametrize("name,data", [("t.pdf", b"%PDF-1.4 x"), ("t.docx", b"not a zip"), ("t.exe", b"x")])
def test_a_template_that_is_not_a_real_docx_is_refused(world, name, data):
    with pytest.raises(ServiceError) as e:
        world.as_(HEAD).upload_template(name, data)
    assert e.value.status == 422


def test_the_head_maps_an_associate_to_a_lead_and_others_cannot(world):
    world.as_(HEAD).set_lead(world.id_of(SANJAY), world.id_of(LEAD))

    assert world.as_(HEAD).list_leads()["assignments"]
    with pytest.raises(ServiceError):
        world.as_(STAFF).set_lead(world.id_of(SANJAY), world.id_of(LEAD))
    with pytest.raises(ServiceError) as e:
        world.as_(HEAD).set_lead(world.id_of(SANJAY), world.id_of(DIVYA))
    assert code_of(e) == "not_a_lead"


# --- job descriptions and tagging (RMG) ------------------------------------------------------------------

def test_rmg_adds_a_job_description_that_is_read_and_stored_once(world):
    jd = world.as_(STAFF).create_jd("jd.txt", b"We need a Java developer")

    assert jd["roles"][0]["title"] == "Java Developer" and jd["id"]


def test_an_associate_cannot_add_a_job_description_and_a_bad_file_gets_a_friendly_error(world):
    with pytest.raises(ServiceError) as e:
        world.as_(RAVI).create_jd("jd.txt", b"x")
    assert code_of(e) == "forbidden"
    with pytest.raises(ServiceError) as e:
        world.as_(STAFF).create_jd("jd.exe", b"x")
    assert (code_of(e), e.value.status) == ("unsupported_type", 422)


def test_a_jd_the_model_cannot_read_is_a_friendly_error(world):
    engine = ResumeEngine(PipelineDeps(FakeResumeExtractor(), FakeJDExtractor(error=ExtractionError("no_roles")),
                                       keep_as_written, TailoringSettings()))
    broken = World(world.db, world.files, engine)

    with pytest.raises(ServiceError) as e:
        broken.as_(STAFF).create_jd("jd.txt", b"nothing useful")
    assert code_of(e) == "no_roles"


def test_tagging_creates_a_request_for_each_associate_and_tells_them(world):
    jd_id = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]

    result = world.as_(STAFF).tag(jd_id, [world.id_of(RAVI), world.id_of(DIVYA)])

    assert len(result["created"]) == 2 and result["skipped"] == []
    assert "prepare a resume" in world.as_(DIVYA).notifications()[0]["message"]


def test_an_associate_with_no_lead_is_skipped_with_an_explanation(world):
    jd_id = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]

    result = world.as_(STAFF).tag(jd_id, [world.id_of(SANJAY), world.id_of(RAVI)])

    assert [c["associate_id"] for c in result["created"]] == [world.id_of(RAVI)]
    assert result["skipped"][0]["reason"] == "no_lead" and "Competency Lead" in result["skipped"][0]["message"]


def test_tagging_the_same_person_twice_is_skipped(world):
    jd_id = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]
    world.as_(STAFF).tag(jd_id, [world.id_of(RAVI)])

    assert world.as_(STAFF).tag(jd_id, [world.id_of(RAVI)])["skipped"][0]["reason"] == "already_tagged"


def test_tagging_needs_rmg_a_real_jd_and_a_real_role(world):
    jd_id = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]
    with pytest.raises(ServiceError) as e:
        world.as_(RAVI).tag(jd_id, [world.id_of(DIVYA)])
    assert code_of(e) == "forbidden"
    with pytest.raises(ServiceError) as e:
        world.as_(STAFF).tag(999, [world.id_of(RAVI)])
    assert e.value.status == 404
    with pytest.raises(ServiceError) as e:
        world.as_(STAFF).tag(jd_id, [world.id_of(RAVI)], role_index=5)
    assert code_of(e) == "no_such_role"


# --- who can see a request --------------------------------------------------------------------------------

def test_a_request_is_visible_to_its_associate_lead_and_rmg_and_hidden_from_everyone_else(ready):
    for who in (RAVI, LEAD, STAFF, HEAD):
        assert ready.as_(who).detail(ready.request_id)["id"] == ready.request_id
    for outsider in (DIVYA, SANJAY):
        with pytest.raises(ServiceError) as e:
            ready.as_(outsider).detail(ready.request_id)
        assert e.value.status == 404  # existence is not revealed


def test_each_role_sees_its_own_list(ready):
    assert [r["id"] for r in ready.as_(RAVI).summaries("mine")] == [ready.request_id]
    assert ready.as_(DIVYA).summaries("mine") == []
    assert [r["id"] for r in ready.as_(LEAD).summaries("lead")] == [ready.request_id]
    assert [r["id"] for r in ready.as_(STAFF).summaries("board")] == [ready.request_id]
    with pytest.raises(ServiceError):
        ready.as_(RAVI).summaries("board")
    with pytest.raises(ServiceError):
        ready.as_(RAVI).summaries("lead")


# --- the associate builds -----------------------------------------------------------------------------------

def test_only_the_associate_can_upload_and_a_bad_file_is_refused(ready):
    with pytest.raises(ServiceError) as e:
        ready.as_(STAFF).upload_resume(ready.request_id, "cv.txt", b"x")
    assert code_of(e) == "forbidden"
    with pytest.raises(ServiceError) as e:
        ready.as_(RAVI).upload_resume(ready.request_id, "cv.exe", b"x")
    assert (code_of(e), e.value.status) == ("unsupported_type", 422)


def test_building_needs_an_uploaded_resume_and_a_template(world):
    jd_id = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]
    request_id = world.as_(STAFF).tag(jd_id, [world.id_of(RAVI)])["created"][0]["request_id"]
    with pytest.raises(ServiceError) as e:
        world.as_(RAVI).build(request_id)
    assert code_of(e) == "no_resume"
    world.as_(RAVI).upload_resume(request_id, "cv.txt", b"Ravi")
    with pytest.raises(ServiceError) as e:
        world.as_(RAVI).build(request_id)
    assert code_of(e) == "no_template"


def test_building_makes_a_draft_with_a_change_log_and_moves_the_request_on(ready):
    view = built(ready).detail(ready.request_id)

    assert view["status"] == "in_progress" and view["resume"]["name"] == "Anil Verma"
    assert list(view["changelog"]["coverage"]["missing_required"]) == ["Spring Boot", "REST"] and view["years_text"]
    assert view["can"]["submit"] and view["can"]["edit"] and not view["can"]["decide"]


def test_a_second_build_is_refused_unless_forced_so_edits_are_not_lost_by_accident(ready):
    ravi = built(ready)

    with pytest.raises(ServiceError) as e:
        ravi.build(ready.request_id)
    assert code_of(e) == "already_built"
    assert ravi.build(ready.request_id, force=True)["status"] == "in_progress"


def test_a_pipeline_failure_becomes_a_friendly_error_and_changes_nothing(ready):
    engine = ResumeEngine(PipelineDeps(FakeResumeExtractor(error=ExtractionError("truncated")), FakeJDExtractor(),
                                       keep_as_written, TailoringSettings()))
    failing = World(ready.db, ready.files, engine)
    failing.request_id = ready.request_id
    failing.as_(RAVI).upload_resume(ready.request_id, "cv.txt", b"Ravi")

    with pytest.raises(ServiceError) as e:
        failing.as_(RAVI).build(ready.request_id)

    assert e.value.status == 422 and "too long" in str(e.value)
    assert ready.as_(RAVI).detail(ready.request_id)["status"] == "requested"


# --- save, submit, decide -------------------------------------------------------------------------------------

def test_saving_makes_numbered_versions(ready):
    ravi = built(ready)

    assert ravi.save(ready.request_id)["version"] == 1 and ravi.save(ready.request_id)["version"] == 2
    assert [v["kind"] for v in ravi.detail(ready.request_id)["versions"]] == ["saved", "saved"]


def test_submitting_needs_a_draft_and_then_locks_editing_and_tells_the_lead(ready):
    with pytest.raises(ServiceError) as e:
        ready.as_(RAVI).submit(ready.request_id)
    assert code_of(e) in ("wrong_status", "no_draft")

    ravi = submitted(ready)

    assert ravi.detail(ready.request_id)["status"] == "submitted" and not ravi.detail(ready.request_id)["can"]["edit"]
    assert "waiting for your review" in ready.as_(LEAD).notifications()[0]["message"]
    assert "submitted a resume" in ready.as_(STAFF).notifications()[0]["message"]
    with pytest.raises(ServiceError) as e:
        ravi.save(ready.request_id)
    assert code_of(e) == "wrong_status"


def test_only_the_associate_submits(ready):
    built(ready)

    with pytest.raises(ServiceError) as e:
        ready.as_(STAFF).submit(ready.request_id)
    assert code_of(e) == "forbidden"


def test_only_the_mapped_lead_decides_and_only_when_it_is_submitted(ready):
    assign_role(ready.db, ready.id_of("Arjun Rao"), "competency_lead")
    with pytest.raises(ServiceError) as e:
        ready.as_(LEAD).decide(ready.request_id, "approve")
    assert code_of(e) == "wrong_status"
    submitted(ready)

    for outsider in ("Arjun Rao", RAVI, STAFF):
        with pytest.raises(ServiceError) as e:
            ready.as_(outsider).decide(ready.request_id, "approve")
        assert e.value.status in (403, 404)

    assert ready.as_(LEAD).decide(ready.request_id, "approve")["status"] == "approved"


def test_approving_makes_an_approved_version_and_tells_the_associate_and_rmg(ready):
    submitted(ready)

    ready.as_(LEAD).decide(ready.request_id, "approve", "Looks good")

    detail = ready.as_(RAVI).detail(ready.request_id)
    assert detail["status"] == "approved" and [v["kind"] for v in detail["versions"]] == ["submitted", "approved"]
    assert "approved" in ready.as_(RAVI).notifications()[0]["message"]
    assert "approved" in ready.as_(STAFF).notifications()[0]["message"]


def test_sending_back_needs_a_note_and_reopens_editing_for_the_associate(ready):
    ravi = submitted(ready)
    with pytest.raises(ServiceError) as e:
        ready.as_(LEAD).decide(ready.request_id, "send_back", "  ")
    assert code_of(e) == "note_required"

    ready.as_(LEAD).decide(ready.request_id, "send_back", "Please add more on Kafka")

    detail = ravi.detail(ready.request_id)
    assert detail["status"] == "changes_requested" and detail["decision_note"] == "Please add more on Kafka"
    assert detail["can"]["edit"] and "Kafka" in ravi.notifications()[0]["message"]
    ravi.save(ready.request_id)
    assert ravi.detail(ready.request_id)["status"] == "in_progress"


def test_an_unknown_decision_is_refused(ready):
    submitted(ready)

    with pytest.raises(ServiceError) as e:
        ready.as_(LEAD).decide(ready.request_id, "maybe")
    assert code_of(e) == "bad_decision"


def test_after_approval_the_associate_can_reopen_and_the_next_save_is_a_new_version(ready):
    ravi = submitted(ready)
    with pytest.raises(ServiceError):
        ravi.reopen(ready.request_id)  # not approved yet
    ready.as_(LEAD).decide(ready.request_id, "approve")

    ravi.reopen(ready.request_id)

    assert ravi.detail(ready.request_id)["status"] == "in_progress"
    assert ravi.save(ready.request_id)["version"] == 3  # submitted, approved, then this one


# --- download -------------------------------------------------------------------------------------------------------

def header(data: bytes) -> str:
    return " ".join(p.text for s in Document(io.BytesIO(data)).sections for p in s.header.paragraphs)


def test_an_unapproved_download_says_draft_in_its_file_name_and_not_inside_the_document(ready):
    built(ready)

    name, data, is_draft = ready.as_(STAFF).download(ready.request_id)

    assert is_draft and name.endswith("_DRAFT.docx") and "DRAFT" not in header(data)


def test_an_approved_download_says_final_in_its_file_name_and_has_no_mark_inside(ready):
    submitted(ready)
    ready.as_(LEAD).decide(ready.request_id, "approve")

    name, data, is_draft = ready.as_(STAFF).download(ready.request_id)

    assert not is_draft and name.endswith("_FINAL.docx") and "DRAFT" not in name and "DRAFT" not in header(data)


def test_the_associate_lead_and_rmg_can_download_and_nobody_else(ready):
    built(ready)

    for who in (RAVI, LEAD, STAFF, HEAD):
        assert ready.as_(who).download(ready.request_id)[1][:2] == b"PK"
    with pytest.raises(ServiceError) as e:
        ready.as_(DIVYA).download(ready.request_id)
    assert e.value.status == 404


def test_downloading_before_anything_is_built_is_a_clear_error(ready):
    with pytest.raises(ServiceError) as e:
        ready.as_(STAFF).download(ready.request_id)
    assert code_of(e) == "no_draft"


def test_a_filename_cannot_carry_path_characters_from_names_or_titles(ready):
    ready.db.execute("UPDATE job_descriptions SET title = ?", ("../../evil title",))
    built(ready)

    name, _, _ = ready.as_(STAFF).download(ready.request_id)

    assert "/" not in name and ".." not in name.replace("_DRAFT.docx", "")


# --- cancel, notifications, audit -----------------------------------------------------------------------------------

def test_rmg_can_cancel_a_request_but_not_an_approved_one(ready):
    submitted(ready)
    ready.as_(LEAD).decide(ready.request_id, "approve")
    with pytest.raises(ServiceError) as e:
        ready.as_(STAFF).cancel(ready.request_id)
    assert code_of(e) == "wrong_status"


def test_cancelling_stops_the_associate_and_tells_them(ready):
    ready.as_(STAFF).cancel(ready.request_id)

    assert ready.as_(RAVI).detail(ready.request_id)["status"] == "cancelled"
    with pytest.raises(ServiceError):
        ready.as_(RAVI).upload_resume(ready.request_id, "cv.txt", b"x")
    assert "cancelled" in ready.as_(RAVI).notifications()[0]["message"]


def test_associates_cannot_cancel(ready):
    with pytest.raises(ServiceError) as e:
        ready.as_(RAVI).cancel(ready.request_id)
    assert code_of(e) == "forbidden"


def test_notifications_can_be_marked_read_and_only_by_their_owner(ready):
    ravi, divya = ready.as_(RAVI), ready.as_(DIVYA)
    note_id = ravi.notifications()[0]["id"]

    divya.mark_read([note_id])
    assert len(ravi.notifications(unread_only=True)) == 1
    ravi.mark_read([note_id])

    assert ravi.notifications(unread_only=True) == []


def test_important_steps_are_written_to_the_audit_log(ready):
    submitted(ready)
    ready.as_(LEAD).decide(ready.request_id, "approve")

    actions = [r["action"] for r in ready.db.execute("SELECT action FROM audit_log WHERE tool = 'resume' ORDER BY id")]

    for expected in ("template_uploaded", "tagged", "resume_built", "resume_submitted", "resume_decided"):
        assert expected in actions

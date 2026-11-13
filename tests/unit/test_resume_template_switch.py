"""Replacing the resume template, checked step by step with real files.

Template A and template B are both complete, but look different: B has other heading names, so any document can be
told apart by its headings. The steps follow what really happens when RMG changes the template while work is under way.
"""
import io

import pytest
from docx import Document

from app.rmg.resume.service import ServiceError
from app.rmg.resume.template import W, paragraph_text
from tests.unit.resume_templates import make_template
from tests.unit.test_resume_ingest import blank_pdf, with_extra_entry
from tests.unit.test_resume_service import HEAD, LEAD, RAVI, STAFF, built, ready, template_bytes, world  # noqa: F401  (fixtures)

B = dict(skills_heading="TECHNICAL SKILLS", highlights_heading="PROFILE HIGHLIGHTS", projects_heading="PROJECT EXPERIENCE")


def headings(data: bytes) -> set[str]:
    doc = Document(io.BytesIO(data))
    return {paragraph_text(p) for p in doc.element.body.iter(W + "p")}


def is_a(data: bytes) -> bool:
    return "SKILLS" in headings(data) and "TECHNICAL SKILLS" not in headings(data)


def is_b(data: bytes) -> bool:
    return "TECHNICAL SKILLS" in headings(data) and "PROJECT EXPERIENCE" in headings(data)


def active_name(world_) -> str:
    return world_.db.execute("SELECT filename FROM resume_templates WHERE status = 'active'").fetchone()["filename"]


def test_step_by_step_what_happens_when_the_template_is_replaced(ready):  # noqa: F811
    # Step 1: only the RMG Head may upload. RMG staff are refused, and nothing changes.
    with pytest.raises(ServiceError) as refused:
        ready.as_(STAFF).upload_template("staff.docx", template_bytes(**B))
    assert (refused.value.code, refused.value.status) == ("forbidden", 403)
    assert active_name(ready) == "template.docx"  # template A, uploaded by the Head in the fixture

    # Step 2: a draft is built with template A.
    ravi = built(ready)
    assert is_a(ravi.download(ready.request_id)[1])

    # Step 3: the Head uploads template B. It becomes active and A is archived, not deleted.
    ready.as_(HEAD).upload_template("b.docx", template_bytes(**B))
    statuses = [(r["filename"], r["status"]) for r in ready.db.execute("SELECT filename, status FROM resume_templates ORDER BY id")]
    assert statuses == [("template.docx", "archived"), ("b.docx", "active")]

    # Step 4: the draft that already exists still downloads in A. Nothing changes under a person's feet.
    assert is_a(ravi.download(ready.request_id)[1])

    # Step 5: rebuilding picks up the new template, and the associate's edits are replaced by the rebuild.
    ravi.build(ready.request_id, force=True)
    assert is_b(ravi.download(ready.request_id)[1])

    # Step 6: submit and approve. The approved download is in B.
    ravi.submit(ready.request_id)
    ready.as_(LEAD).decide(ready.request_id, "approve")
    name, data, is_draft = ready.as_(STAFF).download(ready.request_id)
    assert not is_draft and is_b(data)

    # Step 7: the Head uploads a third template. The approved resume does not change.
    ready.as_(HEAD).upload_template("c.docx", template_bytes())
    assert active_name(ready) == "c.docx"
    assert is_b(ready.as_(STAFF).download(ready.request_id)[1])

    # Step 8: reopening keeps the template the work was built with until the associate rebuilds.
    ravi.reopen(ready.request_id)
    assert is_b(ravi.download(ready.request_id)[1])
    ravi.build(ready.request_id, force=True)
    assert is_a(ravi.download(ready.request_id)[1])  # c.docx has template A's headings


@pytest.mark.parametrize("name,data,code", [
    ("macro.docx", with_extra_entry(template_bytes(), "word/vbaProject.bin", b"macro"), "macros_not_allowed"),
    ("fake.docx", b"this is not a docx", "type_mismatch"),
    ("real.pdf", blank_pdf(), "unsupported_type"),  # a genuine PDF is the wrong kind of file for a template
    ("broken.pdf", b"%PDF-1.4 not a template", "corrupt"),
    ("run.exe", b"MZ", "unsupported_type"),
], ids=["macros", "not-really-a-docx", "real-pdf", "broken-pdf", "exe"])
def test_a_template_that_cannot_be_used_is_refused_and_the_active_template_is_unchanged(ready, name, data, code):  # noqa: F811
    before = ready.db.execute("SELECT id FROM resume_templates WHERE status = 'active'").fetchone()["id"]

    with pytest.raises(ServiceError) as e:
        ready.as_(HEAD).upload_template(name, data)

    assert e.value.code == code and e.value.status == 422
    after = ready.db.execute("SELECT id FROM resume_templates WHERE status = 'active'").fetchone()["id"]
    assert after == before
    assert ready.db.execute("SELECT count(*) FROM resume_templates").fetchone()[0] == 1  # nothing was stored


def test_an_incomplete_template_names_what_is_missing_in_its_warning(ready):  # noqa: F811
    result = ready.as_(HEAD).upload_template("noprojects.docx", template_bytes(omit_projects=True))

    assert "projects" in result["warning"]


def test_building_without_any_template_is_a_clear_error(world):  # noqa: F811
    jd_id = world.db.execute("SELECT id FROM job_descriptions").fetchone()["id"]
    request_id = world.as_(STAFF).tag(jd_id, [world.id_of(RAVI)])["created"][0]["request_id"]
    world.as_(RAVI).upload_resume(request_id, "cv.txt", b"Ravi")

    with pytest.raises(ServiceError) as e:
        world.as_(RAVI).build(request_id)

    assert e.value.code == "no_template"


def test_the_template_in_use_is_visible_to_rmg_but_not_to_associates(ready):  # noqa: F811
    assert ready.as_(STAFF).template_info()["filename"] == "template.docx"
    assert ready.as_(HEAD).template_info()["filename"] == "template.docx"
    with pytest.raises(ServiceError):
        ready.as_(RAVI).template_info()


def test_the_template_upload_is_audited(ready):  # noqa: F811
    ready.as_(HEAD).upload_template("b.docx", template_bytes(**B))

    uploads = ready.db.execute("SELECT count(*) FROM audit_log WHERE action = 'template_uploaded'").fetchone()[0]
    assert uploads == 2  # the fixture's first upload and this one
    assert make_template is not None

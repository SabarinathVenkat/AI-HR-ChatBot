"""Downloading the job description: the original file is kept, and anyone with a part in a request can get it.

When no original file exists (the seeded demo JD, or a file that has gone missing) a Word file is made from the stored
requirements instead, so the button always works.
"""
import io
import sqlite3

import pytest
from docx import Document

from app.db.connection import init_schema
from app.rmg.resume.jd import JobDescription, Role, jd_to_docx
from app.rmg.resume.service import ServiceError
from tests.unit.test_resume_service import DIVYA, LEAD, RAVI, STAFF, ready, world  # noqa: F401  (fixtures)

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def jd_id_of(world_):
    return world_.db.execute("SELECT id FROM job_descriptions ORDER BY id DESC").fetchone()["id"]


def docx_text(data: bytes) -> str:
    return "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)


# --- the original file is kept ---------------------------------------------------------------------------------

def test_the_original_job_description_file_is_kept_and_comes_back_unchanged(world):  # noqa: F811
    original = b"We need a Java developer with Kafka experience."
    created = world.as_(STAFF).create_jd("opening.txt", original, title="Platform Engineer")

    name, data, media_type = world.as_(STAFF).jd_file(created["id"])

    assert data == original and name == "Platform_Engineer.txt" and media_type.startswith("text/plain")


def test_a_word_job_description_keeps_its_type(world):  # noqa: F811
    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph("Senior Java Developer needed.")
    doc.save(buf)
    created = world.as_(STAFF).create_jd("jd.docx", buf.getvalue())

    name, data, media_type = world.as_(STAFF).jd_file(created["id"])

    assert name.endswith(".docx") and media_type == DOCX_TYPE and data == buf.getvalue()


# --- who may download ---------------------------------------------------------------------------------------------

def test_the_associate_the_lead_and_rmg_can_download_the_jd_of_their_request(ready):  # noqa: F811
    for who in (RAVI, LEAD, STAFF):
        name, data, _ = ready.as_(who).download_jd(ready.request_id)
        assert data and name.endswith(".docx")


def test_someone_with_no_part_in_the_request_gets_not_found(ready):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        ready.as_(DIVYA).download_jd(ready.request_id)
    assert e.value.status == 404


def test_the_jd_list_download_by_id_is_for_rmg_only(ready):  # noqa: F811
    assert ready.as_(STAFF).jd_file(jd_id_of(ready))[1]
    with pytest.raises(ServiceError) as e:
        ready.as_(RAVI).jd_file(jd_id_of(ready))
    assert e.value.status == 403


# --- when there is no original file -------------------------------------------------------------------------------

def test_a_job_description_with_no_stored_file_is_made_from_its_requirements(ready):  # noqa: F811
    name, data, media_type = ready.as_(STAFF).download_jd(ready.request_id)

    text = docx_text(data)
    assert media_type == DOCX_TYPE and "Senior Java Developer" in text
    for skill in ("Java", "Spring Boot", "Kafka", "Kubernetes"):
        assert skill in text


def test_a_stored_file_that_has_gone_missing_falls_back_to_the_requirements(world):  # noqa: F811
    created = world.as_(STAFF).create_jd("opening.txt", b"We need a Java developer.")
    key = world.db.execute("SELECT file_key FROM job_descriptions WHERE id = ?", (created["id"],)).fetchone()["file_key"]
    world.files.delete(key)

    name, data, media_type = world.as_(STAFF).jd_file(created["id"])

    assert media_type == DOCX_TYPE and "Java Developer" in docx_text(data)


def test_the_file_name_cannot_carry_path_characters_from_the_title(world):  # noqa: F811
    created = world.as_(STAFF).create_jd("opening.txt", b"We need a Java developer.", title="../../evil name")

    name, _, _ = world.as_(STAFF).jd_file(created["id"])

    assert "/" not in name and "\\" not in name and ".." not in name.replace(".txt", "")


def test_downloading_is_audited(ready):  # noqa: F811
    ready.as_(RAVI).download_jd(ready.request_id)

    actions = [r["action"] for r in ready.db.execute("SELECT action FROM audit_log WHERE tool = 'resume'")]
    assert "jd_downloaded" in actions


# --- the generated document and the database upgrade --------------------------------------------------------------

def test_the_generated_document_lists_role_years_domain_and_both_skill_lists():
    jd = JobDescription(roles=[Role(title="QA Lead", min_years=7, domain="Healthcare", must_have=["Selenium", "Python"],
                                    nice_to_have=["Cypress"])], flagged=[])

    text = docx_text(jd_to_docx("QA Lead opening", jd))

    for part in ("QA Lead opening", "QA Lead", "7", "Healthcare", "Selenium", "Python", "Cypress"):
        assert part in text


def test_an_older_database_without_the_file_column_is_upgraded_and_keeps_its_rows():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE employees (id INTEGER PRIMARY KEY);
        CREATE TABLE job_descriptions (id INTEGER PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
            jd_json TEXT NOT NULL, created_by INTEGER NOT NULL, created_at TEXT NOT NULL);
        INSERT INTO job_descriptions VALUES (1, 'Old JD', 'old.txt', '{}', 1, '2026-01-01');
    """)

    from app.db import connection
    connection.upgrade_schema(conn)
    connection.upgrade_schema(conn)  # running it again is harmless

    row = conn.execute("SELECT title, file_key FROM job_descriptions WHERE id = 1").fetchone()
    assert row["title"] == "Old JD" and row["file_key"] is None
    assert init_schema is not None


# --- a job description pasted as text (it can be just a list of skills) ----------------------------------------------

def test_a_pasted_job_description_is_read_stored_and_can_be_downloaded_as_the_text_that_was_pasted(world):  # noqa: F811
    pasted = "Java, Spring Boot, Kafka, SQL"

    created = world.as_(STAFF).create_jd_from_text(pasted, title="Skills for the payments team")

    assert created["title"] == "Skills for the payments team" and created["id"]
    name, data, media_type = world.as_(STAFF).jd_file(created["id"])
    assert data == pasted.encode() and name.endswith(".txt") and media_type.startswith("text/plain")


def test_pasted_text_is_trimmed_and_blank_text_is_refused_with_a_clear_message(world):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        world.as_(STAFF).create_jd_from_text("   \n  ")
    assert (e.value.code, e.value.status) == ("empty", 422) and "Paste" in str(e.value)

    created = world.as_(STAFF).create_jd_from_text("  \n We need a Java developer.  \n ")
    assert world.as_(STAFF).jd_file(created["id"])[1] == b"We need a Java developer."


def test_only_rmg_can_paste_a_job_description_and_a_huge_paste_is_refused(world):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        world.as_(RAVI).create_jd_from_text("Java, Kafka")
    assert e.value.code == "forbidden"
    with pytest.raises(ServiceError) as e:
        world.as_(STAFF).create_jd_from_text("word " * 6000)
    assert (e.value.code, e.value.status) == ("text_too_long", 422)


# --- previewing the job description without downloading it -------------------------------------------------------------

def test_rmg_can_preview_a_job_description_to_see_what_was_understood_and_its_own_text(world):  # noqa: F811
    created = world.as_(STAFF).create_jd("opening.txt", b"We need a Java developer with Kafka experience.", title="Platform Engineer")

    preview = world.as_(STAFF).jd_preview(created["id"])

    assert preview["title"] == "Platform Engineer" and preview["roles"] and "flagged" in preview
    assert "We need a Java developer with Kafka experience." in preview["text"] and preview["truncated"] is False


def test_a_long_job_description_is_cut_for_the_preview_and_says_so(world):  # noqa: F811
    created = world.as_(STAFF).create_jd_from_text("word " * 3000)  # 15,000 characters

    preview = world.as_(STAFF).jd_preview(created["id"])

    assert preview["truncated"] is True and 0 < len(preview["text"]) <= 8000


def test_a_job_description_made_from_requirements_previews_without_original_text(ready):  # noqa: F811
    preview = ready.as_(STAFF).jd_preview(jd_id_of(ready))  # the seeded demo job description has no stored file

    assert preview["roles"] and preview["text"] == "" and preview["truncated"] is False


def test_the_associate_the_lead_and_rmg_can_preview_the_jd_of_their_request(ready):  # noqa: F811
    for who in (RAVI, LEAD, STAFF):
        preview = ready.as_(who).request_jd_preview(ready.request_id)
        assert preview["roles"] and preview["title"]


def test_someone_with_no_part_in_the_request_cannot_preview_its_jd(ready):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        ready.as_(DIVYA).request_jd_preview(ready.request_id)
    assert e.value.status in (403, 404)


def test_the_jd_list_preview_is_for_rmg_only(ready):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        ready.as_(RAVI).jd_preview(jd_id_of(ready))
    assert e.value.status == 403


def test_a_preview_of_a_job_description_that_does_not_exist_is_not_found(world):  # noqa: F811
    with pytest.raises(ServiceError) as e:
        world.as_(STAFF).jd_preview(9999)
    assert e.value.status == 404

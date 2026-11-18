"""The download runs the layout judge when the server has one, and says what happened; with none, it downloads as before."""
import io
import logging

from docx import Document

from app.rmg.resume.layout_fix import Polish
from app.rmg.resume.template import W, paragraph_text
from tests.unit.test_resume_service import RAVI, STAFF, built, ready, world  # noqa: F401  (fixtures and helpers)


def with_polisher(world_, polisher):
    object.__setattr__(world_.engine, "polisher", polisher)  # the engine is a frozen dataclass: set it the way tests may


def texts(docx: bytes) -> list[str]:
    return [paragraph_text(p) for p in Document(io.BytesIO(docx)).element.body.iter(W + "p")]


def test_without_a_polisher_the_download_is_as_before_and_says_the_layout_was_not_checked(ready):  # noqa: F811
    built(ready)
    rmg = ready.as_(STAFF)

    name, data, _ = rmg.download(ready.request_id)

    assert name.endswith("_DRAFT.docx") and data and rmg.last_layout == "not_checked"


def test_the_user_gets_the_file_the_polisher_returns_and_the_service_notes_the_outcome(ready):  # noqa: F811
    built(ready)
    seen = {}

    def polisher(docx, template):
        seen["docx"], seen["template"] = docx, template
        return Polish(docx=docx + b"", status="fixed", rounds=1)

    with_polisher(ready, polisher)
    rmg = ready.as_(STAFF)

    _, data, _ = rmg.download(ready.request_id)

    assert rmg.last_layout == "fixed" and data == seen["docx"] and seen["template"][:2] == b"PK"  # it is shown the template as well


def test_a_polished_file_replaces_the_original_in_the_download(ready):  # noqa: F811
    built(ready)
    marker = io.BytesIO()
    doc = Document()
    doc.add_paragraph("The polished version")
    doc.save(marker)
    with_polisher(ready, lambda docx, template: Polish(docx=marker.getvalue(), status="fixed", rounds=1))

    _, data, _ = ready.as_(STAFF).download(ready.request_id)

    assert texts(data) == ["The polished version"]


def test_a_polisher_that_raises_never_stops_the_download(ready):  # noqa: F811
    built(ready)

    def broken(docx, template):
        raise RuntimeError("office crashed")

    with_polisher(ready, broken)
    rmg = ready.as_(STAFF)

    name, data, _ = rmg.download(ready.request_id)

    assert name.endswith(".docx") and data and rmg.last_layout == "not_checked"


def test_the_outcome_goes_in_the_issue_log_with_what_was_wrong(ready, caplog):  # noqa: F811
    built(ready)
    with_polisher(ready, lambda docx, template: Polish(docx=docx, status="unfixed", rounds=2, issues=("page 2 is blank or nearly blank",)))

    with caplog.at_level(logging.INFO, logger="resume.issues"):
        ready.as_(STAFF).download(ready.request_id)

    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("layout_judged"))
    assert "status=unfixed" in line and "blank" in line and "request_id=" in line and "user=" in line

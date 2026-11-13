"""The issue log: one readable line per event, in a file, with the details needed to trace a problem."""
import logging

import pytest

from app.issue_log import configure, event


@pytest.fixture
def log_file(tmp_path):
    path = configure(tmp_path / "logs" / "resume_builder.log")
    yield path
    for handler in list(logging.getLogger("resume.issues").handlers):
        handler.close()
        logging.getLogger("resume.issues").removeHandler(handler)


def lines(path):
    return path.read_text(encoding="utf-8").splitlines()


def test_configure_creates_the_folder_and_the_file_is_written_as_events_happen(log_file):
    event("build_failed", level="error", trace="ab12", code="incomplete")

    text = log_file.read_text(encoding="utf-8")
    assert "ERROR" in text and "build_failed" in text and "trace=ab12" in text and "code=incomplete" in text


def test_each_event_is_one_line_with_a_timestamp_and_level(log_file):
    event("template_uploaded", name="Sample", size=1234)

    (line,) = lines(log_file)
    assert line[:4].isdigit() and " INFO " in line and line.endswith("name=Sample size=1234")


def test_values_with_spaces_or_quotes_are_quoted_so_a_line_can_be_read_back(log_file):
    event("upload_rejected", filename="My CV (final).docx", message='It said "no"')

    (line,) = lines(log_file)
    assert 'filename="My CV (final).docx"' in line and 'message="It said \\"no\\""' in line


def test_fields_with_no_value_are_left_out(log_file):
    event("x", present=1, absent=None)

    assert "absent" not in log_file.read_text(encoding="utf-8")


def test_an_error_adds_its_type_message_and_traceback(log_file):
    try:
        raise ValueError("model returned nothing")
    except ValueError as e:
        event("build_crashed", level="error", error=e, request_id=7)

    text = log_file.read_text(encoding="utf-8")
    assert "error_type=ValueError" in text and "model returned nothing" in text and "Traceback" in text and "request_id=7" in text


def test_text_in_any_language_is_kept(log_file):
    event("x", name="Zoë Müller 日本語")

    assert "Zoë Müller 日本語" in log_file.read_text(encoding="utf-8")


def test_configuring_the_same_file_twice_does_not_write_every_line_twice(log_file, tmp_path):
    configure(log_file)
    event("once")

    assert sum("once" in line for line in lines(log_file)) == 1


def test_without_a_file_events_do_not_fail():
    event("nowhere", level="warning", a=1)  # no file is configured for this logger: nothing is raised

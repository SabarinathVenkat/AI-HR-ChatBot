"""Reading the structure of a resume template (a .docx) so a renderer can rebuild it.

The analyser finds where each slot lives (name, role line, summary, skills, education, highlights, projects) and keeps
one prototype paragraph for each kind of line, so new content can be made by cloning the template's own formatting.
The templates here are built in memory and are synthetic; the real template is not in the repository.
"""
import pytest
from lxml import etree

from app.rmg.resume.template import W, analyse, paragraph_text
from tests.unit.resume_templates import SUMMARY, make_template

def text_of(element):
    return paragraph_text(element) if element is not None else None


def test_the_header_lines_are_found_by_their_title_style():
    m = analyse(make_template())

    assert text_of(m.name) == "Sample Name" and text_of(m.role) == "Sample Role 5 years" and text_of(m.summary) == SUMMARY


def test_a_header_inside_a_table_cell_is_found_too():
    m = analyse(make_template(header_in_table=True))

    assert text_of(m.name) == "Sample Name" and text_of(m.summary) == SUMMARY


def test_skills_keep_a_label_prototype_and_a_value_prototype():
    m = analyse(make_template())

    assert text_of(m.skills.proto_label) == "Backend: " and text_of(m.skills.proto_value) == "Java, Spring"
    assert [paragraph_text(p) for p in m.skills.region] == ["Backend: ", "Java, Spring", "Cloud: ", "AWS"]


def test_sections_are_found_in_whatever_order_the_template_uses():
    m = analyse(make_template(education_first=True))

    assert text_of(m.skills.proto_label) == "Backend: " and [paragraph_text(p) for p in m.education.region] == ["B.E. Sample Sample University 2010"]


def test_an_optional_section_the_template_does_not_have_is_simply_absent():
    assert analyse(make_template()).certifications is None
    assert [paragraph_text(p) for p in analyse(make_template(certifications=True)).certifications.region] == ["Sample Certificate"]


def test_highlights_are_the_numbered_bullets_after_their_heading():
    m = analyse(make_template())

    assert [paragraph_text(p) for p in m.highlights.region] == [f"Sample highlight {i}" for i in range(3)]
    assert text_of(m.highlights.proto) == "Sample highlight 0"


def test_projects_are_split_into_blocks_with_prototypes_for_each_kind_of_line():
    m = analyse(make_template())
    projects = m.projects

    assert [paragraph_text(b.name) for b in projects.blocks] == ["Sample Project 0", "Sample Project 1"]
    assert [len(b.bullets) for b in projects.blocks] == [4, 2]
    assert text_of(projects.proto_name) == "Sample Project 0" and text_of(projects.proto_desc) == "Sample description 0."
    assert (text_of(projects.proto_first), text_of(projects.proto_mid), text_of(projects.proto_last)) == (
        "Sample bullet 0.0", "Sample bullet 0.2", "Sample bullet 0.3")
    assert projects.proto_blank is not None and paragraph_text(projects.proto_blank) == ""


def test_a_complete_template_has_nothing_missing():
    assert analyse(make_template()).missing() == []


def test_a_template_without_title_styles_has_its_header_guessed_from_the_first_lines():
    m = analyse(make_template(title_style=False))

    assert text_of(m.name) == "Sample Name" and text_of(m.role) == "Sample Role 5 years" and m.missing() == []


def test_bullets_typed_as_a_character_are_recognised_like_numbered_ones():
    m = analyse(make_template(numbered_bullets=False))

    assert m.missing() == [] and len(m.highlights.region) == 3 and len(m.projects.blocks) == 2


def test_a_template_with_no_projects_section_reports_projects_as_missing():
    assert analyse(make_template(omit_projects=True)).missing() == ["projects"]


def test_analysing_does_not_change_the_document():
    doc = make_template()
    before = etree.tostring(doc.element.body)

    analyse(doc)

    assert etree.tostring(doc.element.body) == before


def test_the_notes_say_what_was_found_in_plain_words():
    notes = " ".join(analyse(make_template()).notes)

    assert "projects: 2 blocks" in notes and "highlights: 3 bullets" in notes


@pytest.mark.parametrize("tag", ["p"])
def test_the_word_namespace_helper_is_exported_for_the_renderer(tag):
    assert W + tag == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"


def test_a_blank_line_the_template_keeps_between_highlight_bullets_is_remembered_as_the_separator():
    spaced = analyse(make_template(spaced_highlights=True)).highlights
    plain = analyse(make_template()).highlights

    assert spaced.separator is not None and paragraph_text(spaced.separator) == ""
    assert plain.separator is None


def test_a_projects_heading_that_also_says_experience_is_still_the_projects_section():
    """Found while checking a second template: "PROJECT EXPERIENCE" was read as the highlights section, because
    "experience" is matched before "project"."""
    m = analyse(make_template(highlights_heading="PROFILE HIGHLIGHTS", projects_heading="PROJECT EXPERIENCE"))

    assert m.missing() == [] and len(m.projects.blocks) == 2 and len(m.highlights.region) == 3


def test_the_line_under_the_highlights_heading_is_remembered_as_the_subheading():
    with_sub = analyse(make_template(highlights_subheading="Professional summary and Key highlights")).highlights
    without = analyse(make_template()).highlights

    assert paragraph_text(with_sub.subheading) == "Professional summary and Key highlights"
    assert without.subheading is None

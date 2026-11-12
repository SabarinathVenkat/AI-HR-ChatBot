"""A long skills list must not push Education off the first page: the side column is tightened until it fits.

Word cannot be run here, so the fit is estimated from text length, font size and line spacing. The tests check the
decisions (when to tighten, how far, and that the template itself is never touched), not pixel positions.
"""
from docx import Document
import io

from app.rmg.resume.model import Education, Item, Origin, Resume, SkillGroup
from app.rmg.resume.render import render_resume
from app.rmg.resume.template import W, analyse
from tests.unit.resume_templates import make_template


def template_bytes():
    buf = io.BytesIO()
    make_template().save(buf)
    return buf.getvalue()


def skill_group(name, count):
    return SkillGroup(category=name, items=[Item(text=f"Technology {name} {i}", origin=Origin.ORIGINAL, source=f"skills.{i}")
                                            for i in range(count)])


def render(groups):
    resume = Resume(name="A B", skill_groups=groups, education=[Education(degree="B.Tech", institution="Uni", year="2010")])
    return render_resume(template_bytes(), resume)


def skill_paragraphs(result):
    doc = Document(io.BytesIO(result.docx))
    m = analyse(doc)
    return m.skills.region, m


def line_values(paragraphs):
    out = []
    for p in paragraphs:
        spacing = p.find(f"{W}pPr/{W}spacing")
        out.append(None if spacing is None else spacing.get(f"{W}line"))
    return out


def font_sizes(paragraphs):
    return {r.get(f"{W}val") for p in paragraphs for r in p.iter(f"{W}sz")}


def test_a_short_skills_list_is_left_exactly_as_the_template_has_it():
    result = render([skill_group("Backend", 3), skill_group("Cloud", 3)])
    region, _ = skill_paragraphs(result)
    plain = skill_paragraphs(render_resume(template_bytes(), Resume(name="A B", skill_groups=[skill_group("Backend", 3)])))[0]

    assert line_values(region)[0] == line_values(plain)[0]
    assert font_sizes(region) == font_sizes(plain)
    assert result.problems == ()


def test_a_long_skills_list_gets_tighter_line_spacing():
    short = render([skill_group("Backend", 3)])
    long = render([skill_group(f"Group{i}", 12) for i in range(4)])

    tight = [int(v) for v in line_values(skill_paragraphs(long)[0]) if v]
    normal = [int(v or 240) for v in line_values(skill_paragraphs(short)[0])]
    assert tight and max(tight) < max(normal)


def test_the_tightening_also_applies_to_education_so_the_column_looks_the_same():
    long = render([skill_group(f"Group{i}", 12) for i in range(4)])
    _, m = skill_paragraphs(long)

    education_lines = [v for v in line_values(m.education.region) if v]
    skill_lines = [v for v in line_values(m.skills.region) if v]
    assert education_lines and education_lines[0] == skill_lines[0]


def test_a_list_too_long_even_when_tightened_is_reported_not_hidden():
    huge = render([skill_group(f"Group{i}", 40) for i in range(15)])

    assert any("skills" in p and "next page" in p for p in huge.problems)


def test_nothing_is_dropped_when_tightening():
    long = render([skill_group(f"Group{i}", 24) for i in range(8)])
    region, _ = skill_paragraphs(long)
    text = " ".join("".join(t.text or "" for t in p.iter(f"{W}t")) for p in region)

    assert "Technology Group7 23" in text and "Group0:" in text

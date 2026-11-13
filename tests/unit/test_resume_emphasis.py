"""Bold key words: only if the template does it, and only the resume's own skill terms.

A template whose highlight bullets have some words in bold ("modernizing enterprise applications") shows that its
style is to emphasise key terms, so the output does the same. A template with no bold in those bullets gets no bold.
"""
import io

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.rmg.resume.emphasis import emphasise, terms_of
from app.rmg.resume.model import Education, Item, Origin, Project, Resume, SkillGroup
from app.rmg.resume.render import render_resume
from app.rmg.resume.template import W, analyse, has_emphasis, paragraph_text, run_is_bold
from tests.unit.resume_templates import make_template


def orig(text, n=0):
    return Item(text=text, origin=Origin.ORIGINAL, source=f"s.{n}")


def bold_parts(segments):
    return [text for text, bold in segments if bold]


TERMS = ["Python", "SQL", ".NET Core", "Angular", "Vue.js", "AWS", "C#", "ASP.NET Web API"]


# --- choosing the words ------------------------------------------------------------------------------------------------

def test_skill_terms_in_the_text_are_bold_and_the_rest_is_not():
    segments = emphasise("Built services in Python and tuned SQL queries for reports.", TERMS)

    assert bold_parts(segments) == ["Python", "SQL"]
    assert "".join(t for t, _ in segments) == "Built services in Python and tuned SQL queries for reports."


def test_neighbouring_terms_joined_by_commas_slashes_or_and_become_one_bold_phrase():
    segments = emphasise("Migrated to Angular/Vue.js SPAs and C#, .NET Core, ASP.NET Web API services.", TERMS)

    assert bold_parts(segments) == ["Angular/Vue.js", "C#, .NET Core, ASP.NET Web API"]


def test_a_term_is_only_matched_as_a_whole_word_ignoring_case():
    assert bold_parts(emphasise("JavaScript and pythonic style", ["Java", "Python"])) == []
    assert bold_parts(emphasise("Wrote python scripts", ["Python"])) == ["python"]


def test_text_is_never_changed_by_emphasis():
    text = "Used  AWS (S3, EC2) with Python, SQL & more."
    assert "".join(t for t, _ in emphasise(text, ["AWS", "S3", "EC2", "Python", "SQL"])) == text


def test_text_that_would_be_almost_all_bold_is_left_plain():
    assert bold_parts(emphasise("Python, SQL, AWS", TERMS)) == []


def test_nothing_is_bold_when_no_term_is_found():
    assert emphasise("Led a team of five.", TERMS) == [("Led a team of five.", False)]


def test_terms_come_from_the_resumes_skills_including_what_is_inside_brackets_and_skip_one_letter_names():
    resume = Resume(name="A", skill_groups=[SkillGroup(category="Cloud", items=[orig("AWS (S3, EC2, SageMaker)"), orig("R"), orig("Kafka")])])

    terms = terms_of(resume)

    assert {"AWS", "S3", "EC2", "SageMaker", "Kafka"} <= set(terms) and "R" not in terms


# --- does the template use bold for emphasis --------------------------------------------------------------------------------

def emphasis_template(*, bold_in_highlights=True, bold_in_projects=False, label_only=False):
    doc = make_template()
    for p in doc.element.body.iter(W + "p"):
        text = paragraph_text(p)
        if text.startswith("Sample highlight") and bold_in_highlights or text.startswith("Sample bullet") and bold_in_projects:
            for child in [c for c in p if c.tag == W + "r"]:
                p.remove(child)
            for part, bold in ((("Label:", True), (" the rest of it", False)) if label_only else
                               (("Sample ", False), ("key phrase", True), (" the rest", False))):
                run = OxmlElement("w:r")
                if bold:
                    rpr = OxmlElement("w:rPr")
                    rpr.append(OxmlElement("w:b"))
                    run.append(rpr)
                t = OxmlElement("w:t")
                t.text = part
                t.set(qn("xml:space"), "preserve")
                run.append(t)
                p.append(run)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_bullets_with_some_words_in_bold_mean_the_template_emphasises():
    m = analyse(Document(io.BytesIO(emphasis_template())))

    assert m.highlights.emphasis is True and m.projects.emphasis is False


def test_a_template_with_no_bold_in_its_bullets_does_not_emphasise():
    m = analyse(Document(io.BytesIO(emphasis_template(bold_in_highlights=False))))

    assert m.highlights.emphasis is False and m.projects.emphasis is False


def test_a_bold_label_at_the_start_of_a_bullet_is_a_label_not_emphasis():
    assert analyse(Document(io.BytesIO(emphasis_template(label_only=True)))).highlights.emphasis is False


def test_has_emphasis_ignores_all_bold_and_all_plain_paragraphs():
    doc = Document()
    doc.add_paragraph().add_run("All bold").bold = True
    doc.add_paragraph("All plain")

    assert has_emphasis(list(doc.element.body.iter(W + "p"))) is False


# --- the output ---------------------------------------------------------------------------------------------------------------

RESUME = Resume(
    name="A B", skill_groups=[SkillGroup(category="Tech", items=[orig("Python"), orig("AWS"), orig("Kafka")])],
    highlights=[orig("Built event-driven systems with Python and Kafka on AWS.")],
    projects=[Project(name="Payments", bullets=[orig("Moved batch jobs to Python services on AWS.")])])


def output_runs(template, resume=RESUME):
    doc = Document(io.BytesIO(render_resume(template, resume).docx))
    result = {}
    for p in doc.element.body.iter(W + "p"):
        text = paragraph_text(p)
        if text.startswith(("Built event", "Moved batch")):
            result[text] = [(("".join(t.text or "" for t in r.iter(W + "t"))), run_is_bold(r)) for r in p.iter(W + "r")]
    return result


def test_a_template_that_emphasises_gets_the_skill_terms_in_bold_in_the_highlights():
    runs = output_runs(emphasis_template())["Built event-driven systems with Python and Kafka on AWS."]

    assert [t for t, bold in runs if bold] == ["Python and Kafka", "AWS"]
    assert "".join(t for t, _ in runs) == "Built event-driven systems with Python and Kafka on AWS."


def test_project_bullets_are_only_bold_if_the_templates_project_bullets_are():
    plain_projects = output_runs(emphasis_template(bold_in_projects=False))["Moved batch jobs to Python services on AWS."]
    bold_projects = output_runs(emphasis_template(bold_in_projects=True))["Moved batch jobs to Python services on AWS."]

    assert not any(bold for _, bold in plain_projects)
    assert [t for t, bold in bold_projects if bold] == ["Python", "AWS"]


def test_a_template_with_no_bold_in_its_bullets_gives_no_bold_anywhere_in_the_bullets():
    runs = output_runs(emphasis_template(bold_in_highlights=False))

    assert runs and not any(bold for parts in runs.values() for _, bold in parts)


def test_the_plain_test_template_gives_no_bold_bullets_either():
    buf = io.BytesIO()
    make_template().save(buf)

    runs = output_runs(buf.getvalue())

    assert runs and not any(bold for parts in runs.values() for _, bold in parts)


def test_project_descriptions_follow_the_templates_own_style_separately_from_its_bullets():
    doc = make_template()
    for p in doc.element.body.iter(W + "p"):
        if paragraph_text(p).startswith("Sample description"):
            for child in [c for c in p if c.tag == W + "r"]:
                p.remove(child)
            for part, bold in (("Moved to ", False), ("cloud", True), (" for good.", False)):
                run = OxmlElement("w:r")
                if bold:
                    rpr = OxmlElement("w:rPr")
                    rpr.append(OxmlElement("w:b"))
                    run.append(rpr)
                t = OxmlElement("w:t")
                t.text = part
                t.set(qn("xml:space"), "preserve")
                run.append(t)
                p.append(run)
    buf = io.BytesIO()
    doc.save(buf)
    resume = RESUME.model_copy(update={"projects": [Project(name="Payments", description=orig("Rebuilt the batch jobs in Python on AWS."),
                                                            bullets=[orig("Moved batch jobs to Python services on AWS.")])]})

    m = analyse(Document(io.BytesIO(buf.getvalue())))
    out = Document(io.BytesIO(render_resume(buf.getvalue(), resume).docx))
    runs = {paragraph_text(p): [(("".join(t.text or "" for t in r.iter(W + "t"))), run_is_bold(r)) for r in p.iter(W + "r")]
            for p in out.element.body.iter(W + "p")}

    assert m.projects.desc_emphasis is True and m.projects.emphasis is False
    assert [t for t, bold in runs["Rebuilt the batch jobs in Python on AWS."] if bold] == ["Python", "AWS"]
    assert not any(bold for _, bold in runs["Moved batch jobs to Python services on AWS."])


def test_a_template_line_with_no_bold_gets_no_bold_even_where_the_renderer_would_normally_bold_a_part():
    doc = make_template()
    for p in doc.element.body.iter(W + "p"):
        if paragraph_text(p).startswith("B.E. Sample"):  # the education line: take its bold out
            for b in list(p.iter(W + "b")):
                b.getparent().remove(b)
    buf = io.BytesIO()
    doc.save(buf)
    resume = Resume(name="A B", skill_groups=RESUME.skill_groups, education=[Education(degree="B.E. Computer Science", institution="Anna University", year="2015")],
                    highlights=RESUME.highlights, projects=RESUME.projects)

    out = Document(io.BytesIO(render_resume(buf.getvalue(), resume).docx))
    bold_text = [paragraph_text(p) for p in out.element.body.iter(W + "p") if any(run_is_bold(r) for r in p.iter(W + "r"))]

    assert [t for t in bold_text if t.startswith(("B.E.", "Built", "Moved"))] == []

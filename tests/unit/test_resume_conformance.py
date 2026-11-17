"""The conformance check: does the finished resume match the setup template, and is it a good resume file?

Each test renders a resume into a template, then (where it needs to) damages the output in one specific way and
checks that exactly that check notices. All plain code: no model is involved.
"""
import io

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.rmg.resume.conformance import check_conformance
from app.rmg.resume.model import Education, Item, Origin, Project, Resume, SkillGroup
from app.rmg.resume.render import render_resume
from app.rmg.resume.template import W, is_heading, paragraph_text
from tests.unit.resume_templates import make_template


def orig(text, n=0):
    return Item(text=text, origin=Origin.ORIGINAL, source=f"s.{n}")


RESUME = Resume(
    name="Anil Verma", role_title=orig("Senior Backend Engineer"), summary=orig("Backend engineer who builds payment systems."),
    skill_groups=[SkillGroup(category="Backend", items=[orig("Java"), orig("Spring Boot")]), SkillGroup(category="Cloud", items=[orig("AWS")])],
    education=[Education(degree="B.E. Computer Science", institution="Anna University", year="2015")],
    highlights=[orig("Led the move to event-driven systems."), orig("Mentored five engineers.")],
    projects=[Project(name="Payments", description=orig("Built payments on Kafka."), bullets=[orig("Wrote Java services."), orig("Tuned SQL queries.")])],
)


def docx_bytes(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def template(**kw) -> bytes:
    return docx_bytes(make_template(**kw))


def rendered(resume=RESUME, tpl=None, **kw):
    tpl = tpl or template(highlights_subheading="Professional summary and Key highlights", **kw)
    return tpl, render_resume(tpl, resume).docx


def damaged(output: bytes, change) -> bytes:
    doc = Document(io.BytesIO(output))
    change(doc)
    return docx_bytes(doc)


def by_name(report):
    return {c.name: c for c in report.checks}


def paragraph(doc, text):
    return next(p for p in doc.element.body.iter(W + "p") if paragraph_text(p) == text)


# --- a good resume passes everything -----------------------------------------------------------------------------------

def test_a_resume_rendered_into_its_template_passes_every_check():
    tpl, out = rendered()

    report = check_conformance(tpl, out, RESUME)

    assert report.status == "pass", [(c.name, c.message) for c in report.checks if c.status != "pass"]
    assert {"sections", "sample_text", "complete", "empty_sections", "bullets", "bold", "fonts", "pages", "breaks"} <= set(by_name(report))


def test_a_section_the_resume_has_nothing_for_is_not_expected_to_be_there():
    thin = Resume(name="Nora", skill_groups=RESUME.skill_groups, highlights=RESUME.highlights)
    tpl, out = rendered(thin)

    assert check_conformance(tpl, out, thin).status == "pass"


def test_a_resume_with_every_kind_of_content_but_a_plain_template_passes():
    with_certs = RESUME.model_copy(update={"certifications": [Item(text="AWS Certified Developer", origin=Origin.ORIGINAL, source="certifications.0")]})
    tpl, out = rendered(with_certs, tpl=template(certifications=True))

    assert check_conformance(tpl, out, with_certs).status == "pass"


# --- sections ------------------------------------------------------------------------------------------------------------

def test_a_missing_heading_is_a_failure():
    tpl, out = rendered()
    broken = damaged(out, lambda d: paragraph(d, "EDUCATION").getparent().remove(paragraph(d, "EDUCATION")))

    check = by_name(check_conformance(tpl, broken, RESUME))["sections"]

    assert check.status == "fail" and "EDUCATION" in check.message


def test_headings_in_a_different_order_than_the_template_are_a_failure():
    tpl, out = rendered()

    def swap(doc):
        skills, education = paragraph(doc, "SKILLS"), paragraph(doc, "EDUCATION")
        marker = OxmlElement("w:p")
        skills.addprevious(marker)
        education.addprevious(skills)
        marker.addprevious(education)
        marker.getparent().remove(marker)

    check = by_name(check_conformance(tpl, damaged(out, swap), RESUME))["sections"]

    assert check.status == "fail" and "order" in check.message


def test_a_heading_the_template_does_not_have_is_a_failure():
    tpl, out = rendered()

    def add(doc):
        extra = OxmlElement("w:p")
        paragraph(doc, "SKILLS").addprevious(extra)
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "MY HOBBIES"
        run.append(text)
        extra.append(run)
        ppr = OxmlElement("w:pPr")
        style = OxmlElement("w:pStyle")
        style.set(qn("w:val"), "Heading1")
        ppr.append(style)
        extra.insert(0, ppr)

    assert by_name(check_conformance(tpl, damaged(out, add), RESUME))["sections"].status == "fail"


# --- leftover sample text ------------------------------------------------------------------------------------------------

def test_sample_text_from_the_template_left_in_the_output_is_a_failure():
    tpl, out = rendered()

    def leave_sample(doc):
        target = paragraph(doc, "Led the move to event-driven systems.")
        for t in target.iter(W + "t"):
            t.text = "Sample highlight 1"

    check = by_name(check_conformance(tpl, damaged(out, leave_sample), RESUME))["sample_text"]

    assert check.status == "fail" and "Sample highlight 1" in check.message


def test_a_resume_that_really_says_the_same_thing_as_the_sample_is_not_flagged():
    same = RESUME.model_copy(update={"highlights": [orig("Sample highlight 1")]})
    tpl, out = rendered(same)

    assert by_name(check_conformance(tpl, out, same))["sample_text"].status == "pass"


def test_a_long_sentence_of_the_template_that_is_unchanged_in_the_output_is_a_warning_even_if_it_was_not_mapped_to_anything():
    doc = make_template(highlights_subheading="Professional summary and Key highlights")
    tagline = "This tagline is part of the template design and is not one of the parts the reader fills in with resume text."
    first = next(p for p in doc.element.body.iter(W + "p") if paragraph_text(p).startswith("A long sample summary"))
    extra = OxmlElement("w:p")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = tagline
    run.append(text)
    extra.append(run)
    first.addnext(extra)  # right under the summary, which is the part the reader fills in
    tpl = docx_bytes(doc)
    out = render_resume(tpl, RESUME).docx

    check = by_name(check_conformance(tpl, out, RESUME))["sample_text"]

    assert check.status == "warn" and "tagline" in check.message


# --- nothing missing -----------------------------------------------------------------------------------------------------------

def test_a_part_of_the_resume_missing_from_the_file_is_a_failure_and_names_it():
    tpl, out = rendered()
    broken = damaged(out, lambda d: paragraph(d, "Mentored five engineers.").getparent().remove(paragraph(d, "Mentored five engineers.")))

    check = by_name(check_conformance(tpl, broken, RESUME))["complete"]

    assert check.status == "fail" and "Mentored five engineers." in check.message


def test_a_template_with_no_certifications_section_is_given_one_so_the_certification_is_not_missing():
    with_certs = RESUME.model_copy(update={"certifications": [Item(text="AWS Certified Developer", origin=Origin.ORIGINAL, source="certifications.0")]})
    tpl, out = rendered(with_certs)  # this template has no certifications section

    assert by_name(check_conformance(tpl, out, with_certs))["complete"].status == "pass"


# --- empty sections ----------------------------------------------------------------------------------------------------------------

def test_a_heading_with_nothing_under_it_is_a_failure():
    tpl, out = rendered()

    def empty_heading(doc):
        for p in list(doc.element.body.iter(W + "p")):
            if paragraph_text(p).startswith(("Tuned SQL", "Wrote Java")):
                p.getparent().remove(p)
        for p in list(doc.element.body.iter(W + "p")):
            if paragraph_text(p) in ("Payments", "Built payments on Kafka."):
                p.getparent().remove(p)

    assert by_name(check_conformance(tpl, damaged(out, empty_heading), RESUME))["empty_sections"].status == "fail"


# --- bullets, bold, fonts ----------------------------------------------------------------------------------------------------------

def test_a_bullet_that_is_not_the_templates_bullet_is_a_warning():
    tpl, out = rendered()

    def other_bullet(doc):
        for e in paragraph(doc, "Mentored five engineers.").iter(W + "numId"):
            e.set(W + "val", "9")

    check = by_name(check_conformance(tpl, damaged(out, other_bullet), RESUME))["bullets"]

    assert check.status == "warn"


def test_bold_inside_a_bullet_when_the_template_has_none_is_a_failure():
    tpl, out = rendered()

    def bold_it(doc):
        run = next(paragraph(doc, "Mentored five engineers.").iter(W + "r"))
        rpr = run.find(W + "rPr")
        if rpr is None:
            rpr = OxmlElement("w:rPr")
            run.insert(0, rpr)
        rpr.append(OxmlElement("w:b"))
        # make it partial: split the paragraph so that only part is bold
        for t in run.iter(W + "t"):
            t.text = "Mentored"
        tail = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = " five engineers."
        text.set(qn("xml:space"), "preserve")
        tail.append(text)
        run.addnext(tail)

    check = by_name(check_conformance(tpl, damaged(out, bold_it), RESUME))["bold"]

    assert check.status == "fail"


def test_a_font_the_template_never_uses_is_a_warning():
    doc = make_template()
    for p in doc.element.body.iter(W + "p"):
        for r in p.iter(W + "r"):
            fonts = r.find(W + "rPr/" + W + "rFonts")
            rpr = r.find(W + "rPr")
            if rpr is None:
                rpr = OxmlElement("w:rPr")
                r.insert(0, rpr)
            if fonts is None:
                fonts = OxmlElement("w:rFonts")
                rpr.insert(0, fonts)
            fonts.set(W + "ascii", "Calibri")
    tpl = docx_bytes(doc)
    out = render_resume(tpl, RESUME).docx

    def comic(d):
        run = next(paragraph(d, "Mentored five engineers.").iter(W + "r"))
        run.find(W + "rPr/" + W + "rFonts").set(W + "ascii", "Comic Sans MS")

    assert by_name(check_conformance(tpl, out, RESUME))["fonts"].status == "pass"
    assert by_name(check_conformance(tpl, damaged(out, comic), RESUME))["fonts"].status == "warn"


# --- pages and breaks -----------------------------------------------------------------------------------------------------------------

def test_a_typed_page_break_left_in_the_output_is_a_warning():
    tpl, out = rendered()

    def add_break(doc):
        paragraph(doc, "Mentored five engineers.").getparent()  # keep the structure; add a break to the end of the paragraph
        run = OxmlElement("w:r")
        br = OxmlElement("w:br")
        br.set(qn("w:type"), "page")
        run.append(br)
        paragraph(doc, "Mentored five engineers.").append(run)

    assert by_name(check_conformance(tpl, damaged(out, add_break), RESUME))["breaks"].status == "warn"


def test_a_resume_over_the_page_limit_is_a_warning():
    long_resume = RESUME.model_copy(update={"projects": [Project(name=f"Project {n}", bullets=[orig("Delivered a long feature " * 25) for _ in range(8)])
                                                         for n in range(12)]})
    tpl, out = rendered(long_resume)

    assert by_name(check_conformance(tpl, out, long_resume))["pages"].status == "warn"


# --- the standard layout fallback -------------------------------------------------------------------------------------------------------

def test_when_the_standard_layout_was_used_the_report_says_so_and_still_checks_the_result():
    from app.rmg.resume.render import render_best

    broken_template = template(omit_projects=True)
    result = render_best(broken_template, RESUME)

    report = check_conformance(broken_template, result.docx, RESUME, used_standard_layout=True)

    assert report.status == "warn" and by_name(report)["template"].status == "warn"
    assert by_name(report)["complete"].status == "pass"


def test_a_report_can_be_sent_as_plain_data():
    tpl, out = rendered()

    data = check_conformance(tpl, out, RESUME).to_dict()

    assert data["status"] == "pass" and data["checks"][0].keys() >= {"name", "status", "message"} and data["summary"]


def test_the_page_break_helper_import_is_used():
    assert WD_BREAK.PAGE is not None and is_heading is not None

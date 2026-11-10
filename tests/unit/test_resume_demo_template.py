"""The demo template is a valid template: it can be analysed, uploaded and rendered into."""
import io

from docx import Document

from app.rmg.resume.demo_template import make_demo_template
from app.rmg.resume.render import render_resume
from app.rmg.resume.template import analyse
from tests.unit.resume_fakes import RESUME


def test_the_demo_template_has_every_required_slot():
    assert analyse(Document(io.BytesIO(make_demo_template()))).missing() == []


def test_a_resume_renders_into_the_demo_template_without_problems():
    result = render_resume(make_demo_template(), RESUME, years_text="6 years")

    assert result.problems == () and result.docx[:2] == b"PK"

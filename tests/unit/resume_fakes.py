"""A fake chat model for the resume tests: returns what it is told, records how it was asked."""
from langchain_core.messages import AIMessage

from app.rmg.resume.draft import DraftedBullet, DraftedProject
from app.rmg.resume.extract import ExtractionResult, LLMResumeExtractor
from app.rmg.resume.jd import JobDescription, Role
from app.rmg.resume.model import Education, Item, Job, Origin, Project, Resume, SkillGroup


class FakeStructured:
    def __init__(self, reply):
        self.reply, self.messages = reply, None

    def invoke(self, messages):
        self.messages = messages
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class FakeModel:
    def __init__(self, parsed=None, stop_reason="end_turn", parsing_error=None, error=None):
        reply = error or {"raw": AIMessage(content="", response_metadata={"stop_reason": stop_reason}),
                          "parsed": parsed, "parsing_error": parsing_error}
        self.structured, self.kwargs, self.schema = FakeStructured(reply), None, None

    def with_structured_output(self, schema, **kwargs):
        self.schema, self.kwargs = schema, kwargs
        return self.structured


def extractor_for(model, extractor_class=LLMResumeExtractor):
    budgets = []

    def factory(max_tokens):
        budgets.append(max_tokens)
        return model

    return extractor_class(factory), budgets


# --- shared sample data and fake extractors for the pipeline and workflow tests ---

def orig(text, source):
    return Item(text=text, origin=Origin.ORIGINAL, source=source)


RESUME = Resume(
    name="Anil Verma", role_title=orig("Senior Backend Engineer", "title"), summary=orig("Backend engineer.", "summary"),
    skill_groups=[SkillGroup(category="Backend", items=[orig("Python", "skills.0.0"), orig("Kafka", "skills.0.1"),
                                                        orig("Java", "skills.0.2"), orig("java", "skills.0.3")])],
    education=[Education(degree="B.E.", institution="Anna University", year="2015")],
    highlights=[orig("Built event-driven systems.", "highlights.0")],
    jobs=[Job(company="Finwave", title="Engineer", start="Mar 2020", end="Present")],
    projects=[Project(name="Intranet", bullets=[orig("Maintained the portal.", "projects.0.bullets.0")]),
              Project(name="Payments", description=orig("Built payments on Kafka.", "projects.1.description"),
                      bullets=[orig("Wrote Java services.", "projects.1.bullets.0"), orig("Tuned SQL queries.", "projects.1.bullets.1")])],
)
JD = JobDescription(roles=[Role(title="Java Developer", min_years=5, must_have=["Java", "Kubernetes"], nice_to_have=["Kafka"]),
                           Role(title="QA Lead", min_years=None, must_have=["Selenium"], nice_to_have=[])], flagged=[])


class FakeResumeExtractor:
    def __init__(self, resume=RESUME, error=None, barrier=None):
        self.resume, self.error, self.barrier, self.calls = resume, error, barrier, []

    def extract(self, doc):
        self.calls.append(doc)
        if self.barrier:
            self.barrier.wait()
        if self.error:
            raise self.error
        return ExtractionResult(resume=self.resume, coverage=1.0)


class FakeJDExtractor:
    def __init__(self, jd=JD, error=None, barrier=None):
        self.jd, self.error, self.barrier, self.calls = jd, error, barrier, []

    def extract(self, doc):
        self.calls.append(doc)
        if self.barrier:
            self.barrier.wait()
        if self.error:
            raise self.error
        return self.jd


def keep_as_written(project, role, plan):
    return DraftedProject(description="", bullets=[DraftedBullet(text=b.text, from_bullet=i) for i, b in enumerate(project.bullets)])

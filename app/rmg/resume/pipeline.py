"""The whole resume-builder run as one LangGraph graph.

    check_template -> extract_resume ─┐
                   -> extract_jd ─────┴-> join -> analyse -> tailor -> ground -> changelog -> render

  check_template   refuses a template that is not a readable Word file before anything costly happens
  extract_*        read and extract the resume and the JD at the same time (two static parallel branches); an
                   expected failure is recorded in state instead of raised, so a branch never hides the other one
  join             waits for both, then stops the run with the most relevant error (resume before JD) if there is one
  analyse          pick the JD role, remove duplicate skills, compute experience, build the match plan
  tailor           draft every project in parallel (the tailor graph), then put skills the JD wants first
  ground           put back the original wording of anything the resume does not support
  changelog        compare original and result, in code
  render           clone the template's paragraphs

Every model is injected (PipelineDeps), so the whole run is testable with fakes. Expected failures end the run with a
PipelineError that has the stage, a machine code and a friendly message.
"""
import operator
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.rmg.resume.changelog import ChangeLog, build_change_log
from app.rmg.resume.draft import TailoringSettings
from app.rmg.resume.extract import ExtractionError, ExtractionResult
from app.rmg.resume.facts import Experience, dedupe_skills, experience
from app.rmg.resume.grounding import enforce_grounding
from app.rmg.resume.ingest import IngestError, SourceDocument, read_document
from app.rmg.resume.jd import JobDescription, Role
from app.rmg.resume.match import MatchPlan, build_match_plan, order_skills
from app.rmg.resume.model import Resume
from app.rmg.resume.render import RenderResult, TemplateError, check_template, render_best
from app.rmg.resume.tailor import Drafter, tailor_projects

STAGE_ORDER = {"resume": 0, "job_description": 1}


class ResumeExtractorLike(Protocol):
    def extract(self, doc: SourceDocument) -> ExtractionResult: ...


class JDExtractorLike(Protocol):
    def extract(self, doc: SourceDocument) -> JobDescription: ...


@dataclass(frozen=True)
class PipelineDeps:
    resume_extractor: ResumeExtractorLike
    jd_extractor: JDExtractorLike
    drafter: Drafter
    settings: TailoringSettings = TailoringSettings()


@dataclass(frozen=True)
class PipelineRequest:
    resume_file: tuple[str, bytes]  # (filename, bytes) as uploaded
    template: bytes
    jd_file: tuple[str, bytes] | None = None  # read and extracted during the run, unless `jd` is given
    jd: JobDescription | None = None  # a job description that was already read (it is stored once and reused)
    role_index: int = 0  # which role of the JD to tailor for
    today: date | None = None  # for experience; defaults to today


class PipelineError(Exception):
    def __init__(self, stage: str, code: str, message: str):
        self.stage, self.code = stage, code
        super().__init__(message)


@dataclass(frozen=True)
class PipelineResult:
    original: Resume  # the resume as read, with duplicate skills removed: the baseline everything is compared with
    tailored: Resume  # the grounded, tailored resume that was rendered
    jd: JobDescription
    role: Role
    experience: Experience
    plan: MatchPlan
    changelog: ChangeLog
    rendered: RenderResult
    warnings: tuple[str, ...]  # projects that could not be tailored
    read_coverage: float | None  # how completely the resume was read; None for scans


class State(TypedDict, total=False):
    request: PipelineRequest
    errors: Annotated[list[tuple[str, str, str]], operator.add]
    extraction: ExtractionResult
    jd: JobDescription
    role: Role
    base: Resume
    experience: Experience
    plan: MatchPlan
    tailored: Resume
    warnings: tuple[str, ...]
    grounded: Resume
    report: object
    changelog: ChangeLog
    rendered: RenderResult


def build_pipeline(deps: PipelineDeps):
    def check_template_node(state: State):
        try:
            check_template(state["request"].template)
        except TemplateError as e:
            if e.code == "unreadable":  # a template with missing sections is fine: the standard layout is used instead
                raise PipelineError("template", e.code, str(e)) from None
        return {}

    def extract_resume(state: State):
        try:
            return {"extraction": deps.resume_extractor.extract(read_document(*state["request"].resume_file))}
        except (IngestError, ExtractionError) as e:
            return {"errors": [("resume", e.code, str(e))]}

    def extract_jd(state: State):
        if state["request"].jd is not None:
            return {"jd": state["request"].jd}
        try:
            return {"jd": deps.jd_extractor.extract(read_document(*state["request"].jd_file))}
        except (IngestError, ExtractionError) as e:
            return {"errors": [("job_description", e.code, str(e))]}

    def join(state: State):
        if errors := state.get("errors"):
            stage, code, message = min(errors, key=lambda e: STAGE_ORDER[e[0]])
            raise PipelineError(stage, code, message)
        return {}

    def analyse(state: State):
        request, jd = state["request"], state["jd"]
        if not 0 <= request.role_index < len(jd.roles):
            raise PipelineError("role", "no_such_role", "That role is not in the job description.")
        role = jd.roles[request.role_index]
        base = dedupe_skills(state["extraction"].resume)
        worked = experience(base.jobs, request.today or date.today())
        return {"role": role, "base": base, "experience": worked, "plan": build_match_plan(base, role, worked)}

    def tailor(state: State):
        result = tailor_projects(state["base"], state["role"], state["plan"], deps.drafter, deps.settings)
        return {"tailored": order_skills(result.resume, state["plan"]), "warnings": result.warnings}

    def ground(state: State):
        grounded, report = enforce_grounding(state["base"], state["tailored"], state["plan"])
        return {"grounded": grounded, "report": report}

    def changelog(state: State):
        return {"changelog": build_change_log(state["base"], state["grounded"], state["role"], state["report"], state["experience"])}

    def render(state: State):
        worked = state["experience"]
        years = worked.describe() if worked.months else ""
        return {"rendered": render_best(state["request"].template, state["grounded"], years_text=years)}

    graph = StateGraph(State)
    for name, node in (("check_template", check_template_node), ("extract_resume", extract_resume), ("extract_jd", extract_jd),
                       ("join", join), ("analyse", analyse), ("tailor", tailor), ("ground", ground),
                       ("changelog", changelog), ("render", render)):
        graph.add_node(name, node)
    graph.add_edge(START, "check_template")
    graph.add_edge("check_template", "extract_resume")
    graph.add_edge("check_template", "extract_jd")
    graph.add_edge(["extract_resume", "extract_jd"], "join")  # waits for both
    graph.add_edge("join", "analyse")
    graph.add_edge("analyse", "tailor")
    graph.add_edge("tailor", "ground")
    graph.add_edge("ground", "changelog")
    graph.add_edge("changelog", "render")
    graph.add_edge("render", END)
    return graph.compile()


def run_pipeline(deps: PipelineDeps, request: PipelineRequest) -> PipelineResult:
    out = build_pipeline(deps).invoke({"request": request})
    return PipelineResult(
        original=out["base"], tailored=out["grounded"], jd=out["jd"], role=out["role"], experience=out["experience"],
        plan=out["plan"], changelog=out["changelog"], rendered=out["rendered"], warnings=out["warnings"],
        read_coverage=out["extraction"].coverage)

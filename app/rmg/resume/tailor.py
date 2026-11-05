"""Tailor every project of a resume in parallel, with a LangGraph fan-out.

The graph:  START --(one Send per project)--> draft_project (runs for all projects at the same time) --> assemble

  fan_out        looks at the resume and returns one Send per project. Each Send starts its own run of
                 draft_project with that project's data, so the number of branches is decided at run time.
  draft_project  asks the drafter for one project and applies the rules (apply_draft). If anything goes wrong the
                 project is kept as written and a warning is recorded, so one bad project never loses the others.
  assemble       runs once every branch has finished (LangGraph waits), merges the results and puts the projects
                 in the order of the match plan (most relevant first).

`drafted` and `warnings` use reducers: each branch writes its own part and LangGraph merges them.
"""
import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.rmg.resume.draft import DraftedProject, TailoringSettings, apply_draft
from app.rmg.resume.jd import Role
from app.rmg.resume.match import MatchPlan
from app.rmg.resume.model import Project, Resume

Drafter = Callable[[Project, Role, MatchPlan], DraftedProject]


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class State(TypedDict, total=False):
    resume: Resume
    role: Role
    plan: MatchPlan
    drafted: Annotated[dict[int, Project], _merge]
    warnings: Annotated[list[str], operator.add]
    result: Resume


@dataclass(frozen=True)
class TailorResult:
    resume: Resume
    warnings: tuple[str, ...]


def build_tailor_graph(drafter: Drafter, settings: TailoringSettings):
    def fan_out(state: State):
        sends = [Send("draft_project", {"index": i, "project": p, "role": state["role"], "plan": state["plan"]})
                 for i, p in enumerate(state["resume"].projects)]
        return sends or "assemble"  # nothing to draft: go straight to the end

    def draft_project(branch: dict):
        index, project = branch["index"], branch["project"]
        try:
            return {"drafted": {index: apply_draft(project, drafter(project, branch["role"], branch["plan"]), settings)}}
        except Exception:  # a model call can fail in many ways; whatever happens, this project must not sink the rest
            return {"drafted": {index: project},
                    "warnings": [f"Project '{project.name}' could not be tailored and was kept as written."]}

    def assemble(state: State):
        drafted = state.get("drafted", {})
        order = [rank.index for rank in state["plan"].project_order]
        projects = [drafted.get(i, state["resume"].projects[i]) for i in order]
        return {"result": state["resume"].model_copy(update={"projects": projects})}

    graph = StateGraph(State)
    graph.add_node("draft_project", draft_project)
    graph.add_node("assemble", assemble)
    graph.add_conditional_edges(START, fan_out, ["draft_project", "assemble"])
    graph.add_edge("draft_project", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def tailor_projects(resume: Resume, role: Role, plan: MatchPlan, drafter: Drafter,
                    settings: TailoringSettings = TailoringSettings()) -> TailorResult:
    out = build_tailor_graph(drafter, settings).invoke({"resume": resume, "role": role, "plan": plan})
    return TailorResult(resume=out["result"], warnings=tuple(sorted(out.get("warnings", []))))

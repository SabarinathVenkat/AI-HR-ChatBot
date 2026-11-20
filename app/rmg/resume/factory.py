"""Build the live resume-builder engine: the extraction and drafting models, wired into the pipeline."""
import logging

from app.rmg.resume.chat import LLMEditInterpreter
from app.rmg.resume.deep import LLMSkillWeaver, LLMSummarizer
from app.rmg.resume.draft import DEEP_SETTINGS, LLMProjectDrafter, TailoringSettings
from app.rmg.resume.extract import LLMResumeExtractor, anthropic_factory
from app.rmg.resume.highlights import LLMHighlighter
from app.rmg.resume.jd import JDExtractor
from app.rmg.resume.layout_check import default_renderer
from app.rmg.resume.layout_fix import LayoutPolisher, LLMLayoutJudge
from app.rmg.resume.pipeline import PipelineDeps
from app.rmg.resume.service import ResumeEngine


log = logging.getLogger(__name__)


def build_live_resume_engine(settings: TailoringSettings | None = None) -> ResumeEngine:
    settings = settings or TailoringSettings()
    make_model = anthropic_factory()  # a small, fast model: it copies and rewords, it does not decide
    deps = PipelineDeps(LLMResumeExtractor(make_model), JDExtractor(make_model), LLMProjectDrafter(make_model, settings), settings,
                        LLMHighlighter(make_model), LLMProjectDrafter(make_model, DEEP_SETTINGS, deep=True), LLMSummarizer(make_model))
    renderer = default_renderer()  # LibreOffice, when the server has it: it draws the pages the layout judge looks at
    if renderer is None:
        log.warning("LibreOffice is not installed: downloads will not have their layout checked")
    polisher = LayoutPolisher(renderer, LLMLayoutJudge(make_model)) if renderer is not None else None
    return ResumeEngine(deps, LLMEditInterpreter(make_model), polisher, LLMSkillWeaver(make_model))

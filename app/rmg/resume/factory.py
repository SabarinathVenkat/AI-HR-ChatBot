"""Build the live resume-builder engine: the extraction and drafting models, wired into the pipeline."""
from app.rmg.resume.chat import LLMEditInterpreter
from app.rmg.resume.draft import LLMProjectDrafter, TailoringSettings
from app.rmg.resume.extract import LLMResumeExtractor, anthropic_factory
from app.rmg.resume.highlights import LLMHighlighter
from app.rmg.resume.jd import JDExtractor
from app.rmg.resume.pipeline import PipelineDeps
from app.rmg.resume.service import ResumeEngine


def build_live_resume_engine(settings: TailoringSettings | None = None) -> ResumeEngine:
    settings = settings or TailoringSettings()
    make_model = anthropic_factory()  # a small, fast model: it copies and rewords, it does not decide
    deps = PipelineDeps(LLMResumeExtractor(make_model), JDExtractor(make_model), LLMProjectDrafter(make_model, settings), settings,
                        LLMHighlighter(make_model))
    return ResumeEngine(deps, LLMEditInterpreter(make_model))

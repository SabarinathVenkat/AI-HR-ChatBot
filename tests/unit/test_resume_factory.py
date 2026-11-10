"""The live engine is wired from real classes (no network is touched when it is built)."""
from app.rmg.resume.chat import LLMEditInterpreter
from app.rmg.resume.draft import LLMProjectDrafter, TailoringSettings
from app.rmg.resume.extract import LLMResumeExtractor
from app.rmg.resume.factory import build_live_resume_engine
from app.rmg.resume.jd import JDExtractor


def test_the_live_engine_uses_the_real_extractors_and_drafter_with_the_given_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    engine = build_live_resume_engine(TailoringSettings(max_bullets=4))

    assert isinstance(engine.deps.resume_extractor, LLMResumeExtractor)
    assert isinstance(engine.deps.jd_extractor, JDExtractor)
    assert isinstance(engine.deps.drafter, LLMProjectDrafter) and engine.deps.settings.max_bullets == 4
    assert isinstance(engine.interpreter, LLMEditInterpreter)

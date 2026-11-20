"""The briefing shown while a resume builds: written once from the job description, always available, never a claim about the person."""
from app.rmg.resume.briefing import (
    INSTRUCTIONS, Briefing, BriefingPoint, LLMBriefer, briefing_for, briefings_for, plain_briefing,
)
from app.rmg.resume.jd import Role
from tests.support import ScriptedChatModel

ROLE = Role(title="Java Developer", min_years=5, domain="Fintech", must_have=["Java", "Spring Boot", "Kafka"], nice_to_have=["AWS"])
BARE = Role(title="Analyst", must_have=[], nice_to_have=[])


def good(role):
    return Briefing(headline=f"{role.title}: the client wants delivery", points=[BriefingPoint(title="Lead with outcomes", text="Say what you built and what it did.")])


def test_the_plain_briefing_is_built_from_the_role_alone_and_names_what_the_job_asks_for():
    briefing = plain_briefing(ROLE)

    text = " ".join(p.text for p in briefing.points)
    assert briefing.headline.startswith("Java Developer")
    assert "Java, Spring Boot and Kafka" in text and "5 years" in text and "Fintech" in text and "AWS" in text
    assert 1 <= len(briefing.points) <= 6


def test_the_plain_briefing_for_a_bare_role_still_has_something_useful_to_say():
    briefing = plain_briefing(BARE)

    assert briefing.points and all(p.title and p.text for p in briefing.points)


def test_the_models_briefing_is_used_when_it_is_valid():
    assert briefing_for(ROLE, good).headline == "Java Developer: the client wants delivery"


def test_a_failing_or_unusable_model_falls_back_to_the_plain_briefing():
    def breaks(role):
        raise RuntimeError("model down")

    def nothing(role):
        return Briefing.model_construct(headline="x", points=[])  # no points: not usable

    for briefer in (breaks, nothing, None):
        assert briefing_for(ROLE, briefer) == plain_briefing(ROLE)


def test_each_role_gets_a_briefing_and_the_model_is_asked_for_a_limited_number_of_them():
    calls = []

    def counting(role):
        calls.append(role.title)
        return good(role)

    roles = [Role(title=f"Role {n}", must_have=[], nice_to_have=[]) for n in range(9)]

    briefings = briefings_for(roles, counting)

    assert len(briefings) == 9 and len(calls) == 6  # the rest get plain ones
    assert briefings[8] == plain_briefing(roles[8])


def test_the_prompt_says_nothing_about_a_person_forbids_inventing_and_treats_the_jd_as_untrusted():
    assert "Do not invent facts about the client" in INSTRUCTIONS
    assert "Never tell the reader to claim a skill they do not have" in INSTRUCTIONS
    assert "untrusted" in INSTRUCTIONS


def test_the_llm_briefer_sends_only_the_role_and_returns_the_models_briefing():
    model = ScriptedChatModel(responses=[])
    sent = []

    class Capturing:
        def __call__(self, max_tokens):
            return model

    from app.rmg.resume import briefing as module

    original = module.structured_call
    module.structured_call = lambda m, schema, messages: (sent.append(messages[0].content), good(ROLE))[1]
    try:
        result = LLMBriefer(Capturing())(ROLE)
    finally:
        module.structured_call = original

    assert result.headline.startswith("Java Developer") and "Kafka" in sent[0] and "Fintech" in sent[0]

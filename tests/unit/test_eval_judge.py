"""The evaluation judge must retry transient failures and never turn an error into a pass."""
from eval.judge import Verdict, make_judge


class FlakyModel:
    def __init__(self, failures, verdict=None):
        self.failures = list(failures)
        self.verdict = verdict or Verdict(passed=True, reason="meets the rubric")
        self.calls = 0

    def invoke(self, prompt):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return self.verdict


def judge_with(model):
    sleeps = []
    return make_judge("unused", structured=model, sleep=sleeps.append), sleeps


def test_a_clean_verdict_is_returned_as_is():
    judge, _ = judge_with(FlakyModel([], Verdict(passed=False, reason="too long")))

    assert judge("be brief", "Q?", "A") == (False, "too long")


def test_transient_failures_are_retried_with_a_growing_pause():
    model = FlakyModel([RuntimeError("overloaded"), RuntimeError("overloaded")])
    judge, sleeps = judge_with(model)

    assert judge("r", "q", "a") == (True, "meets the rubric")
    assert model.calls == 3
    assert sleeps == [1, 3]


def test_persistent_failure_is_a_failed_check_that_names_the_cause():
    model = FlakyModel([ValueError("bad"), ValueError("bad"), ValueError("bad")])
    judge, _ = judge_with(model)

    passed, reason = judge("r", "q", "a")

    assert passed is False
    assert "ValueError" in reason


def test_the_prompt_contains_the_rubric_question_and_reply():
    seen = []

    class Recorder:
        def invoke(self, prompt):
            seen.append(prompt)
            return Verdict(passed=True, reason="ok")

    judge, _ = judge_with(Recorder())
    judge("RUBRIC-TEXT", "QUESTION-TEXT", "REPLY-TEXT {with braces}")

    assert all(word in seen[0] for word in ("RUBRIC-TEXT", "QUESTION-TEXT", "REPLY-TEXT {with braces}"))

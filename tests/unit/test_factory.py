"""The live models are built with explicit timeouts and retries (no network calls are made)."""
from app.agent import factory
from app.config import Settings


def models():
    return factory.build_models(Settings(jwt_secret="x" * 40))


def test_every_model_has_a_request_timeout_far_below_the_library_default():
    answer, router, subagent = models()

    assert answer.default_request_timeout == factory.ANSWER_TIMEOUT_SECONDS
    assert router.default_request_timeout == factory.ROUTER_TIMEOUT_SECONDS
    assert subagent.default_request_timeout == factory.SUBAGENT_TIMEOUT_SECONDS
    assert max(factory.ANSWER_TIMEOUT_SECONDS, factory.ROUTER_TIMEOUT_SECONDS,
               factory.SUBAGENT_TIMEOUT_SECONDS) <= 60


def test_every_model_retries_transient_errors_a_set_number_of_times():
    assert all(m.max_retries == factory.MAX_RETRIES for m in models())


def test_models_use_the_configured_names():
    answer, router, subagent = models()

    assert answer.model == "claude-sonnet-5-5"
    assert router.model == subagent.model == "claude-haiku-5-5"

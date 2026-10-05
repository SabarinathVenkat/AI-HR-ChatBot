from datetime import datetime, timedelta, timezone

from app.api.throttle import RateLimiter

T0 = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)


def limiter(limit=30) -> RateLimiter:
    return RateLimiter(limit, window=timedelta(minutes=1))


def test_requests_up_to_the_limit_are_allowed():
    rl = limiter()

    assert all(rl.retry_after("u1", T0) == 0 for _ in range(30))


def test_the_request_over_the_limit_is_refused_with_a_retry_delay():
    rl = limiter()
    for _ in range(30):
        rl.retry_after("u1", T0)

    assert 0 < rl.retry_after("u1", T0 + timedelta(seconds=10)) <= 50


def test_requests_are_allowed_again_once_the_window_has_passed():
    rl = limiter()
    for _ in range(30):
        rl.retry_after("u1", T0)

    assert rl.retry_after("u1", T0 + timedelta(seconds=61)) == 0


def test_the_limit_is_per_user():
    rl = limiter(limit=2)
    rl.retry_after("u1", T0)
    rl.retry_after("u1", T0)

    assert rl.retry_after("u1", T0) > 0
    assert rl.retry_after("u2", T0) == 0


def test_refused_requests_do_not_extend_the_window():
    rl = limiter(limit=1)
    rl.retry_after("u1", T0)
    for second in range(1, 30):
        rl.retry_after("u1", T0 + timedelta(seconds=second))

    assert rl.retry_after("u1", T0 + timedelta(seconds=61)) == 0

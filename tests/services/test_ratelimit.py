"""A key may make a limited number of requests a minute, and it is told when to come back."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.clock import ManualClock
from alexia_api.services.ratelimit import RateLimiter


def test_requests_up_to_the_limit_pass_and_the_next_one_waits(clock: ManualClock) -> None:
    limiter = RateLimiter(3, clock)

    assert [limiter.check("home") for _ in range(3)] == [None, None, None]
    assert limiter.check("home") == pytest.approx(20)


def test_the_wait_shrinks_as_time_passes(clock: ManualClock) -> None:
    limiter = RateLimiter(3, clock)
    for _ in range(3):
        limiter.check("home")

    clock.advance(5)

    assert limiter.check("home") == pytest.approx(15)


def test_a_refused_request_does_not_make_the_wait_longer(clock: ManualClock) -> None:
    limiter = RateLimiter(3, clock)
    for _ in range(3):
        limiter.check("home")

    first = limiter.check("home")
    second = limiter.check("home")

    assert first == second


def test_one_token_comes_back_every_so_often(clock: ManualClock) -> None:
    limiter = RateLimiter(3, clock)
    for _ in range(3):
        limiter.check("home")

    clock.advance(20)

    assert limiter.check("home") is None
    assert limiter.check("home") is not None


def test_a_long_rest_refills_the_bucket_but_never_beyond_the_limit(clock: ManualClock) -> None:
    limiter = RateLimiter(3, clock)
    limiter.check("home")

    clock.advance(3600)

    assert [limiter.check("home") for _ in range(3)] == [None, None, None]
    assert limiter.check("home") is not None


def test_each_key_has_its_own_bucket(clock: ManualClock) -> None:
    limiter = RateLimiter(1, clock)

    assert limiter.check("home") is None
    assert limiter.check("home") is not None
    assert limiter.check("phone") is None


@given(
    per_minute=st.integers(min_value=1, max_value=600),
    gaps=st.lists(st.floats(min_value=0, max_value=90, allow_nan=False), min_size=1, max_size=60),
)
def test_a_refusal_always_names_a_wait_of_more_than_nothing(
    per_minute: int, gaps: list[float]
) -> None:
    clock = ManualClock()
    limiter = RateLimiter(per_minute, clock)

    for gap in gaps:
        clock.advance(gap)
        wait = limiter.check("home")
        assert wait is None or wait > 0


def test_a_limit_of_zero_turns_the_limiter_off(clock: ManualClock) -> None:
    limiter = RateLimiter(0, clock)

    assert all(limiter.check("home") is None for _ in range(1000))

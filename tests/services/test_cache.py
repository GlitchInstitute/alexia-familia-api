"""Answers are reused for a while, concurrent askers share one load, and failures are not kept."""

import asyncio
import gc
import logging

import pytest

from alexia_api.clock import ManualClock
from alexia_api.services.cache import Cached, CacheStatus, TtlCache, combine

KEY = ("children",)


class Source:
    """A loader that counts its calls, returns the call number, and can be held open."""

    def __init__(self) -> None:
        self.calls = 0
        self.gate: asyncio.Event | None = None
        self.fail: Exception | None = None

    async def __call__(self) -> int:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return self.calls


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_the_first_ask_loads_and_the_next_ones_hit(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()

    first = await cache.get(KEY, 60, source)
    clock.advance(10)
    second = await cache.get(KEY, 60, source)

    assert (first.value, first.status, first.age) == (1, "miss", 0)
    assert (second.value, second.status, second.age) == (1, "hit", 10)
    assert source.calls == 1


async def test_an_answer_expires_after_its_time_to_live(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()
    await cache.get(KEY, 60, source)

    clock.advance(59)
    assert (await cache.get(KEY, 60, source)).status == "hit"
    clock.advance(1)
    reloaded = await cache.get(KEY, 60, source)

    assert (reloaded.value, reloaded.status) == (2, "miss")


async def test_different_keys_do_not_share_answers(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()

    first = await cache.get(("tracking", "a"), 60, source)
    second = await cache.get(("tracking", "b"), 60, source)

    assert (first.value, second.value) == (1, 2)


async def test_a_zero_time_to_live_stores_nothing(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()

    await cache.get(KEY, 0, source)
    again = await cache.get(KEY, 0, source)

    assert (again.value, again.status, source.calls) == (2, "miss", 2)


async def test_a_fresh_ask_reloads_and_keeps_the_new_answer(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()
    await cache.get(KEY, 60, source)

    fresh = await cache.get(KEY, 60, source, fresh=True)
    later = await cache.get(KEY, 60, source)

    assert (fresh.value, fresh.status, fresh.age) == (2, "bypass", 0)
    assert (later.value, later.status) == (2, "hit")


async def test_concurrent_askers_share_one_load(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()
    source.gate = asyncio.Event()
    askers = [asyncio.create_task(cache.get(KEY, 60, source)) for _ in range(5)]
    await settle()

    source.gate.set()
    results = await asyncio.gather(*askers)

    assert source.calls == 1
    assert {result.value for result in results} == {1}
    assert {result.status for result in results} == {"miss"}


async def test_a_fresh_ask_joins_a_load_that_is_already_running(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()
    source.gate = asyncio.Event()
    running = asyncio.create_task(cache.get(KEY, 60, source))
    await settle()
    impatient = asyncio.create_task(cache.get(KEY, 60, source, fresh=True))
    await settle()

    source.gate.set()
    first, second = await asyncio.gather(running, impatient)

    assert source.calls == 1
    assert (first.value, second.value, second.status) == (1, 1, "bypass")


async def test_a_failure_reaches_every_asker_and_is_not_kept(clock: ManualClock) -> None:
    cache = TtlCache(clock)
    source = Source()
    source.gate = asyncio.Event()
    source.fail = RuntimeError("the portal is down")
    askers = [asyncio.create_task(cache.get(KEY, 60, source)) for _ in range(3)]
    await settle()

    source.gate.set()
    outcomes = await asyncio.gather(*askers, return_exceptions=True)

    assert source.calls == 1
    assert all(isinstance(outcome, RuntimeError) for outcome in outcomes)
    source.fail = None
    source.gate = None
    assert (await cache.get(KEY, 60, source)).value == 2


async def test_a_cancelled_asker_does_not_cancel_the_load_for_the_others(
    clock: ManualClock,
) -> None:
    cache = TtlCache(clock)
    source = Source()
    source.gate = asyncio.Event()
    first = asyncio.create_task(cache.get(KEY, 60, source))
    second = asyncio.create_task(cache.get(KEY, 60, source))
    await settle()

    first.cancel()
    await settle()
    source.gate.set()

    assert (await second).value == 1
    assert source.calls == 1
    with pytest.raises(asyncio.CancelledError):
        await first


async def test_a_load_finishes_and_is_kept_even_when_every_asker_has_gone(
    clock: ManualClock,
) -> None:
    cache = TtlCache(clock)
    source = Source()
    source.gate = asyncio.Event()
    asker = asyncio.create_task(cache.get(KEY, 60, source))
    await settle()

    asker.cancel()
    await settle()
    source.gate.set()
    await settle()

    assert (await cache.get(KEY, 60, source)).status == "hit"
    assert source.calls == 1


async def test_a_failure_nobody_waits_for_is_not_logged_as_lost(
    clock: ManualClock, caplog: pytest.LogCaptureFixture
) -> None:
    cache = TtlCache(clock)
    source = Source()
    source.gate = asyncio.Event()
    source.fail = RuntimeError("the portal is down")
    asker = asyncio.create_task(cache.get(KEY, 60, source))
    await settle()

    asker.cancel()
    await settle()
    with caplog.at_level(logging.DEBUG):
        source.gate.set()
        await settle()
        gc.collect()
        await settle()

    assert "never retrieved" not in caplog.text
    assert (await cache.get(KEY, 60, Source())).status == "miss"


async def test_the_least_recently_used_entries_go_first_over_the_limit(
    clock: ManualClock,
) -> None:
    cache = TtlCache(clock, max_entries=2)
    source = Source()
    await cache.get(("a",), 60, source)
    await cache.get(("b",), 60, source)
    await cache.get(("a",), 60, source)

    await cache.get(("c",), 60, source)

    assert (await cache.get(("a",), 60, source)).status == "hit"
    assert (await cache.get(("b",), 60, source)).status == "miss"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (("hit",), "hit"),
        (("hit", "hit"), "hit"),
        (("hit", "miss"), "miss"),
        (("miss", "hit"), "miss"),
        (("miss", "miss"), "miss"),
        (("hit", "hit", "miss"), "miss"),
        (("bypass", "bypass"), "bypass"),
        (("bypass", "hit"), "bypass"),
        (("hit", "bypass"), "bypass"),
        (("miss", "bypass"), "bypass"),
    ],
)
def test_an_answer_made_of_stored_answers_is_a_hit_only_when_every_part_was_stored(
    statuses: tuple[CacheStatus, ...], expected: CacheStatus
) -> None:
    parts = [Cached(object(), status, 0.0) for status in statuses]

    joined = combine("answer", *parts)

    assert (joined.value, joined.status) == ("answer", expected)


def test_an_answer_made_of_stored_answers_is_as_old_as_the_oldest_part() -> None:
    parts = [Cached(object(), "hit", age) for age in (12.0, 300.0, 0.0)]

    assert combine("answer", *parts).age == 300.0

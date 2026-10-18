"""A small cache that is kind to the portal.

Each answer lives for a time to live, and concurrent askers for the same answer share one load.
The load runs as its own task, so an asker that gives up, for example a client that hangs up,
does not cancel it halfway through a recipe that other askers wait for. Failures are shared with
everyone who waited and are never stored.
"""

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from alexia_api.clock import Clock, SystemClock

type CacheKey = tuple[str, ...]
type CacheStatus = Literal["hit", "miss", "bypass"]

DEFAULT_MAX_ENTRIES: Final = 512


@dataclass(frozen=True, slots=True)
class Cached[T]:
    """An answer and how it was found."""

    value: T
    status: CacheStatus
    age: float


def combine[T](value: T, first: Cached[object], *rest: Cached[object]) -> Cached[T]:
    """Describe an answer built from several stored answers, as one.

    It is a hit only when every part was stored. A part that was forced makes it a bypass, and
    any other part that was read for it makes it a miss. It is as old as its oldest part.
    """
    parts = (first, *rest)
    statuses = {part.status for part in parts}
    if "bypass" in statuses:
        status: CacheStatus = "bypass"
    elif "miss" in statuses:
        status = "miss"
    else:
        status = "hit"
    return Cached(value, status, max(part.age for part in parts))


@dataclass(frozen=True, slots=True)
class _Entry:
    value: object
    stored_at: float
    expires_at: float


class TtlCache:
    def __init__(
        self, clock: Clock | None = None, *, max_entries: int = DEFAULT_MAX_ENTRIES
    ) -> None:
        self._clock = clock or SystemClock()
        self._max_entries = max_entries
        self._entries: OrderedDict[CacheKey, _Entry] = OrderedDict()
        self._loading: dict[CacheKey, asyncio.Task[Any]] = {}

    async def get[T](
        self,
        key: CacheKey,
        ttl: float,
        load: Callable[[], Awaitable[T]],
        *,
        fresh: bool = False,
    ) -> Cached[T]:
        """Return the stored answer, or load it.

        With `fresh`, a stored answer is ignored and a new one is loaded and kept. A load that is
        already running is joined in both cases, because its answer is as new as anyone can get.
        """
        now = self._clock.monotonic()
        if not fresh:
            entry = self._entries.get(key)
            if entry is not None:
                if now < entry.expires_at:
                    self._entries.move_to_end(key)
                    return Cached(cast("T", entry.value), "hit", now - entry.stored_at)
                del self._entries[key]
        task = self._loading.get(key)
        if task is None:
            task = asyncio.create_task(self._load(key, ttl, load))
            self._loading[key] = task
        value = await asyncio.shield(task)
        return Cached(cast("T", value), "bypass" if fresh else "miss", 0.0)

    def invalidate(self, prefix: CacheKey) -> int:
        """Forget every answer whose key starts with `prefix`. Returns how many went."""
        doomed = [key for key in self._entries if key[: len(prefix)] == prefix]
        for key in doomed:
            del self._entries[key]
        return len(doomed)

    def clear(self) -> None:
        self._entries.clear()

    async def _load[T](self, key: CacheKey, ttl: float, load: Callable[[], Awaitable[T]]) -> T:
        try:
            value = await load()
            if ttl > 0:
                self._store(key, value, ttl)
            return value
        finally:
            self._loading.pop(key, None)

    def _store(self, key: CacheKey, value: object, ttl: float) -> None:
        now = self._clock.monotonic()
        self._entries[key] = _Entry(value=value, stored_at=now, expires_at=now + ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

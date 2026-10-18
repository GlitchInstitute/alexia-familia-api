"""Time as a dependency, so tests move it by hand and nothing waits for real seconds."""

import asyncio
import time
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The wall clock in UTC. Use it for timestamps that people read."""

    def monotonic(self) -> float:
        """Seconds that never go backwards. Use it to measure gaps."""

    async def sleep(self, seconds: float) -> None:
        """Wait for a number of seconds."""


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class LocalClock:
    """Names the same instants as the clock it wraps, with the offset of one time zone.

    The server wraps its clock once, so every timestamp it makes, such as the time a login
    started, reaches a client in the school's zone like the times that come from the portal.
    """

    def __init__(self, inner: Clock, zone: tzinfo) -> None:
        self._inner = inner
        self._zone = zone

    def now(self) -> datetime:
        return self._inner.now().astimezone(self._zone)

    def monotonic(self) -> float:
        return self._inner.monotonic()

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class ManualClock:
    """A clock that moves only when told to. Sleeping moves it instead of waiting."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)

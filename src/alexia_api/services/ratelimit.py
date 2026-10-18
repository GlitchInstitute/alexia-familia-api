"""A limit on how fast one API key may call this server.

A leaked key could ask for fresh data in a loop. The gateway already spaces requests to the
portal, so the school never sees the burst, but the limit keeps one noisy client from filling
the queue for the others. Each key has a bucket that holds up to a minute of requests and
refills at a steady rate.
"""

from alexia_api.clock import Clock, SystemClock

_SECONDS_PER_MINUTE = 60.0


class RateLimiter:
    def __init__(self, per_minute: int, clock: Clock | None = None) -> None:
        self._capacity = float(per_minute)
        self._refill_per_second = per_minute / _SECONDS_PER_MINUTE
        self._clock = clock or SystemClock()
        self._buckets: dict[str, tuple[float, float]] = {}

    def check(self, who: str) -> float | None:
        """Take one request from the bucket of `who`.

        Returns `None` when the request may go on, and otherwise the number of seconds to wait
        before one will be allowed. A refused request takes nothing, so asking again does not
        make the wait longer. A limit of zero turns the limiter off.
        """
        if self._capacity <= 0:
            return None
        now = self._clock.monotonic()
        tokens, last = self._buckets.get(who, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - last) * self._refill_per_second)
        if tokens >= 1:
            self._buckets[who] = (tokens - 1, now)
            return None
        self._buckets[who] = (tokens, now)
        return (1 - tokens) / self._refill_per_second

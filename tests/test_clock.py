from datetime import UTC, datetime

from alexia_api.clock import ManualClock, SystemClock


def test_the_manual_clock_moves_only_when_told() -> None:
    clock = ManualClock(datetime(2026, 3, 5, 9, 0, tzinfo=UTC))

    assert clock.now() == datetime(2026, 3, 5, 9, 0, tzinfo=UTC)
    assert clock.monotonic() == 0.0

    clock.advance(90)

    assert clock.now() == datetime(2026, 3, 5, 9, 1, 30, tzinfo=UTC)
    assert clock.monotonic() == 90.0


async def test_sleeping_on_the_manual_clock_advances_it_without_waiting() -> None:
    clock = ManualClock()

    await clock.sleep(3600)

    assert clock.monotonic() == 3600.0


async def test_the_system_clock_reports_utc_and_keeps_moving_forward() -> None:
    clock = SystemClock()
    before = clock.monotonic()

    await clock.sleep(0)

    assert clock.now().tzinfo is UTC
    assert clock.monotonic() >= before

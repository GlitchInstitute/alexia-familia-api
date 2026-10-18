from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from alexia_api.clock import LocalClock, ManualClock, SystemClock

MADRID = ZoneInfo("Europe/Madrid")


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


def test_a_local_clock_names_the_same_instant_with_the_offset_of_its_zone() -> None:
    inner = ManualClock(datetime(2026, 1, 15, 8, 0, tzinfo=UTC))
    clock = LocalClock(inner, MADRID)

    winter = clock.now()
    inner.advance(180 * 24 * 3600)
    summer = clock.now()

    assert winter == datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
    assert winter.isoformat() == "2026-01-15T09:00:00+01:00"
    assert summer.isoformat() == "2026-07-14T10:00:00+02:00"


async def test_a_local_clock_leaves_measuring_and_waiting_to_the_clock_it_wraps() -> None:
    inner = ManualClock()
    clock = LocalClock(inner, MADRID)

    await clock.sleep(30)

    assert clock.monotonic() == 30.0
    assert inner.monotonic() == 30.0


async def test_the_system_clock_reports_utc_and_keeps_moving_forward() -> None:
    clock = SystemClock()
    before = clock.monotonic()

    await clock.sleep(0)

    assert clock.now().tzinfo is UTC
    assert clock.monotonic() >= before

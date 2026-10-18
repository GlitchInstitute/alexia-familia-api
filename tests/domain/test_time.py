from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.domain.time import (
    UnknownZoneError,
    instant_of,
    midnight_seconds,
    portal_list_date,
    wall_of,
    window_around,
    zone,
)

MADRID = zone("Europe/Madrid")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("05/03/2026", date(2026, 3, 5)),
        (" 05/03/2026 ", date(2026, 3, 5)),
        ("29/02/2028", date(2028, 2, 29)),
        ("29/02/2026", None),
        ("31/04/2026", None),
        ("5/3/2026", None),
        ("2026-03-05", None),
        ("05/03/26", None),
        ("00/03/2026", None),
        ("", None),
    ],
)
def test_portal_list_date_accepts_only_real_dates_written_day_first(
    text: str, expected: date | None
) -> None:
    assert portal_list_date(text) == expected


@given(st.dates(min_value=date(1, 1, 1)))
def test_portal_list_date_reads_back_every_date_it_is_given(day: date) -> None:
    written = f"{day.day:02}/{day.month:02}/{day.year:04}"
    assert portal_list_date(written) == day


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-03-05T09:30:00Z", datetime(2026, 3, 5, 9, 30)),
        ("2026-03-05T09:30:00", datetime(2026, 3, 5, 9, 30)),
        ("2026-03-05T09:30", datetime(2026, 3, 5, 9, 30)),
        ("2026-03-05T09:30:00.000Z", datetime(2026, 3, 5, 9, 30)),
        ("2026-03-05T24:00:00", None),
        ("2026-03-05T09:60:00", None),
        ("2026-02-30T10:00:00", None),
        ("2026-03-05 09:30:00", None),
        ("2026-03-05", None),
        ("nonsense", None),
    ],
)
def test_wall_of_reads_feed_times_as_local_wall_time(text: str, expected: datetime | None) -> None:
    assert wall_of(text) == expected


def test_instant_of_uses_winter_and_summer_offsets() -> None:
    winter = instant_of(datetime(2026, 1, 15, 9, 0), MADRID)
    summer = instant_of(datetime(2026, 7, 15, 9, 0), MADRID)

    assert winter.astimezone(UTC) == datetime(2026, 1, 15, 8, 0, tzinfo=UTC)
    assert summer.astimezone(UTC) == datetime(2026, 7, 15, 7, 0, tzinfo=UTC)


def test_instant_of_moves_a_time_that_never_happens_one_hour_later() -> None:
    skipped = instant_of(datetime(2026, 3, 29, 2, 30), MADRID)

    assert skipped.astimezone(UTC) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    assert skipped.hour == 3


def test_instant_of_takes_the_first_of_two_identical_wall_times() -> None:
    repeated = instant_of(datetime(2026, 10, 25, 2, 30), MADRID)

    assert repeated.astimezone(UTC) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_instant_of_refuses_a_time_that_already_has_a_zone() -> None:
    with pytest.raises(ValueError, match="carries no zone"):
        instant_of(datetime(2026, 1, 15, 9, 0, tzinfo=UTC), MADRID)


@given(st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2040, 1, 1)))
def test_instant_of_keeps_the_wall_clock_or_shifts_it_by_the_skipped_hour(
    wall: datetime,
) -> None:
    placed = instant_of(wall, MADRID).replace(tzinfo=None)

    assert placed - wall in {timedelta(0), timedelta(hours=1)}


def test_midnight_seconds_is_local_midnight_as_a_unix_time() -> None:
    expected = int(datetime(2026, 1, 14, 23, 0, tzinfo=UTC).timestamp())

    assert midnight_seconds(date(2026, 1, 15), MADRID) == expected


def test_midnight_seconds_follows_the_zone_it_is_given() -> None:
    canary = zone("Atlantic/Canary")

    assert (
        midnight_seconds(date(2026, 1, 15), canary) - midnight_seconds(date(2026, 1, 15), MADRID)
        == 3600
    )


@pytest.mark.parametrize("name", ["Nowhere/City", "../etc/passwd", ""])
def test_zone_rejects_names_the_tz_database_does_not_know(name: str) -> None:
    with pytest.raises(UnknownZoneError):
        zone(name)


def test_window_around_lists_every_day_in_order() -> None:
    window = window_around(date(2026, 3, 5), back=1, ahead=2)

    assert window.days() == [
        date(2026, 3, 4),
        date(2026, 3, 5),
        date(2026, 3, 6),
        date(2026, 3, 7),
    ]


def test_window_overlaps_an_event_that_touches_either_edge() -> None:
    window = window_around(date(2026, 3, 5), back=0, ahead=0)

    assert window.overlaps(datetime(2026, 3, 4, 23, 0), datetime(2026, 3, 5, 0, 0))
    assert window.overlaps(datetime(2026, 3, 5, 23, 59), datetime(2026, 3, 6, 8, 0))
    assert not window.overlaps(datetime(2026, 3, 4, 8, 0), datetime(2026, 3, 4, 9, 0))
    assert not window.overlaps(datetime(2026, 3, 6, 0, 0), datetime(2026, 3, 6, 1, 0))

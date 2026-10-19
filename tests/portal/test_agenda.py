"""Reading the agenda of a child and of the guardian."""

import json
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.domain.agenda import AgendaEvent, AgendaScope, EventKind, LessonSignals
from alexia_api.domain.errors import (
    MAX_DRIFT_SAMPLE_CHARS,
    PortalError,
    SchemaDrift,
    SessionExpired,
    UnexpectedReply,
)
from alexia_api.domain.ids import PersonId, parse_person_id
from alexia_api.domain.time import DateWindow
from alexia_api.portal.agenda import (
    agenda_feed_path,
    agenda_page_path,
    counter_of,
    events_in,
    kind_of,
    normalized,
    parse_feed,
    read_agenda,
)
from alexia_api.portal.wire import FeedEvent, Flag
from alexia_api.sim.agenda import LessonEdit
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_B, default_world, synthetic_guid
from tests.harness import Failure, Harness

MADRID = ZoneInfo("Europe/Madrid")
LUCIA = parse_person_id(synthetic_guid(0x201))
MATEO = parse_person_id(synthetic_guid(0x202))
HUGO = parse_person_id(synthetic_guid(0x211))
MARTA = parse_person_id(synthetic_guid(0x301))
PABLO = parse_person_id(synthetic_guid(0x311))

MONDAY = date(2025, 10, 13)
WEEK = DateWindow(first=MONDAY, last=date(2025, 10, 19))
LESSONS_IN_A_WEEK = 30
NO_FLAGS = LessonSignals(tasks=0, activities=0, notes=0, tests=0, substitution=False)


def window_of(first: date, last: date | None = None) -> DateWindow:
    return DateWindow(first=first, last=last or first)


async def read(
    harness: Harness,
    scope: AgendaScope,
    person: PersonId,
    window: DateWindow,
    *,
    family_b: bool = False,
) -> tuple[AgendaEvent, ...]:
    credentials = harness.credentials(DEMO_USER_B, DEMO_PASSWORD_B) if family_b else None
    gateway = harness.gateway(credentials=credentials)
    return await gateway.call(lambda tx: read_agenda(tx, scope, person, window))


def lucias_first_lesson_slot_id() -> str:
    return default_world().families[0].children[0].timetable[0].id


def feed_event(
    start: str,
    end: str,
    *,
    entry_id: str = "a",
    title: str = "Lesson",
    class_name: str = "evHorario",
    teacher: str | None = None,
    tasks: Flag = None,
    substitution: Flag = None,
) -> FeedEvent:
    return FeedEvent(
        id=entry_id,
        title=title,
        start=start,
        end=end,
        class_name=class_name,
        teacher=teacher,
        tasks=tasks,
        substitution=substitution,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, 0),
        (False, 0),
        (True, 1),
        (0, 0),
        (3, 3),
        (-2, 0),
        (0.0, 0),
        (0.4, 1),
        (2.0, 2),
        (-0.5, 0),
        (float("inf"), 1),
        (float("-inf"), 1),
        (float("nan"), 1),
        ("0", 0),
        ("", 0),
        ("  ", 0),
        ("false", 0),
        ("FALSE", 0),
        ("true", 1),
        (" True ", 1),
        ("2", 2),
        (" 3 ", 3),
        ("2.5", 3),
        ("-1", 0),
        ("1e3", 1000),
        ("nope", 1),
        ("inf", 1),
        ("nan", 1),
    ],
)
def test_a_counter_is_how_many_things_the_school_flagged(value: Flag, expected: int) -> None:
    counted = counter_of(value)

    assert counted == expected
    assert type(counted) is int


@given(st.one_of(st.none(), st.booleans(), st.integers(), st.floats(), st.text()))
def test_a_counter_is_never_negative(value: Flag) -> None:
    assert counter_of(value) >= 0


@given(st.integers(min_value=0, max_value=10**9))
def test_a_number_and_its_text_count_the_same(number: int) -> None:
    assert counter_of(number) == counter_of(str(number)) == number


@pytest.mark.parametrize(
    ("class_name", "title", "kind"),
    [
        ("evHorario", "MATEMÁTICAS", "lesson"),
        ("evHorario", "FESTIVO", "lesson"),
        ("evEntrevista", "Entrevista: Aceptada", "interview"),
        ("evEntrevista", "FESTIVO", "interview"),
        ("evSecundario", "FESTIVO", "holiday"),
        ("evSecundario", "festivo", "holiday"),
        ("evSecundario", "  Festivo  ", "holiday"),
        ("evSecundario", "¡Festivo!", "holiday"),
        ("evSecundario", "Festívo", "holiday"),
        ("evSecundario", "FESTIVOS", "school_event"),
        ("evSecundario", "FESTIVO LOCAL", "school_event"),
        ("evSecundario", "No festivo", "school_event"),
        ("evSecundario", "", "school_event"),
        ("evSecundario", "ESCUELA DE PASCUA", "school_event"),
        ("evOtro", "FESTIVO", "school_event"),
        ("", "FESTIVO", "school_event"),
    ],
)
def test_the_class_and_the_title_decide_what_kind_of_entry_it_is(
    class_name: str, title: str, kind: EventKind
) -> None:
    assert kind_of(class_name, title) == kind


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Festivo", "festivo"),
        ("  A   B  ", "a b"),
        ("Educación Física", "educacion fisica"),
        ("¡Hola, mundo!", "hola mundo"),
        ("ñandú", "nandu"),
        ("a_b-c", "a b c"),
        ("\uff13 ab", "3 ab"),
        ("", ""),
        ("---", ""),
    ],
)
def test_a_title_is_compared_as_lower_case_words_without_accents(title: str, expected: str) -> None:
    assert normalized(title) == expected


def test_the_page_that_opens_an_agenda_names_the_kind_of_agenda_and_the_person() -> None:
    assert agenda_page_path("child", LUCIA) == (
        "/ACWeb/paginas/Agenda/PaginaAgenda.aspx"
        "?master=3&TipoAgenda=7&GuidObjeto=5afe0000-0000-4000-8000-000000000201"
    )
    assert agenda_page_path("guardian", MARTA) == (
        "/ACWeb/paginas/Agenda/PaginaAgenda.aspx"
        "?master=1&TipoAgenda=6&GuidObjeto=5afe0000-0000-4000-8000-000000000301"
    )


def test_the_feed_is_asked_in_unix_seconds_from_midnight_to_midnight_in_madrid() -> None:
    asked_at = datetime(2026, 1, 1, tzinfo=UTC)

    path = agenda_feed_path(WEEK, asked_at, MADRID)

    assert path == (
        "/ACWeb/controladores/ControladorAgenda.ashx"
        "?start=1760306400&end=1760911200&_=1767225600000"
    )


def test_the_seconds_follow_the_offset_that_the_days_have() -> None:
    asked_at = datetime(2026, 1, 1, tzinfo=UTC)
    winter = agenda_feed_path(window_of(date(2026, 1, 15)), asked_at, MADRID)
    across_the_change = agenda_feed_path(window_of(date(2026, 3, 29)), asked_at, MADRID)

    assert "start=1768431600&end=1768518000" in winter
    assert "start=1774738800&end=1774821600" in across_the_change


async def test_a_school_week_has_six_lessons_on_each_weekday(harness: Harness) -> None:
    events = await read(harness, "child", LUCIA, WEEK)

    assert len(events) == LESSONS_IN_A_WEEK
    assert {event.kind for event in events} == {"lesson"}
    days = [event.starts_at.date() for event in events]
    assert {day: days.count(day) for day in sorted(set(days))} == {
        MONDAY + timedelta(days=offset): 6 for offset in range(5)
    }
    assert events == tuple(sorted(events, key=lambda event: (event.starts_at, event.id)))


async def test_a_lesson_has_its_title_teacher_and_times_in_the_zone_of_the_school(
    harness: Harness,
) -> None:
    events = await read(harness, "child", LUCIA, window_of(MONDAY))

    assert events[0] == AgendaEvent(
        id="5afe0000-0000-4000-8000-000000007110|2025-10-13",
        kind="lesson",
        title="Educación Física",
        teacher="Rosa Prueba",
        starts_at=datetime(2025, 10, 13, 9, 0, tzinfo=MADRID),
        ends_at=datetime(2025, 10, 13, 9, 45, tzinfo=MADRID),
        all_day=False,
        signals=NO_FLAGS,
    )
    assert events[0].starts_at.utcoffset() == timedelta(hours=2)


async def test_each_child_has_their_own_week(harness: Harness) -> None:
    lucia = await read(harness, "child", LUCIA, window_of(MONDAY))
    mateo = await read(harness, "child", MATEO, window_of(MONDAY))

    assert (mateo[0].title, mateo[0].teacher) == ("Música", "Tomás Demo")
    assert (lucia[0].title, lucia[0].teacher) != (mateo[0].title, mateo[0].teacher)
    assert {event.id for event in lucia}.isdisjoint({event.id for event in mateo})


async def test_a_lesson_the_school_flags_carries_every_kind_of_flag(harness: Harness) -> None:
    (slot,) = [
        slot
        for slot in default_world().families[0].children[0].timetable
        if (slot.weekday, slot.starts) == (2, "11:00")
    ]
    tuesday = date(2025, 10, 14)
    harness.sim.edit_lesson(
        synthetic_guid(0x201),
        slot.id,
        tuesday,
        LessonEdit(
            counters={
                "tareas": 2,
                "actividades": "1",
                "anotaciones": False,
                "controles": True,
                "is_sustitucion": "true",
            }
        ),
    )

    events = await read(harness, "child", LUCIA, window_of(tuesday))

    flagged = [event for event in events if event.id.startswith(slot.id)]
    assert [event.signals for event in flagged] == [
        LessonSignals(tasks=2, activities=1, notes=0, tests=1, substitution=True)
    ]
    assert [event.signals for event in events if event not in flagged] == [NO_FLAGS] * 5


async def test_a_changed_lesson_shows_the_new_title_teacher_and_times(harness: Harness) -> None:
    harness.sim.edit_lesson(
        synthetic_guid(0x201),
        lucias_first_lesson_slot_id(),
        MONDAY,
        LessonEdit(title="Teatro", teacher="Profesora invitada", starts="10:00", ends="10:50"),
    )

    events = await read(harness, "child", LUCIA, window_of(MONDAY))

    changed = next(event for event in events if event.title == "Teatro")
    assert changed.teacher == "Profesora invitada"
    assert changed.starts_at == datetime(2025, 10, 13, 10, 0, tzinfo=MADRID)
    assert changed.ends_at == datetime(2025, 10, 13, 10, 50, tzinfo=MADRID)
    assert len(events) == 6


async def test_a_change_to_one_day_leaves_the_same_lesson_alone_on_the_next_week(
    harness: Harness,
) -> None:
    harness.sim.edit_lesson(
        synthetic_guid(0x201), lucias_first_lesson_slot_id(), MONDAY, LessonEdit(title="Teatro")
    )

    next_monday = await read(harness, "child", LUCIA, window_of(date(2025, 10, 20)))

    assert "Teatro" not in {event.title for event in next_monday}


async def test_a_cancelled_lesson_is_gone(harness: Harness) -> None:
    slot_id = lucias_first_lesson_slot_id()
    harness.sim.cancel_lesson(synthetic_guid(0x201), slot_id, MONDAY)

    events = await read(harness, "child", LUCIA, window_of(MONDAY))

    assert len(events) == 5
    assert all(not event.id.startswith(slot_id) for event in events)


async def test_a_school_event_of_one_child_is_not_in_the_agenda_of_the_other(
    harness: Harness,
) -> None:
    around = window_of(date(2025, 10, 30))

    lucia = await read(harness, "child", LUCIA, around)
    mateo = await read(harness, "child", MATEO, around)

    (trip,) = [event for event in lucia if event.kind == "school_event"]
    assert trip.title == "EXCURSIÓN AL MUSEO"
    assert trip.teacher is None
    assert trip.signals is None
    assert trip.all_day is False
    assert trip.starts_at == datetime(2025, 10, 30, 9, 30, tzinfo=MADRID)
    assert trip.ends_at == datetime(2025, 10, 30, 14, 0, tzinfo=MADRID)
    assert [event for event in mateo if event.kind != "lesson"] == []


async def test_a_holiday_covers_its_whole_day_whichever_way_the_portal_ends_it(
    harness: Harness,
) -> None:
    ends_at_midnight = await read(harness, "child", LUCIA, window_of(date(2025, 10, 12)))
    ends_at_the_last_minute = await read(harness, "child", LUCIA, window_of(date(2025, 12, 8)))

    (first,) = [event for event in ends_at_midnight if event.kind == "holiday"]
    (second,) = [event for event in ends_at_the_last_minute if event.kind == "holiday"]
    assert first.title == second.title == "FESTIVO"
    assert first.all_day is second.all_day is True
    assert first.starts_at == datetime(2025, 10, 12, 0, 0, tzinfo=MADRID)
    assert first.ends_at == first.starts_at
    assert second.starts_at == datetime(2025, 12, 8, 0, 0, tzinfo=MADRID)
    assert second.ends_at == datetime(2025, 12, 8, 23, 59, tzinfo=MADRID)
    assert first.signals is None


async def test_a_break_of_several_days_is_one_all_day_entry_that_spans_the_new_year(
    harness: Harness,
) -> None:
    window = window_of(date(2025, 12, 20), date(2026, 1, 10))

    (christmas,) = await read(harness, "guardian", MARTA, window)

    assert christmas.title == "VACACIONES DE NAVIDAD"
    assert christmas.kind == "school_event"
    assert christmas.all_day is True
    assert christmas.starts_at == datetime(2025, 12, 23, 0, 0, tzinfo=MADRID)
    assert christmas.ends_at == datetime(2026, 1, 7, 23, 59, tzinfo=MADRID)
    assert christmas.starts_at.utcoffset() == timedelta(hours=1)


async def test_a_trip_of_several_days_with_hours_is_not_an_all_day_entry(
    harness: Harness,
) -> None:
    (camp,) = await read(harness, "guardian", MARTA, window_of(date(2026, 4, 1)))

    assert camp.title == "ESCUELA DE PASCUA"
    assert camp.all_day is False
    assert camp.starts_at == datetime(2026, 3, 30, 9, 0, tzinfo=MADRID)
    assert camp.ends_at == datetime(2026, 4, 2, 17, 0, tzinfo=MADRID)
    assert camp.starts_at.utcoffset() == timedelta(hours=2)


async def test_the_guardian_has_interviews_and_school_events_but_no_lessons(
    harness: Harness,
) -> None:
    marta_window = window_of(date(2025, 10, 13), date(2025, 10, 26))
    pablo_window = window_of(date(2025, 11, 9), date(2025, 11, 15))

    (interview,) = await read(harness, "guardian", MARTA, marta_window)
    (other,) = await read(harness, "guardian", PABLO, pablo_window, family_b=True)

    assert interview.kind == "interview"
    assert interview.title == "Entrevista: Aceptada"
    assert interview.starts_at == datetime(2025, 10, 20, 16, 0, tzinfo=MADRID)
    assert interview.ends_at == datetime(2025, 10, 20, 16, 30, tzinfo=MADRID)
    assert interview.signals is None
    assert other.title == "Entrevista: Pendiente"
    assert other.starts_at == datetime(2025, 11, 10, 17, 0, tzinfo=MADRID)


async def test_the_events_of_the_children_are_not_in_the_agenda_of_the_guardian(
    harness: Harness,
) -> None:
    events = await read(harness, "guardian", MARTA, window_of(date(2025, 10, 30)))

    assert events == ()


async def test_the_agenda_of_a_child_of_another_family_is_not_there_to_open(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()

    detail = await failure(gateway.call(lambda tx: read_agenda(tx, "child", HUGO, WEEK)))

    assert detail == UnexpectedReply(where="page:agenda HTTP 500")


async def test_the_guardian_page_does_not_open_for_a_child_and_the_reverse(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()

    as_child = await failure(gateway.call(lambda tx: read_agenda(tx, "child", MARTA, WEEK)))
    as_guardian = await failure(gateway.call(lambda tx: read_agenda(tx, "guardian", LUCIA, WEEK)))

    assert as_child == as_guardian == UnexpectedReply(where="page:agenda HTTP 500")


async def test_reading_an_agenda_takes_one_page_and_one_feed_request(harness: Harness) -> None:
    await read(harness, "child", LUCIA, WEEK)

    assert harness.requests_to("PaginaAgenda.aspx") == 1
    assert harness.requests_to("ControladorAgenda.ashx") == 1


async def test_the_feed_is_asked_for_the_days_wanted_and_stamped_by_the_clock(
    harness: Harness,
) -> None:
    before = int(harness.clock.now().timestamp() * 1000)

    await read(harness, "child", LUCIA, WEEK)

    after = int(harness.clock.now().timestamp() * 1000)
    (feed,) = [r for r in harness.sim.requests if r.path.endswith("ControladorAgenda.ashx")]
    asked = parse_qs(feed.query)
    assert (asked["start"], asked["end"]) == (["1760306400"], ["1760911200"])
    assert before <= int(asked["_"][0]) <= after


@pytest.mark.parametrize("window", [WEEK, window_of(date(2025, 12, 1), date(2026, 1, 12))])
async def test_what_the_portal_sends_outside_the_days_wanted_is_left_out(
    harness: Harness, window: DateWindow
) -> None:
    quirky = await read(harness, "child", LUCIA, window)
    harness.sim.options.agenda_ignores_end = False
    harness.sim.options.agenda_standing_events = False

    strict = await read(harness, "child", LUCIA, window)

    assert quirky == strict
    assert all(window.first <= event.ends_at.date() for event in quirky)
    assert all(event.starts_at.date() <= window.last for event in quirky)


async def test_a_session_that_ended_is_replaced_and_the_agenda_still_comes(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    await gateway.call(lambda tx: read_agenda(tx, "child", LUCIA, window_of(MONDAY)))
    harness.sim.expire_all_sessions()

    events = await gateway.call(lambda tx: read_agenda(tx, "child", LUCIA, window_of(MONDAY)))

    assert len(events) == 6
    assert harness.sim.counters.login_attempts == 2


async def test_a_feed_that_is_the_logon_page_is_a_session_that_is_gone(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.agenda_not_json = True
    gateway = harness.gateway()

    detail = await failure(gateway.call(lambda tx: read_agenda(tx, "child", LUCIA, WEEK)))

    assert detail == SessionExpired()
    assert harness.sim.counters.login_attempts == 2


async def test_a_feed_that_the_portal_fails_to_build_is_an_unexpected_reply_that_names_it(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.agenda_feed_fails = True
    gateway = harness.gateway()

    detail = await failure(gateway.call(lambda tx: read_agenda(tx, "child", LUCIA, WEEK)))

    assert detail == UnexpectedReply(where="page:agenda-feed HTTP 500")


async def test_an_entry_with_a_start_that_is_not_a_date_is_a_changed_portal(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.agenda_bad_event = True
    gateway = harness.gateway()

    detail = await failure(gateway.call(lambda tx: read_agenda(tx, "child", LUCIA, WEEK)))

    assert isinstance(detail, SchemaDrift)
    assert detail.where == "agenda feed"
    assert "tomorrow morning" in detail.sample


def drift_of(text: str) -> PortalError:
    with pytest.raises(PortalError) as raised:
        parse_feed(text)
    return raised.value


def test_a_feed_that_is_an_empty_list_has_no_entries() -> None:
    assert parse_feed("[]") == []


def test_a_feed_that_is_not_json_and_not_the_logon_page_is_a_changed_portal() -> None:
    error = drift_of("<html><body>Mantenimiento</body></html>")

    assert error.detail == SchemaDrift(
        where="agenda feed is not JSON", sample="<html><body>Mantenimiento</body></html>"
    )


def test_a_feed_that_is_the_logon_page_is_an_ended_session() -> None:
    assert drift_of('<form action="LogOn.aspx"></form>').detail == SessionExpired()
    assert drift_of('<input id="txtUsuario" />').detail == SessionExpired()


GOOD_ENTRY = {
    "id": "a",
    "title": "t",
    "start": "2026-01-01T00:00:00Z",
    "end": "2026-01-01T00:00:00Z",
    "className": "evHorario",
}


def feed_with(**changes: object) -> str:
    return json.dumps([{**GOOD_ENTRY, **changes}])


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        '{"events": []}',
        "null",
        "[1]",
        "[{}]",
        feed_with(start="x"),
        feed_with(end="2026-13-01T00:00:00Z"),
        feed_with(id=""),
        feed_with(id=7),
        feed_with(title=None),
        feed_with(tareas=[]),
        feed_with(seccion=3),
    ],
)
def test_a_feed_in_a_shape_the_portal_never_used_is_a_changed_portal(text: str) -> None:
    error = drift_of(text)

    assert error.detail == SchemaDrift(where="agenda feed", sample=text)


def test_the_sample_of_a_changed_feed_is_cut_to_the_size_that_diagnosis_needs() -> None:
    error = drift_of("<" * (MAX_DRIFT_SAMPLE_CHARS + 10))

    assert isinstance(error.detail, SchemaDrift)
    assert len(error.detail.sample) == MAX_DRIFT_SAMPLE_CHARS


def test_a_feed_entry_may_carry_fields_this_server_does_not_read() -> None:
    (entry,) = parse_feed(
        '[{"id": "a", "title": "t", "start": "2026-01-01T09:00:00Z", '
        '"end": "2026-01-01T10:00:00Z", "className": "evHorario", "color": "#336699", '
        '"editable": false, "pasar_lista": "1", "is_pd": "0", "tareas": 2, '
        '"seccion": "Ana Muestra"}]'
    )

    assert (entry.id, entry.tasks, entry.teacher) == ("a", 2, "Ana Muestra")


def test_the_times_of_a_feed_entry_may_leave_the_seconds_and_the_z_out() -> None:
    (entry,) = parse_feed(
        '[{"id": "a", "title": "t", "start": "2026-01-01T09:00", '
        '"end": "2026-01-01T10:00:00.000", "className": "evHorario"}]'
    )

    assert (entry.start, entry.end) == ("2026-01-01T09:00", "2026-01-01T10:00:00.000")


def test_entries_are_kept_when_they_touch_the_window_and_dropped_when_they_do_not() -> None:
    window = window_of(date(2026, 3, 10), date(2026, 3, 12))
    inside = feed_event("2026-03-11T09:00:00Z", "2026-03-11T10:00:00Z", entry_id="inside")
    before = feed_event("2026-03-09T23:00:00Z", "2026-03-09T23:59:00Z", entry_id="before")
    after = feed_event("2026-03-13T00:00:00Z", "2026-03-13T01:00:00Z", entry_id="after")
    ends_at_the_start = feed_event(
        "2026-03-09T22:00:00Z", "2026-03-10T00:00:00Z", entry_id="edge-in"
    )
    starts_on_the_last_day = feed_event(
        "2026-03-12T23:59:00Z", "2026-03-13T08:00:00Z", entry_id="last"
    )
    covers = feed_event("2026-03-01T00:00:00Z", "2026-03-31T23:59:00Z", entry_id="covers")

    events = events_in(
        [inside, before, after, ends_at_the_start, starts_on_the_last_day, covers],
        window,
        MADRID,
    )

    assert sorted(event.id.split("|")[0] for event in events) == [
        "covers",
        "edge-in",
        "inside",
        "last",
    ]


def test_an_entry_the_portal_repeats_is_kept_once_and_a_weekly_lesson_once_a_week() -> None:
    window = window_of(date(2026, 3, 1), date(2026, 3, 31))
    monday = feed_event("2026-03-02T09:00:00Z", "2026-03-02T09:45:00Z", entry_id="weekly")
    again = feed_event(
        "2026-03-02T09:00:00Z", "2026-03-02T09:45:00Z", entry_id="weekly", title="Copy"
    )
    next_week = feed_event("2026-03-09T09:00:00Z", "2026-03-09T09:45:00Z", entry_id="weekly")

    events = events_in([monday, again, next_week], window, MADRID)

    assert [event.id for event in events] == ["weekly|2026-03-02", "weekly|2026-03-09"]
    assert events[0].title == "Lesson"


def test_entries_come_in_the_order_they_happen_and_ties_go_by_id() -> None:
    window = window_of(date(2026, 3, 1), date(2026, 3, 31))
    late = feed_event("2026-03-02T11:00:00Z", "2026-03-02T11:45:00Z", entry_id="late")
    b = feed_event("2026-03-02T09:00:00Z", "2026-03-02T09:45:00Z", entry_id="b")
    a = feed_event("2026-03-02T09:00:00Z", "2026-03-02T09:45:00Z", entry_id="a")

    events = events_in([late, b, a], window, MADRID)

    assert [event.id for event in events] == ["a|2026-03-02", "b|2026-03-02", "late|2026-03-02"]


def test_the_words_of_an_entry_are_trimmed_and_a_blank_teacher_is_no_teacher() -> None:
    window = window_of(date(2026, 3, 2))
    blank = feed_event("2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z", entry_id="a", teacher="  ")
    named = feed_event(
        "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z", entry_id="b", teacher="  Ana Muestra  "
    )
    spaced = feed_event(
        "2026-03-02T09:00:00Z", "2026-03-02T10:00:00Z", entry_id="c", title="  Trip  "
    )

    events = events_in([blank, named, spaced], window, MADRID)

    by_id = {event.id.split("|")[0]: event for event in events}
    assert by_id["a"].teacher is None
    assert by_id["b"].teacher == "Ana Muestra"
    assert by_id["c"].teacher is None
    assert by_id["c"].title == "Trip"


@pytest.mark.parametrize(
    ("start", "end", "all_day"),
    [
        ("2026-03-02T00:00:00Z", "2026-03-02T00:00:00Z", True),
        ("2026-03-02T00:00:00Z", "2026-03-02T23:59:00Z", True),
        ("2026-03-02T00:00:00Z", "2026-03-05T00:00:00Z", True),
        ("2026-03-02T00:00:00Z", "2026-03-02T23:58:00Z", False),
        ("2026-03-02T00:00:00Z", "2026-03-02T12:00:00Z", False),
        ("2026-03-02T00:01:00Z", "2026-03-02T23:59:00Z", False),
        ("2026-03-02T09:00:00Z", "2026-03-02T09:00:00Z", False),
    ],
)
def test_an_entry_is_all_day_when_it_runs_from_midnight_to_midnight_or_the_last_minute(
    start: str, end: str, all_day: bool
) -> None:
    window = window_of(date(2026, 3, 1), date(2026, 3, 31))

    (event,) = events_in([feed_event(start, end, class_name="evSecundario")], window, MADRID)

    assert event.all_day is all_day


@pytest.mark.parametrize(
    ("day", "start", "expected"),
    [
        (date(2026, 3, 29), "2026-03-29T01:30:00Z", "2026-03-29T01:30:00+01:00"),
        (date(2026, 3, 29), "2026-03-29T03:30:00Z", "2026-03-29T03:30:00+02:00"),
        (date(2026, 3, 29), "2026-03-29T02:30:00Z", "2026-03-29T03:30:00+02:00"),
        (date(2026, 10, 25), "2026-10-25T01:30:00Z", "2026-10-25T01:30:00+02:00"),
        (date(2026, 10, 25), "2026-10-25T02:30:00Z", "2026-10-25T02:30:00+02:00"),
        (date(2026, 10, 25), "2026-10-25T03:30:00Z", "2026-10-25T03:30:00+01:00"),
    ],
)
def test_wall_time_gets_the_offset_that_the_school_has_at_that_time(
    day: date, start: str, expected: str
) -> None:
    (event,) = events_in([feed_event(start, start)], window_of(day), MADRID)

    assert event.starts_at.isoformat() == expected


def test_only_a_lesson_has_signals() -> None:
    window = window_of(date(2026, 3, 2))
    lesson = feed_event(
        "2026-03-02T09:00:00Z",
        "2026-03-02T10:00:00Z",
        entry_id="l",
        tasks=1,
        substitution="true",
    )
    interview = feed_event(
        "2026-03-02T09:00:00Z",
        "2026-03-02T10:00:00Z",
        entry_id="i",
        class_name="evEntrevista",
        tasks=1,
        substitution="true",
    )
    holiday = feed_event(
        "2026-03-02T00:00:00Z",
        "2026-03-02T00:00:00Z",
        entry_id="h",
        title="FESTIVO",
        class_name="evSecundario",
        tasks=1,
        substitution="true",
    )

    events = events_in([lesson, interview, holiday], window, MADRID)

    by_kind = {event.kind: event for event in events}
    assert by_kind["lesson"].signals == LessonSignals(
        tasks=1, activities=0, notes=0, tests=0, substitution=True
    )
    assert by_kind["interview"].signals is None
    assert by_kind["holiday"].signals is None


walls = st.datetimes(min_value=datetime(2026, 2, 20), max_value=datetime(2026, 4, 10)).map(
    lambda value: value.replace(second=0, microsecond=0)
)


def stamp(wall: datetime) -> str:
    return wall.strftime("%Y-%m-%dT%H:%M:%SZ")


@given(
    st.lists(
        st.builds(
            feed_event,
            start=walls.map(stamp),
            end=walls.map(stamp),
            entry_id=st.sampled_from(["a", "b", "c", "d"]),
            class_name=st.sampled_from(["evHorario", "evEntrevista", "evSecundario"]),
        ),
        max_size=25,
    ),
    walls.map(lambda wall: wall.date()),
    st.integers(min_value=0, max_value=20),
)
def test_the_entries_kept_are_the_ones_that_touch_the_window_once_each_and_in_order(
    items: list[FeedEvent], first: date, length: int
) -> None:
    window = window_of(first, first + timedelta(days=length))

    events = events_in(items, window, MADRID)

    expected = {
        f"{item.id}|{item.start[:10]}"
        for item in items
        if window.overlaps(
            datetime.fromisoformat(item.start[:-1]), datetime.fromisoformat(item.end[:-1])
        )
    }
    assert {event.id for event in events} == expected
    assert len({event.id for event in events}) == len(events)
    assert list(events) == sorted(events, key=lambda event: (event.starts_at, event.id))

"""The simulator refuses an agenda request that the real portal would refuse.

The reader tests only mean something if the simulator is as strict as the portal. These tests
send each request wrong, one detail at a time, and expect the portal's error page. They also pin
down what the feed holds, so a change to the simulator's seed shows up here first.
"""

import json
from collections.abc import Callable
from datetime import date

import httpx
import pytest

from alexia_api.portal.session import PortalRequest, PortalResponse, Tx
from alexia_api.sim.agenda import (
    FEED_PATH,
    PAGE_PATH,
    LessonEdit,
    Term,
    asked_days,
    feed_entry,
    feed_seconds,
    page_target,
    page_url,
    stamp,
    term_of,
)
from alexia_api.sim.app import HOME_PATH, LOGON_PATH
from alexia_api.sim.world import synthetic_guid
from tests.harness import Harness

LUCIA = synthetic_guid(0x201)
MATEO = synthetic_guid(0x202)
HUGO = synthetic_guid(0x211)
MARTA = synthetic_guid(0x301)
CHILD_PAGE = f"{PAGE_PATH}?master=3&TipoAgenda=7&GuidObjeto={LUCIA}"
SECOND_CHILD_PAGE = f"{PAGE_PATH}?master=3&TipoAgenda=7&GuidObjeto={MATEO}"
GUARDIAN_PAGE = f"{PAGE_PATH}?master=1&TipoAgenda=6&GuidObjeto={MARTA}"
WEEK_FEED = f"{FEED_PATH}?start=1760306400&end=1760911200&_=1767225600000"
TWO_WEEKS_FEED = f"{FEED_PATH}?start=1760306400&end=1761516000&_=1767225600000"
ONE_DAY_FEED = f"{FEED_PATH}?start=1760306400&end=1760392800&_=1767225600000"
BEFORE_THE_TERM_FEED = f"{FEED_PATH}?start=1756677600&end=1757887200&_=1767225600000"
ACROSS_THE_END_FEED = f"{FEED_PATH}?start=1783893600&end=1785189600&_=1767225600000"
JSON_ACCEPT = "application/json, text/javascript, */*; q=0.01"

BROKEN_PAGES: dict[str, str] = {
    "a person that does not exist": f"master=3&TipoAgenda=7&GuidObjeto={synthetic_guid(0x9999)}",
    "a child of another family": f"master=3&TipoAgenda=7&GuidObjeto={HUGO}",
    "the guardian page with a child": f"master=1&TipoAgenda=6&GuidObjeto={LUCIA}",
    "the child page with the guardian": f"master=3&TipoAgenda=7&GuidObjeto={MARTA}",
    "another kind of agenda": f"master=3&TipoAgenda=6&GuidObjeto={LUCIA}",
    "another master": f"master=2&TipoAgenda=7&GuidObjeto={LUCIA}",
    "an extra field": f"master=3&TipoAgenda=7&GuidObjeto={LUCIA}&extra=1",
    "no person": "master=3&TipoAgenda=7",
    "no query": "",
}

BROKEN_FEEDS: dict[str, Callable[[str], str]] = {
    "no cache buster": lambda path: path.replace("&_=1767225600000", ""),
    "a cache buster that is not a number": lambda path: path.replace("_=1767", "_=x1767"),
    "an extra field": lambda path: f"{path}&extra=1",
    "a start that is not a number": lambda path: path.replace("start=1760306400", "start=monday"),
    "a negative start": lambda path: path.replace("start=1760306400", "start=-5"),
    "an end with too many digits": lambda path: path.replace("end=1760911200", "end=176091120000"),
    "no end": lambda path: path.replace("&end=1760911200", ""),
}


async def request_page(harness: Harness, page: str = CHILD_PAGE) -> PortalResponse:
    async def ask(tx: Tx) -> PortalResponse:
        return await tx.request(
            PortalRequest(
                method="GET",
                path=page,
                headers={"accept": "text/html"},
                referer=tx.absolute(HOME_PATH),
                follow=False,
            )
        )

    return await harness.gateway().call(ask)


async def request_feed(
    harness: Harness,
    *,
    path: str = WEEK_FEED,
    pages: tuple[str, ...] = (CHILD_PAGE,),
    xhr: bool = True,
    referer: str | None = None,
) -> PortalResponse:
    """Open each page in turn, then ask for the feed from the last page unless told otherwise."""

    async def ask(tx: Tx) -> PortalResponse:
        for page in pages:
            await tx.request(
                PortalRequest(
                    method="GET",
                    path=page,
                    headers={"accept": "text/html"},
                    referer=tx.absolute(HOME_PATH),
                    follow=False,
                )
            )
        headers = {"accept": JSON_ACCEPT}
        if xhr:
            headers["x-requested-with"] = "XMLHttpRequest"
        came_from = referer or (pages[-1] if pages else HOME_PATH)
        return await tx.request(
            PortalRequest(
                method="GET",
                path=path,
                headers=headers,
                referer=tx.absolute(came_from),
                follow=False,
            )
        )

    return await harness.gateway().call(ask)


def entries_of(response: PortalResponse) -> list[dict[str, object]]:
    assert response.status == 200
    entries = json.loads(response.text())
    assert isinstance(entries, list)
    return entries


def titles_of(response: PortalResponse) -> set[str]:
    return {str(entry["title"]) for entry in entries_of(response)}


def classes_of(response: PortalResponse) -> set[str]:
    return {str(entry["className"]) for entry in entries_of(response)}


def lesson_ids_of(response: PortalResponse) -> set[str]:
    return {str(e["id"]) for e in entries_of(response) if e["className"] == "evHorario"}


def lesson_days_of(response: PortalResponse) -> set[str]:
    return {str(e["start"])[:10] for e in entries_of(response) if e["className"] == "evHorario"}


async def test_a_page_request_shaped_like_the_portals_own_opens_the_agenda(
    harness: Harness,
) -> None:
    child = await request_page(harness, CHILD_PAGE)
    guardian = await request_page(harness, GUARDIAN_PAGE)

    assert child.status == guardian.status == 200
    assert b'id="calendar"' in child.body
    assert b'id="calendar"' in guardian.body


@pytest.mark.parametrize("how", sorted(BROKEN_PAGES))
async def test_a_page_request_that_is_shaped_wrong_gets_the_error_page(
    harness: Harness, how: str
) -> None:
    response = await request_page(harness, f"{PAGE_PATH}?{BROKEN_PAGES[how]}")

    assert response.status == 500
    assert b"Error" in response.body


async def test_a_feed_request_shaped_like_the_portals_own_gets_a_json_list(
    harness: Harness,
) -> None:
    response = await request_feed(harness)

    assert response.status == 200
    assert isinstance(json.loads(response.text()), list)


@pytest.mark.parametrize("how", sorted(BROKEN_FEEDS))
async def test_a_feed_request_that_is_shaped_wrong_gets_the_error_page(
    harness: Harness, how: str
) -> None:
    response = await request_feed(harness, path=BROKEN_FEEDS[how](WEEK_FEED))

    assert response.status == 500
    assert b"Error" in response.body


async def test_a_feed_asked_for_before_any_agenda_is_opened_gets_the_error_page(
    harness: Harness,
) -> None:
    assert (await request_feed(harness, pages=())).status == 500


async def test_a_feed_request_that_is_not_ajax_gets_the_error_page(harness: Harness) -> None:
    assert (await request_feed(harness, xhr=False)).status == 500


async def test_a_feed_request_that_does_not_come_from_an_agenda_page_gets_the_error_page(
    harness: Harness,
) -> None:
    assert (await request_feed(harness, referer=HOME_PATH)).status == 500


async def test_a_feed_request_must_come_from_the_page_of_the_agenda_that_is_open(
    harness: Harness,
) -> None:
    response = await request_feed(
        harness, pages=(CHILD_PAGE, SECOND_CHILD_PAGE), referer=CHILD_PAGE
    )

    assert response.status == 500


async def test_the_referer_check_can_be_switched_off(harness: Harness) -> None:
    harness.sim.options.require_referer = False

    assert (await request_feed(harness, referer=HOME_PATH)).status == 200


async def test_the_server_remembers_the_agenda_that_was_opened_last(harness: Harness) -> None:
    lucia_then_mateo = await request_feed(harness, pages=(CHILD_PAGE, SECOND_CHILD_PAGE))
    mateo_then_lucia = await request_feed(harness, pages=(SECOND_CHILD_PAGE, CHILD_PAGE))

    assert "SALIDA A LA GRANJA" in titles_of(lucia_then_mateo)
    assert "EXCURSIÓN AL MUSEO" not in titles_of(lucia_then_mateo)
    assert "EXCURSIÓN AL MUSEO" in titles_of(mateo_then_lucia)
    assert "SALIDA A LA GRANJA" not in titles_of(mateo_then_lucia)
    assert lesson_ids_of(lucia_then_mateo).isdisjoint(lesson_ids_of(mateo_then_lucia))


async def test_the_feed_of_a_child_holds_lessons_and_school_events_but_no_interviews(
    harness: Harness,
) -> None:
    response = await request_feed(harness)

    assert classes_of(response) == {"evHorario", "evSecundario"}


async def test_the_feed_of_the_guardian_holds_interviews_and_school_events_but_no_lessons(
    harness: Harness,
) -> None:
    response = await request_feed(harness, pages=(GUARDIAN_PAGE,))

    assert classes_of(response) == {"evEntrevista", "evSecundario"}
    assert "Entrevista: Aceptada" in titles_of(response)


async def test_an_interview_is_sent_only_when_its_day_is_asked_for_unless_the_end_is_ignored(
    harness: Harness,
) -> None:
    ignoring_the_end = await request_feed(harness, path=WEEK_FEED, pages=(GUARDIAN_PAGE,))
    harness.sim.options.agenda_ignores_end = False

    one_week = await request_feed(harness, path=WEEK_FEED, pages=(GUARDIAN_PAGE,))
    two_weeks = await request_feed(harness, path=TWO_WEEKS_FEED, pages=(GUARDIAN_PAGE,))

    assert "Entrevista: Aceptada" in titles_of(ignoring_the_end)
    assert "Entrevista: Aceptada" not in titles_of(one_week)
    assert "Entrevista: Aceptada" in titles_of(two_weeks)


async def test_the_portal_answers_up_to_the_end_of_the_term_whatever_end_is_asked(
    harness: Harness,
) -> None:
    one_day = await request_feed(harness, path=ONE_DAY_FEED)

    lessons = [entry for entry in entries_of(one_day) if entry["className"] == "evHorario"]
    days = {str(entry["start"])[:10] for entry in lessons}
    assert min(days) == "2025-10-13"
    assert max(days) == "2026-07-20"


async def test_there_are_no_lessons_before_the_term_starts(harness: Harness) -> None:
    harness.sim.options.agenda_ignores_end = False

    response = await request_feed(harness, path=BEFORE_THE_TERM_FEED)

    days = lesson_days_of(response)
    assert min(days) == "2025-09-08"
    assert max(days) == "2025-09-12"


async def test_there_are_no_lessons_after_the_term_ends(harness: Harness) -> None:
    harness.sim.options.agenda_ignores_end = False

    response = await request_feed(harness, path=ACROSS_THE_END_FEED)

    days = lesson_days_of(response)
    assert min(days) == "2026-07-13"
    assert max(days) == "2026-07-20"


async def test_the_portal_sends_every_school_event_whatever_range_is_asked(
    harness: Harness,
) -> None:
    one_day = await request_feed(harness, path=ONE_DAY_FEED)
    last_week_of_the_term = await request_feed(harness, path=ACROSS_THE_END_FEED)

    holidays = {"VACACIONES DE NAVIDAD", "ESCUELA DE PASCUA", "FESTIVO"}
    assert holidays <= titles_of(one_day)
    assert holidays <= titles_of(last_week_of_the_term)


async def test_with_the_quirks_off_only_the_range_asked_comes_back(harness: Harness) -> None:
    harness.sim.options.agenda_ignores_end = False
    harness.sim.options.agenda_standing_events = False

    one_day = await request_feed(harness, path=ONE_DAY_FEED)

    entries = entries_of(one_day)
    assert len(entries) == 6
    assert {str(entry["start"])[:10] for entry in entries} == {"2025-10-13"}
    assert classes_of(one_day) == {"evHorario"}


async def test_a_lesson_is_sent_with_every_field_the_portal_sends(harness: Harness) -> None:
    harness.sim.options.agenda_ignores_end = False

    first = entries_of(await request_feed(harness, path=ONE_DAY_FEED))[0]

    assert set(first) == {
        "title",
        "id",
        "start",
        "end",
        "className",
        "editable",
        "color",
        "objetoTipo",
        "objetoGuid",
        "progreso",
        "is_pd",
        "is_sustitucion",
        "actividades",
        "tareas",
        "anotaciones",
        "controles",
        "pasar_lista",
        "seccion",
        "size",
        "aplicarEstilo",
    }
    assert first["start"] == "2025-10-13T09:00:00Z"
    assert first["end"] == "2025-10-13T09:45:00Z"
    assert first["className"] == "evHorario"
    assert first["tareas"] == "0"


async def test_a_flag_the_school_raises_comes_in_the_type_the_simulator_was_told_to_use(
    harness: Harness,
) -> None:
    harness.sim.options.agenda_ignores_end = False
    slot = harness.sim.world.families[0].children[0].timetable[0]
    harness.sim.edit_lesson(LUCIA, slot.id, date(2025, 10, 13), LessonEdit(counters={"tareas": 3}))

    first = entries_of(await request_feed(harness, path=ONE_DAY_FEED))[0]

    assert first["tareas"] == 3
    assert first["controles"] == "0"


async def test_without_a_session_the_visitor_is_sent_to_the_logon_page(harness: Harness) -> None:
    async with httpx.AsyncClient(
        transport=harness.sim.transport(), base_url=harness.sim.base_url
    ) as client:
        page = await client.get(CHILD_PAGE)
        feed = await client.get(WEEK_FEED, headers={"x-requested-with": "XMLHttpRequest"})

    assert page.status_code == feed.status_code == 302
    assert page.headers["location"].startswith(LOGON_PATH)
    assert feed.headers["location"].startswith(LOGON_PATH)
    assert LUCIA not in page.headers["location"]


async def test_the_feed_can_be_made_to_answer_with_the_logon_page(harness: Harness) -> None:
    harness.sim.options.agenda_not_json = True

    response = await request_feed(harness)

    assert response.status == 200
    assert b'id="txtUsuario"' in response.body


async def test_the_first_entry_can_be_made_to_start_at_a_time_that_is_not_one(
    harness: Harness,
) -> None:
    harness.sim.options.agenda_bad_event = True

    entries = entries_of(await request_feed(harness))

    assert entries[0]["start"] == "tomorrow morning"
    assert str(entries[1]["start"]).startswith("2025-")


async def test_the_term_follows_the_clock_of_the_simulator(harness: Harness) -> None:
    assert harness.sim.term == Term(2025)

    harness.clock.advance(60 * 60 * 24 * 270)

    assert harness.sim.term == Term(2026)


@pytest.mark.parametrize(
    ("today", "year"),
    [
        (date(2026, 1, 1), 2025),
        (date(2026, 7, 31), 2025),
        (date(2026, 8, 1), 2026),
        (date(2026, 9, 8), 2026),
        (date(2026, 12, 31), 2026),
    ],
)
def test_the_term_that_a_day_belongs_to_starts_in_the_august_before_it(
    today: date, year: int
) -> None:
    assert term_of(today) == Term(year)


def test_a_term_runs_from_the_eighth_of_september_to_the_twentieth_of_july() -> None:
    term = Term(2025)

    assert (term.first, term.last) == (date(2025, 9, 8), date(2026, 7, 20))
    assert term.on(10, 12) == date(2025, 10, 12)
    assert term.on(9, 1) == date(2025, 9, 1)
    assert term.on(8, 31) == date(2026, 8, 31)
    assert term.on(1, 7) == date(2026, 1, 7)


@pytest.mark.parametrize(
    ("start", "end", "first", "last"),
    [
        (1760306400, 1760911200, date(2025, 10, 13), date(2025, 10, 19)),
        (1760306400, 1760392800, date(2025, 10, 13), date(2025, 10, 13)),
        (1760306400, 1760306401, date(2025, 10, 13), date(2025, 10, 13)),
        (1760306400, 1760306400, date(2025, 10, 13), date(2025, 10, 13)),
        (1760306400, 0, date(2025, 10, 13), date(2025, 10, 13)),
        (1774738800, 1774821600, date(2026, 3, 29), date(2026, 3, 29)),
    ],
)
def test_the_days_a_feed_request_touches_are_the_madrid_days_of_its_seconds(
    start: int, end: int, first: date, last: date
) -> None:
    assert asked_days(start, end) == (first, last)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ({"start": "1", "end": "2", "_": "3"}, (1, 2)),
        ({"start": "1", "end": "2", "_": "1767225600000"}, (1, 2)),
        ({"start": "12345678901", "end": "2", "_": "3"}, (12345678901, 2)),
        ({"start": "123456789012", "end": "2", "_": "3"}, None),
        ({"start": "1", "end": "2"}, None),
        ({"start": "1", "end": "2", "_": "3", "x": "4"}, None),
        ({"start": "-1", "end": "2", "_": "3"}, None),
        ({"start": "1", "end": "", "_": "3"}, None),
        ({"start": "1", "end": "2", "_": "now"}, None),
        ({"start": "1.5", "end": "2", "_": "3"}, None),
        ({}, None),
    ],
)
def test_a_feed_request_is_read_only_when_it_has_exactly_the_three_numbers(
    query: dict[str, str], expected: tuple[int, int] | None
) -> None:
    assert feed_seconds(query) == expected


def test_a_page_request_opens_the_agenda_of_a_child_of_the_family_or_of_the_guardian() -> None:
    children = {LUCIA, MATEO}

    def target(master: str, kind: str, person: str, **more: str) -> object:
        query = {"master": master, "TipoAgenda": kind, "GuidObjeto": person, **more}
        return page_target(query, children, MARTA)

    assert target("3", "7", LUCIA) == ("child", LUCIA)
    assert target("3", "7", MATEO) == ("child", MATEO)
    assert target("1", "6", MARTA) == ("guardian", MARTA)
    assert target("3", "7", HUGO) is None
    assert target("3", "7", MARTA) is None
    assert target("1", "6", LUCIA) is None
    assert target("1", "7", MARTA) is None
    assert target("3", "7", LUCIA, extra="1") is None
    assert page_target({"master": "3"}, children, MARTA) is None


def test_the_page_of_an_agenda_is_what_the_feed_has_to_come_from() -> None:
    assert page_url("child", LUCIA) == CHILD_PAGE
    assert page_url("guardian", MARTA) == GUARDIAN_PAGE


def test_the_portal_writes_local_time_with_a_z_on_the_end() -> None:
    assert stamp(date(2025, 10, 13), "09:00") == "2025-10-13T09:00:00Z"


def test_a_change_to_a_lesson_cannot_name_a_counter_the_portal_does_not_have() -> None:
    with pytest.raises(ValueError, match="no counter named"):
        LessonEdit(counters={"tarea": 1})


def test_an_entry_carries_the_counters_and_lets_a_change_override_them() -> None:
    entry = feed_entry(
        entry_id="a",
        title="t",
        start="2025-10-13T09:00:00Z",
        end="2025-10-13T09:45:00Z",
        class_name="evHorario",
        object_type="18",
        object_guid=synthetic_guid(1),
        counters={"tareas": True},
    )

    assert entry["tareas"] is True
    assert entry["actividades"] == "0"
    assert entry["seccion"] == ""

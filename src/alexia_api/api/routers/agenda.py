"""The agenda of each child and of the guardian, as data and as calendar files."""

from collections import Counter
from datetime import date, timedelta
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query, Response

from alexia_api.api.deps import Services, ServicesDep
from alexia_api.api.errors import ApiError, problem_responses
from alexia_api.api.ics import MEDIA_TYPE, CalendarSource, calendar_entries, render_calendar
from alexia_api.api.params import (
    CACHE_HEADERS,
    MAX_DISTANCE_DAYS,
    FeedAccount,
    FeedChild,
    FoundChild,
    FreshQuery,
    ReadAccount,
    require_near,
    stamp,
)
from alexia_api.api.schemas import Agenda
from alexia_api.domain.agenda import AgendaEvent, EventKind
from alexia_api.domain.children import Child
from alexia_api.domain.ids import StudentId
from alexia_api.domain.time import DateWindow, window_around
from alexia_api.services.cache import Cached, combine

DEFAULT_DAYS: Final = 7
MAX_DAYS: Final = 366
FEED_BACK_DAYS: Final = 14
FEED_AHEAD_DAYS: Final = 180
FEED_LESSON_DAYS: Final = 90
MAX_FEED_DAYS: Final = 366

router = APIRouter(
    prefix="/v1/accounts/{account}",
    tags=["agenda"],
    responses=problem_responses(401, 403, 404, 422, 429, 500, 502, 503, 504),
)

FromQuery = Annotated[
    date | None,
    Query(
        alias="from",
        description=(
            "The first day of the range, written YYYY-MM-DD, counting that day. The default is "
            "today at the school."
        ),
    ),
]
ToQuery = Annotated[
    date | None,
    Query(
        description=(
            "The last day of the range, written YYYY-MM-DD, counting that day. The default is "
            f"{DEFAULT_DAYS - 1} days after `from`, so that the range is a week."
        )
    ),
]
KindQuery = Annotated[
    list[EventKind] | None,
    Query(
        alias="kind",
        description=(
            "Keep only entries of this kind. Repeat the parameter to keep several kinds, as in "
            "`kind=lesson&kind=interview`. Leave it out to keep every kind."
        ),
    ),
]
BackQuery = Annotated[
    int,
    Query(ge=0, le=MAX_FEED_DAYS, description="How many days before today the calendar reaches."),
]
AheadQuery = Annotated[
    int,
    Query(ge=0, le=MAX_FEED_DAYS, description="How many days after today the calendar reaches."),
]
LessonsAheadQuery = Annotated[
    int,
    Query(
        ge=0,
        le=MAX_FEED_DAYS,
        description=(
            "How many days after today lessons are listed. The school's timetable for the far "
            "future is only a guess, and holidays and changes have not reached it, so lessons "
            "stop sooner than the rest."
        ),
    ),
]

CALENDAR_RESPONSE: Final[dict[int | str, dict[str, Any]]] = {
    200: {
        "description": "An iCalendar file.",
        "content": {"text/calendar": {"schema": {"type": "string"}}},
        **CACHE_HEADERS[200],
    }
}

FEED_NOTE: Final = (
    "Calendar apps cannot send a header, so this route also takes the key as `?key=`, but only "
    "a key that holds nothing but the `feed` scope. Make one with "
    "`alexia-api keys create NAME --scope feed`. A key with another scope is refused in a URL "
    "even when it is right, so an address that leaks opens calendars and nothing else. There "
    "is no `fresh` option, because this address is meant to be handed to other software. When "
    "the portal cannot be read, the answer is a problem and not a shorter calendar, so an app "
    "keeps what it had."
)


def resolve_window(today: date, first: date | None, last: date | None) -> DateWindow:
    """The range a request asks for, or a refusal that says what to change.

    A range far from today is refused as well as a long one.
    """
    start = today if first is None else first
    require_near("from", start, today)
    end = start + timedelta(days=DEFAULT_DAYS - 1) if last is None else last
    if end < start:
        raise ApiError(422, "invalid_window", "to must not be before from")
    if (end - start).days + 1 > MAX_DAYS:
        raise ApiError(422, "invalid_window", f"a range may cover at most {MAX_DAYS} days")
    return DateWindow(first=start, last=end)


async def _window_of(
    services: ServicesDep, first: FromQuery = None, to: ToQuery = None
) -> DateWindow:
    return resolve_window(services.today(), first, to)


Window = Annotated[DateWindow, Depends(_window_of)]


def _kept(
    events: tuple[AgendaEvent, ...], kinds: list[EventKind] | None
) -> tuple[AgendaEvent, ...]:
    if kinds is None:
        return events
    return tuple(event for event in events if event.kind in kinds)


def _lessons_until(events: tuple[AgendaEvent, ...], last_day: date) -> tuple[AgendaEvent, ...]:
    return tuple(
        event for event in events if event.kind != "lesson" or event.starts_at.date() <= last_day
    )


def _labels(children: tuple[Child, ...]) -> dict[StudentId, str]:
    """A first name for each child, with the slug added where two children share one."""
    counts = Counter(child.first_name for child in children)
    return {
        child.id: child.first_name
        if counts[child.first_name] == 1
        else f"{child.first_name} ({child.slug})"
        for child in children
    }


def _render(name: str, sources: list[CalendarSource], shared: str, services: Services) -> bytes:
    return render_calendar(
        name,
        calendar_entries(sources, shared=shared),
        zone=services.settings.tzinfo,
        stamped_at=services.clock.now(),
    )


def _file(data: bytes, cached: Cached[object]) -> Response:
    reply = Response(content=data, media_type=MEDIA_TYPE)
    stamp(reply, cached)
    return reply


@router.get(
    "/children/{child}/agenda",
    summary="Show the agenda of a child",
    description=(
        "Needs the `read` scope. Gives the lessons and the school events of one child for a "
        "range of days, earliest first. `from` and `to` are days at the school, written "
        "YYYY-MM-DD, and both count. Without them the range is today and the six days after it. "
        f"A range covers at most {MAX_DAYS} days and lies within {MAX_DISTANCE_DAYS} days of "
        "today. A range that breaks these rules, or that ends before it starts, is refused with "
        "the code `invalid_window`. A lesson names its teacher and carries the numbers the "
        "school flagged for it, which are tasks, activities, notes, and tests, and whether a "
        "substitute teacher takes it. A holiday is a school event whose title the school "
        "writes as `festivo`. A time has the offset the school has on that day, so it reads "
        "the same on both sides of a clock change. The portal answers a range with far more "
        "than was asked for, so the server keeps only the days you asked for. Each range is "
        "stored on its own for a while, and `fresh=true` reads it again. The portal shows one "
        "agenda at a time for a login, so this read waits for the other requests of the same "
        "account."
    ),
    responses=CACHE_HEADERS,
)
async def get_child_agenda(
    account: ReadAccount,
    window: Window,
    found: FoundChild,
    response: Response,
    kinds: KindQuery = None,
    fresh: FreshQuery = False,
) -> Agenda:
    events = await account.agenda(found.value, window, fresh=fresh)
    stamp(response, events)
    return Agenda(from_=window.first, to=window.last, items=_kept(events.value, kinds))


@router.get(
    "/guardian/agenda",
    summary="Show the agenda of the guardian",
    description=(
        "Needs the `read` scope. Gives the interviews with the school and the school events "
        "that the portal shows the guardian, for a range of days, earliest first. The range "
        "works as it does for a child, down to the `invalid_window` refusal. A login for which "
        "the portal lists no guardian has no "
        "such agenda, and the answer is a 404 with the code `guardian_not_found`. `fresh=true` "
        "also reads the list of children again, so a guardian that the portal has just begun to "
        "list is found."
    ),
    responses=CACHE_HEADERS,
)
async def get_guardian_agenda(
    account: ReadAccount,
    window: Window,
    response: Response,
    kinds: KindQuery = None,
    fresh: FreshQuery = False,
) -> Agenda:
    events = await account.guardian_agenda(window, fresh=fresh)
    stamp(response, events)
    return Agenda(from_=window.first, to=window.last, items=_kept(events.value, kinds))


@router.get(
    "/children/{child}/agenda.ics",
    summary="Subscribe to the calendar of a child",
    description=(
        "Needs the `feed` scope, which every other scope includes. Gives an iCalendar file that "
        "a calendar app can subscribe to, with the lessons, the school events, and the holidays "
        "of one child. It reaches back `back` days and ahead `ahead` days from today at the "
        "school, and it lists lessons only for the next `lessons_ahead` days. A holiday or any "
        "other entry that lasts all day shows as free time. A lesson says its teacher and what "
        f"the school flagged for it. {FEED_NOTE}"
    ),
    response_class=Response,
    responses=CALENDAR_RESPONSE,
)
async def get_child_calendar(
    account: FeedAccount,
    found: FeedChild,
    services: ServicesDep,
    back: BackQuery = FEED_BACK_DAYS,
    ahead: AheadQuery = FEED_AHEAD_DAYS,
    lessons_ahead: LessonsAheadQuery = FEED_LESSON_DAYS,
) -> Response:
    today = services.today()
    child = found.value
    events = await account.agenda(child, window_around(today, back, ahead))
    source = CalendarSource(
        scope=child.person_id,
        label=None,
        events=_lessons_until(events.value, today + timedelta(days=lessons_ahead)),
    )
    name = f"{child.first_name} school calendar"
    return _file(_render(name, [source], child.person_id, services), events)


@router.get(
    "/guardian/agenda.ics",
    summary="Subscribe to the calendar of the guardian",
    description=(
        "Needs the `feed` scope, which every other scope includes. Gives an iCalendar file with "
        "the interviews and the school events that the portal shows the guardian. It reaches "
        "back `back` days and ahead `ahead` days from today at the school. A login for which "
        "the portal lists no guardian has no such calendar, and the answer is a 404 with the "
        f"code `guardian_not_found`. {FEED_NOTE}"
    ),
    response_class=Response,
    responses=CALENDAR_RESPONSE,
)
async def get_guardian_calendar(
    account: FeedAccount,
    services: ServicesDep,
    back: BackQuery = FEED_BACK_DAYS,
    ahead: AheadQuery = FEED_AHEAD_DAYS,
) -> Response:
    events = await account.guardian_agenda(window_around(services.today(), back, ahead))
    source = CalendarSource(scope=account.account, label=None, events=events.value)
    name = f"{account.label} school meetings"
    return _file(_render(name, [source], account.account, services), events)


@router.get(
    "/agenda.ics",
    summary="Subscribe to one calendar for the whole family",
    description=(
        "Needs the `feed` scope, which every other scope includes. Gives one iCalendar file "
        "with the lessons and school events of every child of the account and the guardian's "
        "interviews. Each entry of a child starts with the child's first name, or with the first "
        "name and the slug when two children share a first name. A holiday that the whole school "
        "shares appears once and has no name in front of it. Lessons stop after `lessons_ahead` "
        "days, as for a single child. The file is all or nothing, so one child whose agenda "
        "cannot be read fails the whole file, and a calendar app does not take the missing "
        f"entries for entries that the school removed. {FEED_NOTE}"
    ),
    response_class=Response,
    responses=CALENDAR_RESPONSE,
)
async def get_family_calendar(
    account: FeedAccount,
    services: ServicesDep,
    back: BackQuery = FEED_BACK_DAYS,
    ahead: AheadQuery = FEED_AHEAD_DAYS,
    lessons_ahead: LessonsAheadQuery = FEED_LESSON_DAYS,
) -> Response:
    today = services.today()
    window = window_around(today, back, ahead)
    last_lesson = today + timedelta(days=lessons_ahead)
    listing = await account.directory()
    labels = _labels(listing.value.children)
    answers: list[Cached[tuple[AgendaEvent, ...]]] = []
    sources: list[CalendarSource] = []
    for child in listing.value.children:
        answer = await account.agenda(child, window)
        answers.append(answer)
        events = _lessons_until(answer.value, last_lesson)
        sources.append(CalendarSource(child.person_id, labels[child.id], events))
    guardian = listing.value.guardian
    if guardian is not None:
        answer = await account.guardian_agenda(window)
        answers.append(answer)
        sources.append(CalendarSource(guardian.person_id, None, answer.value))
    name = f"{account.label} family school calendar"
    data = _render(name, sources, account.account, services)
    return _file(data, combine(data, listing, *answers))

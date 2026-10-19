"""The meetings of a child with the school, and the hours that staff offers for new ones."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response

from alexia_api.api.deps import ServicesDep
from alexia_api.api.errors import problem_responses
from alexia_api.api.params import (
    CACHE_HEADERS,
    MAX_DISTANCE_DAYS,
    FoundChild,
    FreshQuery,
    ReadAccount,
    require_near,
    stamp,
)
from alexia_api.api.schemas import AvailableDays, AvailableHours, MeetingList

router = APIRouter(
    prefix="/v1/accounts/{account}/children/{child}",
    tags=["meetings"],
    responses=problem_responses(401, 403, 404, 422, 429, 500, 502, 503, 504),
)

MonthQuery = Annotated[
    str | None,
    Query(
        pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$",
        description=(
            "The month to look at, written YYYY-MM. The default is the current month at the "
            f"school. The month must start within {MAX_DISTANCE_DAYS} days of today."
        ),
    ),
]
StaffPath = Annotated[
    str,
    Path(
        description=(
            "The id of a member of the staff, as the staff list of the same child shows it. "
            "Letter case does not matter."
        )
    ),
]
DayPath = Annotated[date, Path(description="The day to look at, written YYYY-MM-DD.")]


def resolve_month(today: date, text: str | None) -> tuple[int, int]:
    """The year and the month a request asks for, or a refusal that says what to change."""
    if text is None:
        return today.year, today.month
    year, month = (int(part) for part in text.split("-"))
    require_near("month", date(year, month, 1), today)
    return year, month


@router.get(
    "/meetings",
    summary="List the meetings of a child",
    description=(
        "Needs the `read` scope. This is the list on the portal's page of meetings for the "
        "child, in the order the meetings take place, oldest first. Each meeting has a `state`, "
        "which this server reads from the word the portal prints, and that word in "
        "`state_label`. Only the word `Aceptada` has been seen on a real list. A word that this "
        "server does not know reads as `unknown`, so branch on `state_label` for those. A "
        "meeting that a school holds for a whole group has been seen with the start 00:00 and "
        "the time of day in `note`. A time has the offset the school has on that day. This "
        "server only reads the list. Asking for a meeting, answering one, and cancelling one "
        "happen in the portal. A row that is worded in a way the server does not know fails "
        "with `portal_changed`."
    ),
    responses=CACHE_HEADERS,
)
async def list_meetings(
    account: ReadAccount, found: FoundChild, response: Response, fresh: FreshQuery = False
) -> MeetingList:
    meetings = await account.meetings(found.value, fresh=fresh)
    stamp(response, meetings)
    return MeetingList(items=meetings.value)


@router.get(
    "/staff/{staff}/availability",
    summary="List the days on which a member of the staff has a free hour",
    description=(
        "Needs the `read` scope. Gives the days of one month on which a member of the staff has "
        "at least one free hour for a meeting, earliest first and each day once. `staff` is an "
        "id from the staff list of the same child, and any other id is a 404 with the code "
        "`staff_not_found`. `month` is written YYYY-MM and defaults to the current month at the "
        f"school. A month that starts more than {MAX_DISTANCE_DAYS} days from today is refused "
        "with the code `invalid_window`. The answer belongs to the person, so two children who "
        "share a teacher share the stored answer. It is kept for a minute by default, because "
        "other guardians book hours too, and `fresh=true` reads it again. An empty list means "
        "that nothing is free in that month. This server only reads the hours. Asking for a "
        "meeting happens in the portal."
    ),
    responses=CACHE_HEADERS,
)
async def list_available_days(
    account: ReadAccount,
    found: FoundChild,
    staff: StaffPath,
    services: ServicesDep,
    response: Response,
    month: MonthQuery = None,
    fresh: FreshQuery = False,
) -> AvailableDays:
    year, number = resolve_month(services.today(), month)
    days = await account.available_days(found.value, staff, year, number, fresh=fresh)
    stamp(response, days)
    return AvailableDays(month=f"{year:04d}-{number:02d}", items=days.value)


@router.get(
    "/staff/{staff}/availability/{day}",
    summary="List the free slots of a member of the staff on one day",
    description=(
        "Needs the `read` scope. Gives the free slots of a member of the staff on one day, "
        "earliest first, each with a start and an end that carry the school's offset. `staff` "
        "and the way the answer is kept work as they do for the days of a month. `day` is "
        f"written YYYY-MM-DD, and a day more than {MAX_DISTANCE_DAYS} days from today is "
        "refused with the code `invalid_window`. An empty list means that nothing is free on "
        "that day. This server only reads the hours. Asking for a meeting happens in the "
        "portal."
    ),
    responses=CACHE_HEADERS,
)
async def list_available_hours(
    account: ReadAccount,
    found: FoundChild,
    staff: StaffPath,
    day: DayPath,
    services: ServicesDep,
    response: Response,
    fresh: FreshQuery = False,
) -> AvailableHours:
    require_near("day", day, services.today())
    slots = await account.available_hours(found.value, staff, day, fresh=fresh)
    stamp(response, slots)
    return AvailableHours(day=day, items=slots.value)

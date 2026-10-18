"""The children of an account, and what the portal shows about each one."""

from fastapi import APIRouter, Response

from alexia_api.api.errors import problem_responses
from alexia_api.api.params import CACHE_HEADERS, FoundChild, FreshQuery, ReadAccount, stamp
from alexia_api.api.schemas import ChildList, StaffList
from alexia_api.domain.children import Child, TrackingCounters

router = APIRouter(
    prefix="/v1/accounts/{account}/children",
    tags=["children"],
    responses=problem_responses(401, 403, 404, 429, 500, 502, 503, 504),
)


@router.get(
    "",
    summary="List the children of an account",
    description=(
        "Needs the `read` scope. Each child has a student id and a slug, and either one works "
        "in the other child routes. The list is stored for a while, so ask with `fresh=true` "
        "after a sibling joins the school."
    ),
    responses=CACHE_HEADERS,
)
async def list_children(
    account: ReadAccount, response: Response, fresh: FreshQuery = False
) -> ChildList:
    listing = await account.directory(fresh=fresh)
    stamp(response, listing)
    return ChildList(items=listing.value.children)


@router.get(
    "/{child}",
    summary="Show one child",
    description=(
        "Needs the `read` scope. The child is found in the list the portal gave for this "
        "account, so a student id that belongs to another account is not found."
    ),
    responses=CACHE_HEADERS,
)
async def get_child(found: FoundChild, response: Response) -> Child:
    stamp(response, found)
    return found.value


@router.get(
    "/{child}/tracking",
    summary="Show the tracking counters of a child",
    description=(
        "Needs the `read` scope. These are the five numbers in the portal's tracking widget, "
        "which count open tasks, activities, notes, tests, and incidents."
    ),
    responses=CACHE_HEADERS,
)
async def get_tracking(
    account: ReadAccount, found: FoundChild, response: Response, fresh: FreshQuery = False
) -> TrackingCounters:
    counters = await account.tracking(found.value, fresh=fresh)
    stamp(response, counters)
    return counters.value


@router.get(
    "/{child}/staff",
    summary="List the staff a guardian can meet about a child",
    description=(
        "Needs the `read` scope. These are the teachers and other staff the portal offers for "
        "a meeting request. Each one has an id that meeting requests use."
    ),
    responses=CACHE_HEADERS,
)
async def list_staff(
    account: ReadAccount, found: FoundChild, response: Response, fresh: FreshQuery = False
) -> StaffList:
    staff = await account.staff(found.value, fresh=fresh)
    stamp(response, staff)
    return StaffList(items=staff.value)

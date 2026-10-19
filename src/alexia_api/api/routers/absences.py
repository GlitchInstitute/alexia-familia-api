"""The absences and other attendance incidents that the portal lists for a child."""

from fastapi import APIRouter, Response

from alexia_api.api.errors import problem_responses
from alexia_api.api.params import CACHE_HEADERS, FoundChild, FreshQuery, ReadAccount, stamp
from alexia_api.api.schemas import AbsenceList

router = APIRouter(
    prefix="/v1/accounts/{account}/children/{child}/absences",
    tags=["absences"],
    responses=problem_responses(401, 403, 404, 429, 500, 502, 503, 504),
)


@router.get(
    "",
    summary="List the absences of a child",
    description=(
        "Needs the `read` scope. This is the list on the portal's page for justifying absences, "
        "newest day first. Most entries are absences. Some are other incidents, such as a late "
        "arrival, so read `incident` for what happened and `justifiable` to see whether the "
        "portal lets a guardian justify it. The portal decides which days the list covers. Its "
        "page filters by the current month, so older absences may be missing, and an empty list "
        "does not prove that a child has none. This server only reads the list. A guardian "
        "justifies an absence in the portal itself. No real list of incidents has been read "
        "while building this route, so a row that is worded in a way the server does not know "
        "fails with `portal_changed`."
    ),
    responses=CACHE_HEADERS,
)
async def list_absences(
    account: ReadAccount, found: FoundChild, response: Response, fresh: FreshQuery = False
) -> AbsenceList:
    absences = await account.absences(found.value, fresh=fresh)
    stamp(response, absences)
    return AbsenceList(items=absences.value)

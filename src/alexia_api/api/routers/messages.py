"""The message folders of an account and the messages in them."""

from typing import Annotated, Final

from fastapi import APIRouter, Query, Response

from alexia_api.api.errors import problem_responses
from alexia_api.api.params import CACHE_HEADERS, FreshQuery, ReadAccount, stamp
from alexia_api.api.schemas import FolderList, MessagePage
from alexia_api.domain.messages import FolderName, MessageSummary

DEFAULT_LIMIT: Final = 25
MAX_LIMIT: Final = 100

router = APIRouter(
    prefix="/v1/accounts/{account}",
    tags=["messages"],
    responses=problem_responses(401, 403, 404, 429, 500, 502, 503, 504),
)

FolderQuery = Annotated[FolderName, Query(description="Which folder to list.")]
UnreadQuery = Annotated[
    bool | None,
    Query(
        description=(
            "`true` keeps the messages that are not known to be read. `false` keeps the ones "
            "that were read. Leave it out to keep every message."
        )
    ),
]
LimitQuery = Annotated[
    int, Query(ge=1, le=MAX_LIMIT, description="The most messages to return in one page.")
]
OffsetQuery = Annotated[int, Query(ge=0, description="How many matching messages to skip.")]


def _matching(
    messages: tuple[MessageSummary, ...], unread: bool | None
) -> tuple[MessageSummary, ...]:
    if unread is None:
        return messages
    return tuple(message for message in messages if (message.read is not True) == unread)


@router.get(
    "/folders",
    summary="List the message folders of an account",
    description=(
        "Needs the `read` scope. This server serves the received and the sent folders. The "
        "`count` of a folder is the number the portal prints after its name. The portal does "
        "not say whether it counts every message or only the unread ones, so use it as a hint."
    ),
    responses=CACHE_HEADERS,
)
async def list_folders(
    account: ReadAccount, response: Response, fresh: FreshQuery = False
) -> FolderList:
    folders = await account.folders(fresh=fresh)
    stamp(response, folders)
    return FolderList(items=folders.value)


@router.get(
    "/messages",
    summary="List the messages in a folder",
    description=(
        "Needs the `read` scope. Messages come newest first, a page at a time. The portal "
        "belongs to the guardian and not to a child, so the list holds the messages for every "
        "child of the account. The server reads the whole folder from the portal once and "
        "stores it, so paging through it costs the portal a single read. Ask with `fresh=true` "
        "to see a message that arrived a moment ago."
    ),
    responses=CACHE_HEADERS,
)
async def list_messages(
    account: ReadAccount,
    response: Response,
    folder: FolderQuery = "received",
    unread: UnreadQuery = None,
    limit: LimitQuery = DEFAULT_LIMIT,
    offset: OffsetQuery = 0,
    fresh: FreshQuery = False,
) -> MessagePage:
    listing = await account.messages(folder, fresh=fresh)
    stamp(response, listing)
    matching = _matching(listing.value.messages, unread)
    page = matching[offset : offset + limit]
    after = offset + len(page)
    return MessagePage(
        items=page,
        total=len(matching),
        limit=limit,
        offset=offset,
        next_offset=after if after < len(matching) else None,
        truncated=listing.value.truncated,
    )

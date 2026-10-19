"""The message folders of an account and the messages in them."""

from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query, Response

from alexia_api.api.errors import problem_responses
from alexia_api.api.files import content_disposition
from alexia_api.api.params import CACHE_HEADERS, FreshQuery, ReadAccount, stamp
from alexia_api.api.schemas import FolderList, MessagePage
from alexia_api.domain.messages import FolderName, Message, MessageSummary

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
MessageFolderQuery = Annotated[
    FolderName,
    Query(description="The folder the message is in. A message the family sent is in `sent`."),
]
MessagePath = Annotated[
    str,
    Path(
        description=(
            "The message's id, as the list of messages shows it. Letter case does not matter."
        )
    ),
]
AttachmentPath = Annotated[
    str,
    Path(
        description=(
            "The file's id, as the `attachments` of the message show it. Use it as it is, "
            "because it is an opaque token and not the portal's own id."
        )
    ),
]
FILE_RESPONSE: Final[dict[int | str, dict[str, Any]]] = {
    200: {
        "description": "The file itself.",
        "content": {"*/*": {"schema": {"type": "string", "format": "binary"}}},
        "headers": {
            "Content-Disposition": {
                "description": (
                    "Always `attachment`, with the file's name in a form that is safe to save "
                    "under."
                ),
                "schema": {"type": "string"},
            },
        },
    },
}


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


@router.get(
    "/messages/{message}",
    summary="Read one message",
    description=(
        "Needs the `read` scope. Gives the message as the list shows it, together with when the "
        "school sent it, its words, the addresses in them, and its files. The message must be in "
        "the list of the folder you name, so a message the family sent needs `folder=sent`. "
        "`body.html` is safe to show, and `body.text` holds the same words as plain text. The "
        "server stores a message after it reads it, so asking again is cheap. `fresh=true` reads "
        "the message again, and the list of its folder too. Opening a message in the portal may "
        "mark it as read there, and this server cannot tell whether it does. The `read` field "
        "comes from the list, so it shows the state from before the message was opened."
    ),
    responses=CACHE_HEADERS,
)
async def get_message(
    account: ReadAccount,
    message: MessagePath,
    response: Response,
    folder: MessageFolderQuery = "received",
    fresh: FreshQuery = False,
) -> Message:
    found = await account.message(folder, message, fresh=fresh)
    stamp(response, found)
    return found.value


@router.get(
    "/messages/{message}/attachments/{attachment}",
    summary="Download one file of a message",
    description=(
        "Needs the `read` scope. Gives the bytes of one file that the `attachments` of the "
        "message list. The server fetches the file from the portal every time and keeps nothing, "
        "so you always get the file as it is now. The message must be in the list of the folder "
        "you name, so a message the family sent needs `folder=sent`. A file larger than the "
        "operator's `max_attachment_mib` is refused with a 413 and the code "
        "`attachment_too_large`. The portal sends every file as a plain stream of bytes, so the "
        "`Content-Type` is judged from the first bytes of the file. A web page or a vector "
        "picture is never named as one. It comes as `text/plain`, so a client that shows a file "
        "by its type cannot be made to run it. The answer always asks the client to save the "
        "file. `fresh=true` reads the list of the message's folder again, which a message that "
        "arrived a moment ago needs."
    ),
    response_class=Response,
    responses={**problem_responses(413), **FILE_RESPONSE},
)
async def download_attachment(
    account: ReadAccount,
    message: MessagePath,
    attachment: AttachmentPath,
    folder: MessageFolderQuery = "received",
    fresh: FreshQuery = False,
) -> Response:
    download = await account.attachment(folder, message, attachment, fresh=fresh)
    return Response(
        content=download.data,
        media_type=download.media_type,
        headers={"Content-Disposition": content_disposition(download.name)},
    )

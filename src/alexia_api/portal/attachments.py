"""Downloading one file of a message."""

from typing import Final
from urllib.parse import quote

from alexia_api.domain.errors import AttachmentTooLarge, PortalError, UnexpectedReply
from alexia_api.domain.ids import AttachmentId, portal_file_id
from alexia_api.domain.media import Download, sniff_media_type
from alexia_api.domain.messages import FolderName, MessageSummary
from alexia_api.portal.message import message_path, read_reply
from alexia_api.portal.pages import PageRequest, get_page
from alexia_api.portal.session import Tx

REPOSITORY_PATH: Final = "/ACWeb/Controladores/ControladorRepositorio.ashx"
ANY_TYPE: Final = "*/*"
_ALSO_LEFT_AS_IS: Final = "!*'()"


def _component(value: str) -> str:
    """Escape the way a browser's `encodeURIComponent` does, which is what the portal expects.

    `quote` already leaves letters, digits, and the marks `-_.~` alone. The browser leaves five
    more.
    """
    return quote(value, safe=_ALSO_LEFT_AS_IS)


def attachment_path(file_id: str, name: str) -> str:
    """The address that serves one file, from the portal's id for it and the name it lists."""
    return f"{REPOSITORY_PATH}?tipo=6&nombre={_component(file_id)}&alias={_component(name)}"


async def download_attachment(
    tx: Tx, folder: FolderName, summary: MessageSummary, token: AttachmentId, limit: int
) -> Download | None:
    """Fetch one file of a message of a folder, or None when the message does not list it any more.

    The portal serves the files of the message that the session has open, so the message is opened
    again and its page is read again. That also shows the files as they are now, and a file the
    school took away or replaced is found out before any bytes move. The portal answers a failed
    download with a web page and a status of 200, so a page, a size that differs from the list,
    and a file over the limit are all refused.
    """
    reply = await read_reply(tx, folder, summary)
    wanted = portal_file_id(token)
    file = next((item for item in reply.files if item.id == wanted), None)
    if file is None:
        return None
    if file.size > limit:
        raise PortalError(AttachmentTooLarge(limit=limit))
    response = await get_page(
        tx,
        PageRequest(
            name="attachment",
            path=attachment_path(file.id, file.name),
            referer=tx.absolute(message_path(summary.id)),
            accept=ANY_TYPE,
            max_bytes=limit,
        ),
    )
    if "text/html" in response.headers.get("content-type", "").lower():
        raise PortalError(UnexpectedReply(where="the file came back as a web page"))
    if len(response.body) != file.size:
        raise PortalError(UnexpectedReply(where="the file is not the size the message lists"))
    return Download(
        name=file.name,
        media_type=sniff_media_type(response.body, file.name),
        data=response.body,
    )

"""Reading the forms that the school asks a guardian to answer.

The portal lists the forms on its message page when that page is opened for them, and it keeps
the choice for the rest of the session. A read therefore switches the list to the forms, reads
it, and switches it back. The page says in a hidden input which list it shows, and the reader
checks that before it trusts a list, because a portal that ignored the address would otherwise
give the messages under the name of forms. These steps follow the script of the message page.
They have not been run against a real portal.
"""

import asyncio
from dataclasses import dataclass
from typing import Final

from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.errors import PortalError, UnexpectedReply
from alexia_api.domain.forms import FormContent, FormSummary
from alexia_api.domain.ids import FormId
from alexia_api.domain.messages import MessageSummary
from alexia_api.portal import wire
from alexia_api.portal.allowlist import SELECT_FOLDER
from alexia_api.portal.body import render_body
from alexia_api.portal.folders import FOLDER_IDS, select_folder
from alexia_api.portal.inbox import DEFAULT_PAGE_SIZE, MAX_PAGES, read_pages
from alexia_api.portal.message import child_names_of, read_reply, sent_at_of
from alexia_api.portal.pages import COMUNICADOS_PAGE, PAGE_ACCEPT, PageRequest, get_page
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws

FORMS_PAGE: Final = f"{COMUNICADOS_PAGE}?autorizaciones=1"
LIST_FIELD: Final = "hidIsAutorizacion"
"""The hidden input of the message page that says whether the page lists forms."""


@dataclass(frozen=True, slots=True)
class FormFeed:
    """Every form of the portal's list, newest first."""

    forms: tuple[FormSummary, ...]
    truncated: bool


def form_of(row: MessageSummary) -> FormSummary:
    """A row of the forms list. The grid is the message grid, and a form keeps what it needs."""
    return FormSummary(
        id=FormId(row.id),
        subject=row.subject,
        sender=row.sender,
        received_on=row.received_on,
        expires_on=row.expires_on,
        category=row.category,
    )


def lists_forms(html: str) -> bool | None:
    """Whether the message page says that it lists forms, or None when it says nothing.

    The portal sets the input to 1 when the address asks for the forms. A page can prefix the
    name of an input that sits inside another control, so the end of the name is what counts.
    """
    field = LexborHTMLParser(html).css_first(
        f'input[id$="{LIST_FIELD}"], input[name$="{LIST_FIELD}"]'
    )
    value = field.attributes.get("value") if field is not None else None
    return None if value is None else value == "1"


async def _open_message_page(tx: Tx, name: str, path: str) -> bool | None:
    response = await get_page(
        tx,
        PageRequest(
            name=name, path=path, referer=tx.absolute(COMUNICADOS_PAGE), accept=PAGE_ACCEPT
        ),
    )
    return lists_forms(response.text())


async def enter_forms(tx: Tx) -> None:
    """Open the message page for the forms, check that it lists them, and choose the folder."""
    if await _open_message_page(tx, "forms", FORMS_PAGE) is not True:
        raise PortalError(UnexpectedReply(where="forms page does not say that it lists forms"))
    await call_ws(
        tx,
        SELECT_FOLDER,
        wire.SelectFolderParams(folder_id=FOLDER_IDS["received"], is_authorization="1"),
    )


async def leave_forms(tx: Tx) -> None:
    """Open the plain message page again, check that it lists no forms, and choose the folder.

    The plain page is not known to carry the input, so only a page that says it lists forms is
    refused.
    """
    if await _open_message_page(tx, "forms-leave", COMUNICADOS_PAGE) is True:
        raise PortalError(UnexpectedReply(where="message page still lists forms"))
    await select_folder(tx, "received")


async def read_forms(
    tx: Tx, *, page_size: int = DEFAULT_PAGE_SIZE, max_pages: int = MAX_PAGES
) -> FormFeed:
    """Read the forms the portal lists, then switch its list back to the messages.

    A read that stops anywhere between the two switches cannot tell which list the session
    shows. The session is dropped then, so the next request logs in again and starts on messages.
    """
    try:
        await enter_forms(tx)
        feed = await read_pages(tx, page_size=page_size, max_pages=max_pages)
        await leave_forms(tx)
    except BaseException:
        tx.clear_cookies()
        raise
    return FormFeed(forms=tuple(form_of(row) for row in feed.messages), truncated=feed.truncated)


async def read_form(tx: Tx, summary: FormSummary) -> FormContent:
    """Read the words of one form from the page that opens it.

    The page is opened with the list on messages, as it is for a message, and with the received
    folder shown. The portal may mark the form read when its page opens. Whether it does is not
    known.
    """
    reply = await read_reply(tx, "received", summary)
    rendered = await asyncio.to_thread(render_body, reply.text_1)
    return FormContent(
        sent_at=sent_at_of(reply, tx.zone),
        body=rendered.body,
        links=rendered.links,
        child_names=child_names_of(reply),
    )

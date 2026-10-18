"""Reading one message. The list gives its row and the message page gives the rest."""

import asyncio
from datetime import datetime
from typing import Literal

from alexia_api.domain.errors import PortalError, SchemaDrift, UnexpectedReply, sample_of
from alexia_api.domain.ids import MessageId, attachment_token
from alexia_api.domain.messages import Attachment, MessageContent, MessageSummary, Translation
from alexia_api.domain.time import instant_of, wall_of
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_MESSAGE_DATA
from alexia_api.portal.body import Rendered, render_body
from alexia_api.portal.pages import (
    COMUNICADO_PAGE,
    COMUNICADOS_PAGE,
    PAGE_ACCEPT,
    PageRequest,
    get_page,
)
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws


def message_path(guid: MessageId) -> str:
    """The address of the page that shows one message to read it."""
    return (
        f"{COMUNICADO_PAGE}?GuidComunicadoOrigen={guid}&TipoComunicado=N&AccionComunicado=1"
        "&DestsInicialesCom=&TxtDefaultCom=&AccionExtraCom="
    )


async def open_message(tx: Tx, guid: MessageId) -> None:
    """Open the page of a message. The portal remembers which message the session has open."""
    await get_page(
        tx,
        PageRequest(
            name="message",
            path=message_path(guid),
            referer=tx.absolute(COMUNICADOS_PAGE),
            accept=PAGE_ACCEPT,
        ),
    )


def _tidy(text: str) -> str:
    return " ".join(text.split())


def _same_text(left: str, right: str) -> bool:
    """Equal when spaces and capitals are ignored, or when one starts with the other.

    Every text starts with nothing, so a blank counts only against another blank. Otherwise a
    page with no subject would match any row.
    """
    first, second = _tidy(left).casefold(), _tidy(right).casefold()
    if not first or not second:
        return first == second
    return first.startswith(second) or second.startswith(first)


def _wall_of(reply: wire.MessageReply) -> datetime:
    wall = wall_of(f"{reply.published_on}T{reply.published_at}")
    if wall is None:
        raise PortalError(
            SchemaDrift(
                where="message publication time",
                sample=sample_of(f"{reply.published_on} {reply.published_at}"),
            )
        )
    return wall


def _require_the_row(summary: MessageSummary, reply: wire.MessageReply, wall: datetime) -> None:
    """Refuse a page that is not the message the list row describes.

    The portal remembers the open message in the session, so a page can show another message
    than the one that was asked for. Serving it would put one message's words under another
    message's id.
    """
    same = (
        wall.date() == summary.received_on
        and _same_text(reply.subject_1, summary.subject)
        and (not reply.sender or _same_text(reply.sender, summary.sender))
    )
    if not same:
        raise PortalError(UnexpectedReply(where="message page does not match the list row"))


def _translations(reply: wire.MessageReply) -> tuple[Translation, ...]:
    versions: tuple[tuple[Literal[2, 3], str, str], ...] = (
        (2, reply.subject_2, reply.text_2),
        (3, reply.subject_3, reply.text_3),
    )
    return tuple(
        Translation(slot=slot, subject=_tidy(subject), body=render_body(text).body)
        for slot, subject, text in versions
        if subject.strip() or text.strip()
    )


def _render(reply: wire.MessageReply) -> tuple[Rendered, tuple[Translation, ...]]:
    return render_body(reply.text_1), _translations(reply)


async def read_message(tx: Tx, summary: MessageSummary) -> MessageContent:
    """Open a message and read its page.

    The portal may mark the message read when its page opens. Whether it does is not known.
    """
    await open_message(tx, summary.id)
    reply = await call_ws(
        tx, GET_MESSAGE_DATA, wire.EmptyParams(), referer=tx.absolute(message_path(summary.id))
    )
    wall = _wall_of(reply)
    _require_the_row(summary, reply, wall)
    # A large body takes a second of CPU to clean. A thread keeps the other accounts moving.
    main, translations = await asyncio.to_thread(_render, reply)
    return MessageContent(
        sent_at=instant_of(wall, tx.zone),
        body=main.body,
        links=main.links,
        attachments=tuple(
            Attachment(id=attachment_token(file.id), name=file.name, size=file.size)
            for file in reply.files
        ),
        translations=translations,
        child_names=_tidy(reply.child_names) or None,
        can_reply=reply.can_reply,
    )

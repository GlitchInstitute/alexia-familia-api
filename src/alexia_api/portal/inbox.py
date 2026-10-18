"""Reading the message list. The portal serves it as a grid with eleven cells per row."""

import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.errors import PortalError, SchemaDrift, sample_of
from alexia_api.domain.ids import InvalidIdError, MessageId, parse_message_id
from alexia_api.domain.messages import FolderName, MessageSummary
from alexia_api.domain.time import portal_list_date
from alexia_api.portal.folders import select_folder
from alexia_api.portal.grid import GridRow, cell_text, is_empty_cell, parse_grid_json
from alexia_api.portal.pages import COMUNICADOS_PAGE, FEED_ACCEPT, PageRequest, get_page
from alexia_api.portal.session import Tx

FEED_CELLS: Final = 11
GRID_ID: Final = "ctl00_ContenidoPagina_ctl00_GridComunicados"
DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGES: Final = 200

_NOT_READ: Final = re.compile(r"\bno\s+le[ií]do\b")
_READ: Final = re.compile(r"\ble[ií]do\b")


@dataclass(frozen=True, slots=True)
class FeedPage:
    page: int
    pages: int
    records: int
    rows: tuple[MessageSummary, ...]


@dataclass(frozen=True, slots=True)
class Feed:
    """Every message of one folder, newest first."""

    records: int
    messages: tuple[MessageSummary, ...]
    truncated: bool


def _is_true(html: str) -> bool:
    return html.strip().lower() == "true"


def _read_state(html: str) -> bool | None:
    image = LexborHTMLParser(html).css_first("img")
    attributes = image.attributes if image is not None else {}
    alt = (attributes.get("alt") or "").lower()
    src = (attributes.get("src") or "").lower()
    if _NOT_READ.search(alt) or "sobre_cerrado" in src:
        return False
    if _READ.search(alt) or "sobre_abierto" in src:
        return True
    return None


def _message_id(text: str) -> MessageId | None:
    try:
        return parse_message_id(text)
    except InvalidIdError:
        return None


def parse_feed_row(row: GridRow, index: int, page_text: str) -> MessageSummary:
    def drift(what: str) -> PortalError:
        return PortalError(
            SchemaDrift(where=f"feed row {index}: {what}", sample=sample_of(page_text))
        )

    if len(row.cell) != FEED_CELLS:
        raise drift(f"{len(row.cell)} cells instead of {FEED_CELLS}")
    cells = [cell for cell in row.cell if isinstance(cell, str)]
    if len(cells) != FEED_CELLS:
        raise drift("a cell is not text")

    message_id = _message_id(cells[0])
    if message_id is None or message_id != _message_id(row.id):
        raise drift("the row id and the first cell disagree")
    received_on = portal_list_date(cell_text(cells[6]))
    if received_on is None:
        raise drift("received date")
    expires_text = cell_text(cells[7])
    expires_on = portal_list_date(expires_text)
    if expires_text and expires_on is None:
        raise drift("expiry date")

    return MessageSummary(
        id=message_id,
        read=_read_state(cells[1]),
        institutional=_is_true(cells[2]),
        sender=cell_text(cells[4]),
        subject=cell_text(cells[5]),
        received_on=received_on,
        expires_on=expires_on,
        anonymous=_is_true(cells[8]),
        category=cell_text(cells[9]) or None,
        has_attachments=not is_empty_cell(cells[10]),
    )


def parse_feed_page(text: str) -> FeedPage:
    grid = parse_grid_json(text, "feed page")
    return FeedPage(
        page=grid.page,
        pages=grid.total,
        records=grid.records,
        rows=tuple(parse_feed_row(row, index, text) for index, row in enumerate(grid.rows)),
    )


async def read_feed_page(tx: Tx, *, rows: int, page: int) -> FeedPage:
    query = urlencode(
        {
            "jqGridID": GRID_ID,
            "_search": "false",
            "nd": int(tx.now().timestamp() * 1000),
            "rows": rows,
            "page": page,
            "sidx": "FechaInicio",
            "sord": "desc",
        }
    )
    response = await get_page(
        tx,
        PageRequest(
            name="feed",
            path=f"{COMUNICADOS_PAGE}?{query}",
            referer=tx.absolute(COMUNICADOS_PAGE),
            accept=FEED_ACCEPT,
            xhr=True,
        ),
    )
    return parse_feed_page(response.text())


async def read_feed(
    tx: Tx,
    folder: FolderName,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int = MAX_PAGES,
) -> Feed:
    """Read every page of a folder. Pages past `max_pages` are left unread.

    The portal lists whichever folder its session shows, so the folder is chosen first.
    """
    await select_folder(tx, folder)
    first = await read_feed_page(tx, rows=page_size, page=1)
    messages = list(first.rows)
    for page in range(2, min(first.pages, max_pages) + 1):
        messages.extend((await read_feed_page(tx, rows=page_size, page=page)).rows)
    return Feed(records=first.records, messages=tuple(messages), truncated=first.pages > max_pages)

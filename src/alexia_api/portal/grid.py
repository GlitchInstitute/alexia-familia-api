"""Reading the grid pages of the portal, and the HTML inside their cells.

A grid page is the portal's table of rows. The list of messages is one, and the per-child lists of
absences and meetings are two more. Each one answers JSON that holds a row id and a list of cells
per row, and each cell is a small piece of HTML.

The per-child grids need two steps, in the order the portal's own page makes them. A page request
tells the server which child is open, and a second request, that the page's script would make,
reads the rows. A reader always makes both.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from urllib.parse import urlencode

from pydantic import ValidationError
from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.errors import PortalError, SchemaDrift, SessionExpired, sample_of
from alexia_api.domain.ids import StudentId
from alexia_api.portal import wire
from alexia_api.portal.pages import FEED_ACCEPT, PAGE_ACCEPT, PageRequest, get_page
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import HOME_PATH, looks_like_logon_page

GRID_ROWS: Final = 500
"""How many rows one read asks for. A school year of absences or of meetings is far below it."""

_EMPTY_CELL: Final = re.compile(r"(?:&nbsp;?|\s)*", re.IGNORECASE)
_YES_WORDS: Final = frozenset({"true", "sí", "si", "1"})
_NO_WORDS: Final = frozenset({"false", "no", "0"})


class GridRow(wire.WireModel):
    id: str
    cell: list[object]


class GridJson(wire.WireModel):
    """The shape of a grid answer. `total` counts pages and `records` counts rows."""

    page: int
    total: int
    records: int
    rows: list[GridRow]


@dataclass(frozen=True, slots=True)
class GridSpec:
    """One of the portal's per-child grid pages, named by what the portal calls it."""

    name: str
    page: str
    grid_id: str
    sort: str
    order: Literal["asc", "desc"]


def is_empty_cell(html: str) -> bool:
    """True for a cell that holds only spaces and `&nbsp`. The portal leaves out the semicolon."""
    return _EMPTY_CELL.fullmatch(html) is not None


def cell_text(html: str) -> str:
    """The words in a cell, with entities decoded and white space folded to single spaces."""
    if is_empty_cell(html):
        return ""
    return " ".join(LexborHTMLParser(html).text().split())


def cell_flag(html: str) -> bool | None:
    """Whether a cell says yes, or no, or neither.

    The portal writes a yes as a ticked box, as `True`, as `Sí`, or as `1`, and writes a no as
    an unticked box, as `False`, as `No`, or as `0`. Anything else is not a flag, and the caller
    decides what that means.
    """
    box = LexborHTMLParser(html).css_first("input")
    if box is not None and "checked" in box.attributes:
        return True
    text = cell_text(html).lower()
    if text in _YES_WORDS:
        return True
    if text in _NO_WORDS or (text == "" and box is not None):
        return False
    return None


def parse_grid_json(text: str, what: str) -> GridJson:
    """Read a grid answer. A logon page where JSON should be means the session ended."""
    try:
        decoded = json.loads(text)
    except ValueError:
        if looks_like_logon_page(text):
            raise PortalError(SessionExpired()) from None
        raise PortalError(
            SchemaDrift(where=f"{what} is not JSON", sample=sample_of(text))
        ) from None
    try:
        return GridJson.model_validate(decoded)
    except ValidationError:
        raise PortalError(SchemaDrift(where=what, sample=sample_of(text))) from None


def row_drift(what: str, index: int, detail: str, page_text: str) -> PortalError:
    """The error for a row that is not shaped as the grid's rows are."""
    return PortalError(
        SchemaDrift(where=f"{what} row {index}: {detail}", sample=sample_of(page_text))
    )


def text_cells(row: GridRow, *, what: str, index: int, count: int, page_text: str) -> list[str]:
    """The cells of a row, after checking that there are `count` of them and all are text."""
    if len(row.cell) != count:
        raise row_drift(what, index, f"{len(row.cell)} cells instead of {count}", page_text)
    cells = [cell for cell in row.cell if isinstance(cell, str)]
    if len(cells) != count:
        raise row_drift(what, index, "a cell is not text", page_text)
    return cells


def _child_query(student: StudentId) -> dict[str, str]:
    return {"GuidObjeto": student, "ObjetoTipo": "6", "master": "3", "contexto_pagina": "1"}


def grid_page_path(spec: GridSpec, student: StudentId) -> str:
    """The page that opens a grid for one child, which the feed has to come after."""
    return f"{spec.page}?{urlencode(_child_query(student))}"


def grid_feed_path(spec: GridSpec, student: StudentId, asked_at: datetime) -> str:
    """The request the page's script makes for the rows. `nd` is the browser's cache buster."""
    query = {
        **_child_query(student),
        "jqGridID": spec.grid_id,
        "_search": "false",
        "nd": int(asked_at.timestamp() * 1000),
        "rows": GRID_ROWS,
        "page": 1,
        "sidx": spec.sort,
        "sord": spec.order,
    }
    return f"{spec.page}?{urlencode(query)}"


async def read_grid_text(tx: Tx, spec: GridSpec, student: StudentId) -> str:
    """Open a grid for a child and read its rows, as the text of the portal's answer."""
    page = grid_page_path(spec, student)
    await get_page(
        tx,
        PageRequest(
            name=f"{spec.name}-page",
            path=page,
            referer=tx.absolute(HOME_PATH),
            accept=PAGE_ACCEPT,
        ),
    )
    feed = await get_page(
        tx,
        PageRequest(
            name=f"{spec.name}-feed",
            path=grid_feed_path(spec, student, tx.now()),
            referer=tx.absolute(page),
            accept=FEED_ACCEPT,
            xhr=True,
        ),
    )
    return feed.text()

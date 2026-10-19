"""The per-child grid pages of the simulated portal, which are the absences and the meetings.

Like the rest of the simulator this repeats the portal's names as literals and imports nothing
from `alexia_api.portal`. A grid page has two requests. The page request makes the server remember
which child is open, and the feed request reads the rows of that child. This simulator answers a
feed that comes without its page, or for another child, with no rows and no error. Nobody has seen
what the real portal does then. The choice makes a reader that skips the page fail a test, because
its answer would be an empty list.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

SimGridOrder = Literal["asc", "desc"]

PAGE_PARAMETERS: Final = frozenset({"GuidObjeto", "ObjetoTipo", "master", "contexto_pagina"})
FEED_PARAMETERS: Final = PAGE_PARAMETERS | {
    "jqGridID",
    "_search",
    "nd",
    "rows",
    "page",
    "sidx",
    "sord",
}
_CHILD_CONTEXT: Final[Mapping[str, str]] = {
    "ObjetoTipo": "6",
    "master": "3",
    "contexto_pagina": "1",
}


@dataclass(frozen=True, slots=True)
class SimGrid:
    """One grid page: where it is, what its table is called, and how it sorts."""

    path: str
    grid_id: str
    sort: str
    order: SimGridOrder


@dataclass(frozen=True, slots=True)
class GridAsk:
    """What a feed request asks for."""

    child: str
    rows: int
    page: int


def page_url(grid: SimGrid, child: str) -> str:
    """The page that opens a grid for one child, which the feed has to come from."""
    return f"{grid.path}?GuidObjeto={child}&ObjetoTipo=6&master=3&contexto_pagina=1"


def page_child(query: Mapping[str, str]) -> str | None:
    """The child that a page request opens, or None when the portal would not serve the request."""
    if set(query) != PAGE_PARAMETERS:
        return None
    if any(query[name] != value for name, value in _CHILD_CONTEXT.items()):
        return None
    return query["GuidObjeto"]


def feed_ask(grid: SimGrid, query: Mapping[str, str]) -> GridAsk | None:
    """What a feed request asks for, or None when the portal would not serve the request."""
    if set(query) != FEED_PARAMETERS:
        return None
    child = page_child({name: query[name] for name in PAGE_PARAMETERS})
    numbers = all(query[name].isdecimal() for name in ("nd", "rows", "page"))
    sorted_as_the_page_sorts = (query["sidx"], query["sord"]) == (grid.sort, grid.order)
    shaped = (
        child is not None
        and numbers
        and query["jqGridID"] == grid.grid_id
        and query["_search"] == "false"
        and sorted_as_the_page_sorts
    )
    if not shaped or child is None:
        return None
    rows, page = int(query["rows"]), int(query["page"])
    if rows < 1 or page < 1:
        return None
    return GridAsk(child=child, rows=rows, page=page)


def answer(rows: Sequence[object], ask: GridAsk) -> dict[str, object]:
    """The grid's JSON for one page of rows, which are in the order the page sorts them."""
    first = (ask.page - 1) * ask.rows
    return {
        "page": ask.page,
        "total": math.ceil(len(rows) / ask.rows),
        "records": len(rows),
        "rows": list(rows[first : first + ask.rows]),
        "userdata": {},
    }


def resized(cells: list[str], count: int | None) -> list[str]:
    """The cells cut or padded to `count`, for a test that makes the portal add a column."""
    if count is None:
        return cells
    return [cells[index] if index < len(cells) else "" for index in range(count)]


def checkbox(checked: bool) -> str:
    """A box the way the portal writes one in a read-only grid."""
    state = 'checked="checked" ' if checked else ""
    value = str(checked).lower()
    return f'<input type="checkbox" {state}value="{value}" offval="no" disabled="true"/>'

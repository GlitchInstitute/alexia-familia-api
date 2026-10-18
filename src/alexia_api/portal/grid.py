"""Reading the JSON that the portal's grid pages send, and the HTML inside its cells."""

import json
import re
from typing import Final

from pydantic import ValidationError
from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.errors import PortalError, SchemaDrift, SessionExpired, sample_of
from alexia_api.portal import wire
from alexia_api.portal.ws import looks_like_logon_page

_EMPTY_CELL: Final = re.compile(r"(?:&nbsp;?|\s)*", re.IGNORECASE)


class GridRow(wire.WireModel):
    id: str
    cell: list[object]


class GridJson(wire.WireModel):
    """The shape of a grid answer. `total` counts pages and `records` counts rows."""

    page: int
    total: int
    records: int
    rows: list[GridRow]


def is_empty_cell(html: str) -> bool:
    """True for a cell that holds only spaces and `&nbsp`. The portal leaves out the semicolon."""
    return _EMPTY_CELL.fullmatch(html) is not None


def cell_text(html: str) -> str:
    """The words in a cell, with entities decoded and white space folded to single spaces."""
    if is_empty_cell(html):
        return ""
    return " ".join(LexborHTMLParser(html).text().split())


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

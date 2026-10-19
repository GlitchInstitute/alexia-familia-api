"""The simulator refuses a grid request that the real portal would refuse.

The reader tests only mean something if the simulator is as strict as the portal. These tests
send each request wrong, one detail at a time, and expect the portal's error page. They also pin
down how the simulator behaves between requests, because it answers a feed that came without its
page with no rows and no error. A reader that forgets the page would then pass for an empty list
unless a test expects rows.
"""

import json
from dataclasses import dataclass
from urllib.parse import urlencode

import pytest

from alexia_api.portal.session import PortalRequest, PortalResponse, Tx
from alexia_api.sim import absences
from alexia_api.sim.app import HOME_PATH, LOGON_PATH
from alexia_api.sim.grids import SimGrid, page_url
from alexia_api.sim.world import DEMO_USER_A, synthetic_guid
from tests.harness import Harness

LUCIA = synthetic_guid(0x101)
MATEO = synthetic_guid(0x102)
HUGO = synthetic_guid(0x111)
JSON_ACCEPT = "application/json, text/javascript, */*; q=0.01"
PAGE_ACCEPT = "text/html"


@dataclass(frozen=True)
class GridCase:
    """A grid, a child of the first family who has rows in it, and a sibling who has none."""

    grid: SimGrid
    field: str
    filled: str
    empty: str
    sample: object


CASES = [
    pytest.param(
        GridCase(
            grid=absences.GRID,
            field="absences",
            filled=MATEO,
            empty=LUCIA,
            sample=absences.SimAbsence(
                id=synthetic_guid(0x7599), date="2026-10-01", incident="Falta de asistencia"
            ),
        ),
        id="absences",
    )
]

BROKEN_PAGES: dict[str, dict[str, str | None]] = {
    "a child that does not exist": {"GuidObjeto": synthetic_guid(0x9999)},
    "a child of another family": {"GuidObjeto": HUGO},
    "no child": {"GuidObjeto": None},
    "another object type": {"ObjetoTipo": "7"},
    "another master": {"master": "2"},
    "another context": {"contexto_pagina": "2"},
    "no object type": {"ObjetoTipo": None},
    "an extra field": {"extra": "1"},
}

BROKEN_FEEDS: dict[str, dict[str, str | None]] = {
    "another table": {"jqGridID": "gridDeOtraPagina"},
    "no table": {"jqGridID": None},
    "a search": {"_search": "true"},
    "a cache buster that is not a number": {"nd": "x1767225600000"},
    "no cache buster": {"nd": None},
    "rows that are not a number": {"rows": "many"},
    "no rows": {"rows": "0"},
    "a negative number of rows": {"rows": "-5"},
    "a page that is not a number": {"page": "first"},
    "page zero": {"page": "0"},
    "a column that is not in the grid": {"sidx": "Otra"},
    "no column": {"sidx": None},
    "no direction": {"sord": None},
    "a child that does not exist": {"GuidObjeto": synthetic_guid(0x9999)},
    "a child of another family": {"GuidObjeto": HUGO},
    "an extra field": {"extra": "1"},
}


def path_with(grid: SimGrid, query: dict[str, str | None]) -> str:
    """A request path from a query in which a value of None means the field is left out."""
    return f"{grid.path}?{urlencode({name: value for name, value in query.items() if value})}"


def page_path(grid: SimGrid, student: str, **changes: str | None) -> str:
    query: dict[str, str | None] = {
        "GuidObjeto": student,
        "ObjetoTipo": "6",
        "master": "3",
        "contexto_pagina": "1",
    }
    return path_with(grid, {**query, **changes})


def feed_path(grid: SimGrid, student: str, **changes: str | None) -> str:
    query: dict[str, str | None] = {
        "GuidObjeto": student,
        "ObjetoTipo": "6",
        "master": "3",
        "contexto_pagina": "1",
        "jqGridID": grid.grid_id,
        "_search": "false",
        "nd": "1767225600000",
        "rows": "500",
        "page": "1",
        "sidx": grid.sort,
        "sord": grid.order,
    }
    return path_with(grid, {**query, **changes})


async def ask_page(harness: Harness, path: str) -> PortalResponse:
    async def ask(tx: Tx) -> PortalResponse:
        return await tx.request(
            PortalRequest(
                method="GET",
                path=path,
                headers={"accept": PAGE_ACCEPT},
                referer=tx.absolute(HOME_PATH),
                follow=False,
            )
        )

    return await harness.gateway().call(ask)


async def ask_feed(
    harness: Harness,
    grid: SimGrid,
    *,
    pages: tuple[str, ...],
    student: str = MATEO,
    path: str | None = None,
    xhr: bool = True,
    referer: str | None = None,
) -> PortalResponse:
    """Open each page in turn, then ask for the feed from the last page unless told otherwise."""

    async def ask(tx: Tx) -> PortalResponse:
        for opened in pages:
            await tx.request(
                PortalRequest(
                    method="GET",
                    path=page_url(grid, opened),
                    headers={"accept": PAGE_ACCEPT},
                    referer=tx.absolute(HOME_PATH),
                    follow=False,
                )
            )
        headers = {"accept": JSON_ACCEPT}
        if xhr:
            headers["x-requested-with"] = "XMLHttpRequest"
        came_from = referer or (page_url(grid, pages[-1]) if pages else HOME_PATH)
        return await tx.request(
            PortalRequest(
                method="GET",
                path=path or feed_path(grid, student),
                headers=headers,
                referer=tx.absolute(came_from),
                follow=False,
            )
        )

    return await harness.gateway().call(ask)


def grid_of(response: PortalResponse) -> dict[str, object]:
    assert response.status == 200
    grid = json.loads(response.text())
    assert isinstance(grid, dict)
    return grid


def rows_of(response: PortalResponse) -> list[dict[str, object]]:
    rows = grid_of(response)["rows"]
    assert isinstance(rows, list)
    return rows


@pytest.mark.parametrize("case", CASES)
async def test_a_page_request_shaped_like_the_portals_own_opens_the_grid(
    harness: Harness, case: GridCase
) -> None:
    response = await ask_page(harness, page_path(case.grid, case.filled))

    assert response.status == 200
    assert b"<table" in response.body


@pytest.mark.parametrize("how", sorted(BROKEN_PAGES))
@pytest.mark.parametrize("case", CASES)
async def test_a_page_request_that_is_shaped_wrong_gets_the_error_page(
    harness: Harness, case: GridCase, how: str
) -> None:
    response = await ask_page(harness, page_path(case.grid, case.filled, **BROKEN_PAGES[how]))

    assert response.status == 500
    assert b"Error" in response.body


@pytest.mark.parametrize("case", CASES)
async def test_a_feed_request_shaped_like_the_portals_own_gets_the_grid_as_json(
    harness: Harness, case: GridCase
) -> None:
    response = await ask_feed(harness, case.grid, pages=(case.filled,), student=case.filled)

    grid = grid_of(response)
    assert grid["page"] == 1
    assert grid["total"] == 1
    assert grid["records"] == len(rows_of(response)) > 0
    assert grid["userdata"] == {}


@pytest.mark.parametrize("how", sorted(BROKEN_FEEDS))
@pytest.mark.parametrize("case", CASES)
async def test_a_feed_request_that_is_shaped_wrong_gets_the_error_page(
    harness: Harness, case: GridCase, how: str
) -> None:
    path = feed_path(case.grid, case.filled, **BROKEN_FEEDS[how])

    response = await ask_feed(harness, case.grid, path=path, pages=(case.filled,))

    assert response.status == 500
    assert b"Error" in response.body


@pytest.mark.parametrize("case", CASES)
async def test_a_feed_that_asks_for_the_other_direction_gets_the_error_page(
    harness: Harness, case: GridCase
) -> None:
    other = "asc" if case.grid.order == "desc" else "desc"
    path = feed_path(case.grid, case.filled, sord=other)

    response = await ask_feed(harness, case.grid, path=path, pages=(case.filled,))

    assert response.status == 500


@pytest.mark.parametrize("case", CASES)
async def test_a_feed_request_that_is_not_ajax_gets_the_error_page(
    harness: Harness, case: GridCase
) -> None:
    response = await ask_feed(harness, case.grid, pages=(case.filled,), xhr=False)

    assert response.status == 500


@pytest.mark.parametrize("case", CASES)
async def test_a_feed_request_must_come_from_the_page_of_its_own_child(
    harness: Harness, case: GridCase
) -> None:
    from_the_home = await ask_feed(
        harness, case.grid, pages=(case.filled,), student=case.filled, referer=HOME_PATH
    )
    from_a_sibling = await ask_feed(
        harness,
        case.grid,
        pages=(case.filled, case.empty),
        student=case.filled,
        referer=page_url(case.grid, case.empty),
    )

    assert from_the_home.status == from_a_sibling.status == 500


@pytest.mark.parametrize("case", CASES)
async def test_the_referer_check_can_be_switched_off(harness: Harness, case: GridCase) -> None:
    harness.sim.options.require_referer = False

    response = await ask_feed(
        harness, case.grid, pages=(case.filled,), student=case.filled, referer=HOME_PATH
    )

    assert response.status == 200


@pytest.mark.parametrize("case", CASES)
async def test_a_feed_that_comes_without_its_page_is_empty_and_not_an_error(
    harness: Harness, case: GridCase
) -> None:
    response = await ask_feed(
        harness, case.grid, pages=(), student=case.filled, referer=page_url(case.grid, case.filled)
    )

    grid = grid_of(response)
    assert (grid["rows"], grid["records"], grid["total"]) == ([], 0, 0)


@pytest.mark.parametrize("case", CASES)
async def test_the_server_remembers_the_child_whose_page_was_opened_last(
    harness: Harness, case: GridCase
) -> None:
    harness.revise_child(DEMO_USER_A, case.empty, **{case.field: (case.sample,)})

    filled_then_empty = await ask_feed(
        harness, case.grid, pages=(case.filled, case.empty), student=case.empty
    )
    empty_then_filled = await ask_feed(
        harness, case.grid, pages=(case.empty, case.filled), student=case.filled
    )
    forgotten = await ask_feed(
        harness,
        case.grid,
        pages=(case.empty, case.filled),
        student=case.empty,
        referer=page_url(case.grid, case.empty),
    )

    assert len(rows_of(filled_then_empty)) == 1
    assert len(rows_of(empty_then_filled)) > 1
    assert rows_of(forgotten) == []


@pytest.mark.parametrize("case", CASES)
async def test_a_grid_is_cut_into_pages_of_the_size_the_feed_asks_for(
    harness: Harness, case: GridCase
) -> None:
    whole = rows_of(await ask_feed(harness, case.grid, pages=(case.filled,), student=case.filled))
    count = len(whole)
    assert count >= 3

    async def page_of_two(number: int) -> PortalResponse:
        path = feed_path(case.grid, case.filled, page=str(number), rows="2")
        return await ask_feed(harness, case.grid, pages=(case.filled,), path=path)

    first, second, beyond = await page_of_two(1), await page_of_two(2), await page_of_two(99)

    assert rows_of(first) == whole[:2]
    assert rows_of(second) == whole[2:4]
    assert rows_of(beyond) == []
    assert (grid_of(first)["total"], grid_of(first)["records"]) == (-(-count // 2), count)
    assert grid_of(second)["page"] == 2


@pytest.mark.parametrize("case", CASES)
async def test_a_grid_asked_for_before_signing_in_sends_the_visitor_to_the_logon_page(
    harness: Harness, case: GridCase
) -> None:
    response = await harness.session().request(
        PortalRequest(method="GET", path=page_path(case.grid, case.filled), follow=False)
    )

    assert response.status == 302
    assert (response.location or "").startswith(LOGON_PATH)


@pytest.mark.parametrize("case", CASES)
async def test_a_grid_asked_for_after_the_session_ended_sends_the_visitor_to_the_logon_page(
    harness: Harness, case: GridCase
) -> None:
    async def end_and_ask(tx: Tx) -> PortalResponse:
        harness.sim.expire_all_sessions()
        return await tx.request(
            PortalRequest(
                method="GET",
                path=page_path(case.grid, case.filled),
                follow=False,
                referer=tx.absolute(HOME_PATH),
            )
        )

    response = await harness.gateway().call(end_and_ask)

    assert response.status == 302
    assert (response.location or "").startswith(LOGON_PATH)

"""Reading the message list."""

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from urllib.parse import parse_qs

import pytest

from alexia_api.domain.errors import PortalError, SchemaDrift, UnexpectedReply
from alexia_api.domain.ids import parse_message_id
from alexia_api.domain.messages import FolderName, MessageSummary
from alexia_api.portal.gateway import Gateway
from alexia_api.portal.grid import GridRow, cell_text
from alexia_api.portal.inbox import (
    GRID_ID,
    Feed,
    parse_feed_page,
    parse_feed_row,
    read_feed,
)
from alexia_api.portal.pages import COMUNICADOS_PAGE, FEED_ACCEPT, PageRequest, get_page
from alexia_api.sim.app import MESSAGES_PATH
from alexia_api.sim.mail import SimMessage, feed_cells
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_B, default_world, synthetic_guid
from tests.harness import Failure, Harness

GUID = synthetic_guid(0x1001)
PAGE_TEXT = "the whole page"

BASE: tuple[object, ...] = (
    GUID,
    '<img src="/img/sobre_cerrado.png" alt="No leído" />',
    "FALSE",
    '<img src="/img/lector.png" />',
    "Ana Muestra Tutora",
    "Reto de matemáticas",
    "15/10/2026",
    "&nbsp",
    "False",
    "Aviso",
    "",
)


def row_of(changes: Mapping[int, object] | None = None, *, row_id: str = GUID) -> GridRow:
    cell = list(BASE)
    for index, value in (changes or {}).items():
        cell[index] = value
    return GridRow(id=row_id, cell=cell)


def parsed(changes: Mapping[int, object] | None = None, *, row_id: str = GUID) -> MessageSummary:
    return parse_feed_row(row_of(changes, row_id=row_id), 0, PAGE_TEXT)


def drift_of(row: GridRow, index: int = 0) -> SchemaDrift:
    with pytest.raises(PortalError) as raised:
        parse_feed_row(row, index, PAGE_TEXT)
    detail = raised.value.detail
    assert isinstance(detail, SchemaDrift)
    assert detail.sample == PAGE_TEXT
    return detail


def test_reads_every_field_of_a_row() -> None:
    assert parsed() == MessageSummary(
        id=parse_message_id(GUID),
        read=False,
        institutional=False,
        sender="Ana Muestra Tutora",
        subject="Reto de matemáticas",
        received_on=date(2026, 10, 15),
        expires_on=None,
        anonymous=False,
        category="Aviso",
        has_attachments=False,
    )


@pytest.mark.parametrize(
    ("icon", "expected"),
    [
        ('<img alt="Leído">', True),
        ('<img alt="LEÍDO">', True),
        ('<img alt="Leido">', True),
        ('<img alt="No leído">', False),
        ('<img alt="no   leido">', False),
        ('<img src="/i/SOBRE_ABIERTO.png">', True),
        ('<img src="/i/sobre_cerrado.png">', False),
        ('<img alt="No leído" src="/i/sobre_abierto.png">', False),
        ('<img alt="Leído" src="/i/sobre_cerrado.png">', False),
        ('<img alt="Unread">', None),
        ('<img alt="leídos">', None),
        ("<span>Leído</span>", None),
        ("", None),
    ],
)
def test_the_read_state_comes_from_the_icon(icon: str, expected: bool | None) -> None:
    assert parsed({1: icon}).read is expected


@pytest.mark.parametrize(("index", "field"), [(2, "institutional"), (8, "anonymous")])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("TRUE", True),
        ("True", True),
        ("true", True),
        (" TRUE ", True),
        ("FALSE", False),
        ("False", False),
        ("", False),
        ("yes", False),
        ("1", False),
    ],
)
def test_a_flag_is_set_only_when_the_portal_says_true(
    index: int, field: str, text: str, expected: bool
) -> None:
    assert getattr(parsed({index: text}), field) is expected


def test_sender_and_subject_are_decoded_and_tidied() -> None:
    summary = parsed({4: "  Ana&nbsp;Muestra &amp; Co ", 5: "  <b>Excursión</b>   al\n museo  "})

    assert (summary.sender, summary.subject) == ("Ana Muestra & Co", "Excursión al museo")


def test_the_received_date_may_sit_in_markup_and_spaces() -> None:
    assert parsed({6: " <b>15/10/2026</b> "}).received_on == date(2026, 10, 15)


@pytest.mark.parametrize("text", ["31/02/2026", "", "2026-10-15", "&nbsp", "15/10/26", "1/10/2026"])
def test_a_received_date_that_is_not_a_list_date_is_schema_drift(text: str) -> None:
    assert drift_of(row_of({6: text})).where == "feed row 0: received date"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("25/10/2026", date(2026, 10, 25)),
        ("<b>25/10/2026</b>", date(2026, 10, 25)),
        ("&nbsp", None),
        ("&nbsp;", None),
        ("", None),
        (" ", None),
    ],
)
def test_the_expiry_is_optional(text: str, expected: date | None) -> None:
    assert parsed({7: text}).expires_on == expected


@pytest.mark.parametrize("text", ["31/02/2026", "25-10-2026", "soon"])
def test_an_expiry_that_is_not_a_list_date_is_schema_drift(text: str) -> None:
    assert drift_of(row_of({7: text})).where == "feed row 0: expiry date"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Aviso", "Aviso"),
        ("  Entrevistas ", "Entrevistas"),
        ("", None),
        ("&nbsp", None),
        ("  ", None),
    ],
)
def test_the_category_is_optional(text: str, expected: str | None) -> None:
    assert parsed({9: text}).category == expected


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("", False),
        ("&nbsp", False),
        (" ", False),
        ('<img alt="Documentos adjuntos: a.pdf" />', True),
        ("x", True),
    ],
)
def test_a_paperclip_means_the_message_has_attachments(html: str, expected: bool) -> None:
    assert parsed({10: html}).has_attachments is expected


@pytest.mark.parametrize("count", [0, 1, 10, 12])
def test_a_row_must_have_eleven_cells(count: int) -> None:
    cell = [*BASE[:count], *[""] * max(0, count - len(BASE))]

    detail = drift_of(GridRow(id=GUID, cell=cell), index=3)

    assert detail.where == f"feed row 3: {count} cells instead of 11"


@pytest.mark.parametrize("value", [None, 1, True, ["x"], {"a": 1}])
def test_a_cell_that_is_not_text_is_schema_drift(value: object) -> None:
    assert drift_of(row_of({4: value})).where == "feed row 0: a cell is not text"


@pytest.mark.parametrize(
    ("row_id", "first"),
    [
        (synthetic_guid(0x1002), GUID),
        ("not-a-guid", GUID),
        (GUID, "not-a-guid"),
        ("", ""),
    ],
)
def test_the_row_id_and_the_first_cell_must_name_one_message(row_id: str, first: str) -> None:
    detail = drift_of(row_of({0: first}, row_id=row_id))

    assert detail.where == "feed row 0: the row id and the first cell disagree"


def test_the_id_may_differ_in_case_between_the_row_and_the_cell() -> None:
    assert parsed({0: GUID.upper()}, row_id=GUID).id == GUID


def page_text(*rows: GridRow, page: int = 1, total: int = 1, records: int | None = None) -> str:
    return json.dumps(
        {
            "page": page,
            "total": total,
            "records": len(rows) if records is None else records,
            "rows": [{"id": row.id, "cell": row.cell} for row in rows],
        }
    )


def test_a_page_keeps_the_portals_counts_and_reads_every_row() -> None:
    other = synthetic_guid(0x1002)
    text = page_text(row_of(), row_of({0: other}, row_id=other), page=2, total=5, records=230)

    page = parse_feed_page(text)

    assert (page.page, page.pages, page.records) == (2, 5, 230)
    assert [row.id for row in page.rows] == [GUID, other]


def test_a_page_names_the_row_it_cannot_read() -> None:
    text = page_text(row_of(), row_of({6: "soon"}))

    with pytest.raises(PortalError) as raised:
        parse_feed_page(text)

    assert raised.value.detail == SchemaDrift(where="feed row 1: received date", sample=text)


def test_a_page_that_is_not_json_is_schema_drift() -> None:
    with pytest.raises(PortalError) as raised:
        parse_feed_page("<html></html>")

    assert raised.value.detail == SchemaDrift(where="feed page is not JSON", sample="<html></html>")


def test_text_the_simulator_writes_into_a_cell_comes_back_unchanged() -> None:
    first = default_world().families[0].messages[0]
    message = replace(first, sender="A <b> & C", subject="1 < 2 &amp; 3", category="x <y> z")

    cells = feed_cells(message)

    assert [cell_text(cells[index]) for index in (4, 5, 9)] == [
        "A <b> & C",
        "1 < 2 &amp; 3",
        "x <y> z",
    ]


def summary_of(message: SimMessage) -> MessageSummary:
    return MessageSummary(
        id=parse_message_id(message.guid),
        read=message.read,
        institutional=message.institutional,
        sender=message.sender,
        subject=message.subject.strip(),
        received_on=date.fromisoformat(message.date),
        expires_on=date.fromisoformat(message.expires) if message.expires else None,
        anonymous=message.anonymous,
        category=message.category or None,
        has_attachments=bool(message.files),
    )


def seeded(username: str, folder: str) -> tuple[MessageSummary, ...]:
    family = default_world().family_for(username)
    assert family is not None
    held = [message for message in family.messages if message.folder == folder]
    held.sort(key=lambda message: (message.date, message.time), reverse=True)
    return tuple(summary_of(message) for message in held)


async def feed_of(gateway: Gateway, folder: FolderName = "received", **limits: int) -> Feed:
    return await gateway.call(lambda tx: read_feed(tx, folder, **limits))


def feed_queries(harness: Harness) -> list[dict[str, str]]:
    return [
        {name: values[0] for name, values in parse_qs(request.query).items()}
        for request in harness.sim.requests
        if request.path == MESSAGES_PATH
    ]


@pytest.mark.parametrize(
    ("username", "password"),
    [("marta.ejemplo", "demo-password-a"), (DEMO_USER_B, DEMO_PASSWORD_B)],
)
async def test_reads_the_received_messages_of_each_family_newest_first(
    harness: Harness, username: str, password: str
) -> None:
    gateway = harness.gateway(credentials=harness.credentials(username, password))

    feed = await feed_of(gateway)

    expected = seeded(username, "received")
    assert feed == Feed(records=len(expected), rows=expected, truncated=False)
    assert len(expected) > 1
    assert any(row.read is False for row in expected)
    assert any(row.read is True for row in expected)


async def test_reads_the_folder_it_is_asked_for_whichever_one_the_portal_showed_before(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    asked: tuple[FolderName, ...] = ("sent", "received", "received", "sent")

    for folder in asked:
        feed = await feed_of(gateway, folder)
        assert feed.rows == seeded("marta.ejemplo", folder)

    assert 0 < len(seeded("marta.ejemplo", "sent")) < len(seeded("marta.ejemplo", "received"))


async def test_a_small_page_size_reads_every_page_and_lists_every_message_once(
    harness: Harness,
) -> None:
    gateway = harness.gateway()

    feed = await feed_of(gateway, page_size=3)

    assert feed.rows == seeded("marta.ejemplo", "received")
    queries = feed_queries(harness)
    assert [query["page"] for query in queries] == ["1", "2", "3"]
    assert {query["rows"] for query in queries} == {"3"}


async def test_pages_past_the_limit_are_left_unread_and_the_feed_says_so(harness: Harness) -> None:
    gateway = harness.gateway()

    feed = await feed_of(gateway, page_size=3, max_pages=2)

    everything = seeded("marta.ejemplo", "received")
    assert feed.rows == everything[:6]
    assert feed.records == len(everything)
    assert feed.truncated
    assert [query["page"] for query in feed_queries(harness)] == ["1", "2"]


async def test_a_limit_that_fits_every_page_is_not_truncated(harness: Harness) -> None:
    gateway = harness.gateway()

    feed = await feed_of(gateway, page_size=3, max_pages=3)

    assert len(feed.rows) == feed.records
    assert not feed.truncated


async def test_a_folder_with_no_messages_costs_one_request(harness: Harness) -> None:
    world = harness.sim.world
    families = tuple(replace(family, messages=()) for family in world.families)
    harness.sim.world = replace(world, families=families)

    feed = await feed_of(harness.gateway())

    assert feed == Feed(records=0, rows=(), truncated=False)
    assert len(feed_queries(harness)) == 1


async def test_the_request_carries_what_the_portals_own_page_sends(harness: Harness) -> None:
    await feed_of(harness.gateway())

    (query,) = feed_queries(harness)
    assert query["jqGridID"] == GRID_ID
    assert (query["sidx"], query["sord"], query["_search"]) == ("FechaInicio", "desc", "false")
    asked_at = int(query["nd"]) / 1000
    assert abs(asked_at - harness.clock.now().timestamp()) < 60


VALID_QUERY = "jqGridID=g&_search=false&nd=1&rows=3&page=1&sidx=FechaInicio&sord=desc"


@pytest.mark.parametrize(
    ("query", "xhr"),
    [
        ("", True),
        ("rows=3&page=1", True),
        (VALID_QUERY.replace("rows=3", "rows=0"), True),
        (VALID_QUERY.replace("page=1", "page=0"), True),
        (VALID_QUERY.replace("page=1", "page=-1"), True),
        (VALID_QUERY.replace("nd=1", "nd=soon"), True),
        (VALID_QUERY, False),
    ],
)
async def test_the_portal_refuses_a_feed_request_that_is_not_what_its_page_sends(
    harness: Harness, failure: Failure, query: str, xhr: bool
) -> None:
    gateway = harness.gateway()

    detail = await failure(
        gateway.call(
            lambda tx: get_page(
                tx,
                PageRequest(
                    name="feed",
                    path=f"{COMUNICADOS_PAGE}?{query}",
                    referer=tx.absolute(COMUNICADOS_PAGE),
                    accept=FEED_ACCEPT,
                    xhr=xhr,
                ),
            )
        )
    )

    assert detail == UnexpectedReply(where="page:feed HTTP 500")


async def test_a_row_with_the_wrong_number_of_cells_is_schema_drift(
    harness: Harness, failure: Failure
) -> None:
    harness.sim.options.feed_cell_count = 10

    detail = await failure(feed_of(harness.gateway()))

    assert isinstance(detail, SchemaDrift)
    assert detail.where == "feed row 0: 10 cells instead of 11"


async def test_a_session_that_ended_is_replaced_and_the_reader_never_notices(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    await feed_of(gateway, "sent")

    harness.sim.expire_all_sessions()
    feed = await feed_of(gateway, "sent")

    assert feed.rows == seeded("marta.ejemplo", "sent")
    assert harness.sim.counters.login_attempts == 2

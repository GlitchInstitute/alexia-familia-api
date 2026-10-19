"""Reading the forms of the school, which the portal lists on the page of the messages."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from alexia_api.domain.errors import PortalError, SchemaDrift, Transport, UnexpectedReply
from alexia_api.domain.forms import FormContent, FormSummary
from alexia_api.domain.ids import parse_form_id
from alexia_api.portal.forms import FORMS_PAGE, FormFeed, lists_forms, read_form, read_forms
from alexia_api.portal.gateway import Gateway
from alexia_api.portal.inbox import Feed, read_feed
from alexia_api.portal.pages import COMUNICADOS_PAGE
from alexia_api.portal.session import Gates, PortalRequest, PortalResponse, Tx
from alexia_api.sim.world import DEMO_PASSWORD_B, DEMO_USER_A, DEMO_USER_B, synthetic_guid
from tests.harness import Failure, Harness

MADRID = ZoneInfo("Europe/Madrid")
ZOO = FormSummary(
    id=parse_form_id(synthetic_guid(0x1401)),
    subject="Autorización para la salida al zoo",
    sender="Secretaría",
    received_on=date(2026, 10, 16),
    expires_on=date(2026, 10, 30),
    category="Autorizaciones",
)
CANTEEN = FormSummary(
    id=parse_form_id(synthetic_guid(0x1402)),
    subject="Encuesta del comedor escolar",
    sender="Dirección",
    received_on=date(2026, 10, 1),
    expires_on=date(2026, 10, 20),
    category="Encuestas",
)
FORM_IDS = {ZOO.id, CANTEEN.id}
LISTS_FORMS = b'<input type="hidden" id="hidIsAutorizacion" value="1" />'
SAYS_NOTHING = b"<html><body><p>Comunicados</p></body></html>"

type Before = Callable[[PortalRequest], Awaitable[None]]
type After = Callable[[PortalRequest, PortalResponse], PortalResponse]


async def nothing(_request: PortalRequest) -> None:
    return None


def unchanged(_request: PortalRequest, response: PortalResponse) -> PortalResponse:
    return response


def answers_with(path: str, body: bytes) -> After:
    """A rewrite that gives the page at a path another body, and leaves the rest alone."""

    def rewrite(request: PortalRequest, response: PortalResponse) -> PortalResponse:
        return replace(response, body=body) if request.path == path else response

    return rewrite


class Watched:
    """A session that works as usual, and that can fail or stall on a request the test names.

    It can also change what an answer says, to give the reader a page that the simulator never
    sends.
    """

    def __init__(self, inner: Tx, before: Before, after: After = unchanged) -> None:
        self._inner = inner
        self._before = before
        self._after = after
        self.cleared = False

    @property
    def gates(self) -> Gates:
        return self._inner.gates

    @property
    def zone(self) -> ZoneInfo:
        return self._inner.zone

    async def request(self, request: PortalRequest) -> PortalResponse:
        await self._before(request)
        return self._after(request, await self._inner.request(request))

    def absolute(self, path: str) -> str:
        return self._inner.absolute(path)

    def now(self) -> datetime:
        return self._inner.now()

    def clear_cookies(self) -> None:
        self.cleared = True
        self._inner.clear_cookies()


async def refuse_the_way_back(request: PortalRequest) -> None:
    if request.path == COMUNICADOS_PAGE:
        raise PortalError(Transport(reason="network"))


def is_a_list_request(request: PortalRequest) -> bool:
    return request.path.startswith(f"{COMUNICADOS_PAGE}?jqGridID")


async def the_ids_of_the_messages(gateway: Gateway) -> set[str]:
    feed: Feed = await gateway.call(lambda tx: read_feed(tx, "received"))
    return {message.id for message in feed.messages}


def what_the_portal_was_asked(harness: Harness) -> list[str]:
    """The requests that switch or read the list, each in a word."""
    words: list[str] = []
    for request in harness.sim.requests:
        if request.path.endswith("CarpetaSeleccionada"):
            words.append("select")
        elif request.path.endswith("Comunicados.aspx"):
            if request.query == "autorizaciones=1":
                words.append("forms page")
            elif request.query.startswith("jqGridID"):
                words.append("list")
            elif request.query == "":
                words.append("plain page")
    return words


async def test_lists_the_forms_newest_first_with_every_field(harness: Harness) -> None:
    feed = await harness.gateway().call(read_forms)

    assert feed == FormFeed(forms=(ZOO, CANTEEN), truncated=False)


async def test_a_family_that_was_sent_no_form_has_an_empty_list(harness: Harness) -> None:
    gateway = harness.gateway(
        account="pablo", credentials=harness.credentials(DEMO_USER_B, DEMO_PASSWORD_B)
    )

    feed = await gateway.call(read_forms)

    assert feed == FormFeed(forms=(), truncated=False)


async def test_the_portal_is_switched_to_the_forms_and_back_in_that_order(harness: Harness) -> None:
    await harness.gateway().call(read_forms)

    assert what_the_portal_was_asked(harness) == [
        "forms page",
        "select",
        "list",
        "plain page",
        "select",
    ]


async def test_messages_and_forms_read_in_turn_never_hold_each_other(harness: Harness) -> None:
    gateway = harness.gateway()

    for _ in range(2):
        assert {form.id for form in (await gateway.call(read_forms)).forms} == FORM_IDS
        assert not FORM_IDS & await the_ids_of_the_messages(gateway)


async def test_a_page_size_below_the_length_reads_every_page(harness: Harness) -> None:
    feed = await harness.gateway().call(lambda tx: read_forms(tx, page_size=1))

    assert feed == FormFeed(forms=(ZOO, CANTEEN), truncated=False)
    assert what_the_portal_was_asked(harness).count("list") == 2


async def test_a_list_longer_than_the_pages_that_are_read_is_marked_truncated(
    harness: Harness,
) -> None:
    feed = await harness.gateway().call(lambda tx: read_forms(tx, page_size=1, max_pages=1))

    assert feed == FormFeed(forms=(ZOO,), truncated=True)


async def test_a_session_the_portal_dropped_is_replaced_and_the_read_runs_again(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    await gateway.call(read_forms)
    harness.sim.expire_all_sessions()

    feed = await gateway.call(read_forms)

    assert feed.forms == (ZOO, CANTEEN)
    assert harness.sim.counters.login_attempts == 2


async def test_a_read_that_fails_in_the_list_ends_the_session(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    harness.sim.options.feed_cell_count = 5

    detail = await failure(gateway.call(read_forms))
    harness.sim.options.feed_cell_count = None

    assert isinstance(detail, SchemaDrift)
    assert not FORM_IDS & await the_ids_of_the_messages(gateway)
    assert harness.sim.counters.login_attempts == 2


async def test_a_read_that_cannot_switch_back_ends_the_session(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    watched: list[Watched] = []

    async def recipe(tx: Tx) -> FormFeed:
        watched.append(Watched(tx, refuse_the_way_back))
        return await read_forms(watched[-1])

    detail = await failure(gateway.call(recipe))

    assert detail == Transport(reason="network")
    assert [session.cleared for session in watched] == [True]
    assert not FORM_IDS & await the_ids_of_the_messages(gateway)
    assert harness.sim.counters.login_attempts == 2


async def test_a_read_that_is_cancelled_ends_the_session(harness: Harness) -> None:
    gateway = harness.gateway()
    reached = asyncio.Event()
    watched: list[Watched] = []

    async def stall_on_the_list(request: PortalRequest) -> None:
        if is_a_list_request(request):
            reached.set()
            await asyncio.Event().wait()

    async def recipe(tx: Tx) -> FormFeed:
        watched.append(Watched(tx, stall_on_the_list))
        return await read_forms(watched[-1])

    task = asyncio.create_task(gateway.call(recipe))
    await reached.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [session.cleared for session in watched] == [True]
    assert not FORM_IDS & await the_ids_of_the_messages(gateway)
    assert harness.sim.counters.login_attempts == 2


async def test_a_read_that_works_keeps_the_session(harness: Harness) -> None:
    gateway = harness.gateway()
    watched: list[Watched] = []

    async def recipe(tx: Tx) -> FormFeed:
        watched.append(Watched(tx, nothing))
        return await read_forms(watched[-1])

    await gateway.call(recipe)

    assert [session.cleared for session in watched] == [False]
    assert harness.sim.counters.login_attempts == 1


@pytest.mark.parametrize(
    ("html", "says"),
    [
        ('<input type="hidden" id="hidIsAutorizacion" value="1" />', True),
        ('<input type="hidden" id="hidIsAutorizacion" value="0" />', False),
        ('<input type="hidden" id="hidIsAutorizacion" value="" />', False),
        ('<input type="hidden" id="hidIsAutorizacion" value="yes" />', False),
        (
            (
                '<input type="hidden" id="ctl00_ContenidoPagina_hidIsAutorizacion" '
                'name="ctl00$ContenidoPagina$hidIsAutorizacion" value="1" />'
            ),
            True,
        ),
        ('<input type="hidden" name="ctl00$hidIsAutorizacion" value="1" />', True),
        ('<input type="hidden" id="hidIsAutorizacion" />', None),
        ('<input type="hidden" id="hidIsAutorizacionX" value="1" />', None),
        ('<input type="hidden" id="hidOtherFlag" value="1" />', None),
        ("<p>Comunicados</p>", None),
        ("", None),
    ],
)
def test_the_message_page_says_in_a_hidden_input_whether_it_lists_forms(
    html: str, says: bool | None
) -> None:
    assert lists_forms(html) is says


async def test_a_portal_that_ignores_the_address_is_refused_before_it_is_asked_for_anything(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    harness.sim.options.forms_page_ignores_query = True

    detail = await failure(gateway.call(read_forms))
    harness.sim.options.forms_page_ignores_query = False

    assert detail == UnexpectedReply(where="forms page does not say that it lists forms")
    assert what_the_portal_was_asked(harness) == ["forms page"]
    assert (await gateway.call(read_forms)).forms == (ZOO, CANTEEN)
    assert harness.sim.counters.login_attempts == 2


async def test_a_forms_page_that_says_nothing_about_its_list_is_refused(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    watched: list[Watched] = []

    async def recipe(tx: Tx) -> FormFeed:
        watched.append(Watched(tx, nothing, answers_with(FORMS_PAGE, SAYS_NOTHING)))
        return await read_forms(watched[-1])

    detail = await failure(gateway.call(recipe))

    assert detail == UnexpectedReply(where="forms page does not say that it lists forms")
    assert [session.cleared for session in watched] == [True]
    assert what_the_portal_was_asked(harness) == ["forms page"]


async def test_a_portal_that_stays_on_the_forms_is_refused_and_the_session_ends(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    watched: list[Watched] = []

    async def recipe(tx: Tx) -> FormFeed:
        watched.append(Watched(tx, nothing, answers_with(COMUNICADOS_PAGE, LISTS_FORMS)))
        return await read_forms(watched[-1])

    detail = await failure(gateway.call(recipe))

    assert detail == UnexpectedReply(where="message page still lists forms")
    assert [session.cleared for session in watched] == [True]
    assert not FORM_IDS & await the_ids_of_the_messages(gateway)
    assert harness.sim.counters.login_attempts == 2


async def test_a_plain_page_that_says_nothing_about_its_list_is_accepted(
    harness: Harness,
) -> None:
    gateway = harness.gateway()

    async def recipe(tx: Tx) -> FormFeed:
        return await read_forms(Watched(tx, nothing, answers_with(COMUNICADOS_PAGE, SAYS_NOTHING)))

    feed = await gateway.call(recipe)

    assert feed.forms == (ZOO, CANTEEN)
    assert harness.sim.counters.login_attempts == 1


async def test_reads_the_time_the_words_and_the_children_of_a_form(harness: Harness) -> None:
    gateway = harness.gateway()
    row = (await gateway.call(read_forms)).forms[0]

    content = await gateway.call(lambda tx: read_form(tx, row))

    assert content == FormContent(
        sent_at=datetime(2026, 10, 16, 10, 0, tzinfo=MADRID),
        body=content.body,
        links=(),
        child_names="Lucía",
    )
    assert content.body.text == (
        "La clase de Lucía irá al zoo el 5 de noviembre.\n\n"
        "Necesitamos su autorización antes del 30 de octubre."
    )


async def test_reading_a_form_does_not_switch_the_list(harness: Harness) -> None:
    gateway = harness.gateway()
    row = (await gateway.call(read_forms)).forms[1]
    asked_before = len(harness.sim.requests)

    content = await gateway.call(lambda tx: read_form(tx, row))

    assert content.child_names == "Lucía, Mateo"
    assert all(
        request.query != "autorizaciones=1" for request in harness.sim.requests[asked_before:]
    )


async def test_a_page_that_is_not_the_form_of_the_row_is_refused(
    harness: Harness, failure: Failure
) -> None:
    gateway = harness.gateway()
    row = (await gateway.call(read_forms)).forms[0]
    harness.revise(DEMO_USER_A, row.id, subject="Otro asunto")

    detail = await failure(gateway.call(lambda tx: read_form(tx, row)))

    assert detail == UnexpectedReply(where="message page does not match the list row")

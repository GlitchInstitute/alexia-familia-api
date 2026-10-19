"""Downloading one file of a message."""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.domain.errors import AttachmentTooLarge, UnexpectedReply
from alexia_api.domain.ids import attachment_token
from alexia_api.domain.media import MEBIBYTE, OCTET_STREAM, Download
from alexia_api.portal.attachments import REPOSITORY_PATH, attachment_path, download_attachment
from alexia_api.portal.folders import select_folder
from alexia_api.portal.gateway import Gateway
from alexia_api.portal.session import Gates, PortalRequest, PortalResponse, Tx
from alexia_api.sim.mail import SimFile, SimMessage
from alexia_api.sim.world import DEMO_USER_A, synthetic_guid
from tests.harness import Failure, Harness, listed_row, seeded

LIMIT = 25 * MEBIBYTE
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def a_file(name: str, data: bytes, key: int = 0xB01) -> SimFile:
    return SimFile(id=f"{synthetic_guid(key)}/{name}", name=name, data=data)


def a_message_with(number: int, *files: SimFile) -> SimMessage:
    return replace(seeded(0x1008), guid=synthetic_guid(number), files=files)


async def fetch(
    gateway: Gateway, number: int, file: SimFile, limit: int = LIMIT
) -> Download | None:
    row = await listed_row(gateway, number)
    token = attachment_token(file.id)
    return await gateway.call(lambda tx: download_attachment(tx, "received", row, token, limit))


class Doctored:
    """A session that works as usual, except that it changes what the portal says to downloads."""

    def __init__(self, inner: Tx, change: Callable[[PortalResponse], PortalResponse]) -> None:
        self._inner = inner
        self._change = change

    @property
    def gates(self) -> Gates:
        return self._inner.gates

    @property
    def zone(self) -> ZoneInfo:
        return self._inner.zone

    async def request(self, request: PortalRequest) -> PortalResponse:
        response = await self._inner.request(request)
        return self._change(response) if request.path.startswith(REPOSITORY_PATH) else response

    def absolute(self, path: str) -> str:
        return self._inner.absolute(path)

    def now(self) -> datetime:
        return self._inner.now()

    def clear_cookies(self) -> None:
        self._inner.clear_cookies()


async def fetch_doctored(
    gateway: Gateway, file: SimFile, change: Callable[[PortalResponse], PortalResponse]
) -> Download | None:
    row = await listed_row(gateway, 0x1002)
    token = attachment_token(file.id)
    return await gateway.call(
        lambda tx: download_attachment(Doctored(tx, change), "received", row, token, LIMIT)
    )


async def test_downloads_a_file_with_the_name_the_message_lists_and_the_type_its_bytes_show(
    harness: Harness,
) -> None:
    (file,) = seeded(0x1002).files

    download = await fetch(harness.gateway(), 0x1002, file)

    assert download == Download(
        name="Autorización museo.pdf", media_type="application/pdf", data=file.data
    )


@pytest.mark.parametrize(
    ("name", "data", "expected"),
    [
        ("foto.png", JPEG, "image/jpeg"),
        ("acta.docx", b"PK\x03\x04" + b"\x00" * 16, DOCX),
        ("acta.zip", b"PK\x03\x04" + b"\x00" * 16, "application/zip"),
        ("pagina.html", b"<html><script>alert(1)</script></html>", "text/plain"),
        ("dibujo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>', "text/plain"),
        ("datos.bin", b"\x00\x01\x02", OCTET_STREAM),
        ("vacio.pdf", b"", OCTET_STREAM),
    ],
)
async def test_the_type_comes_from_the_bytes_and_never_from_the_name(
    harness: Harness, name: str, data: bytes, expected: str
) -> None:
    file = a_file(name, data)
    harness.deliver(DEMO_USER_A, a_message_with(0x1300, file))

    download = await fetch(harness.gateway(), 0x1300, file)

    assert download is not None
    assert download.media_type == expected
    assert download.data == data
    assert download.name == name


async def test_a_name_with_spaces_accents_and_every_kind_of_punctuation_is_fetched_whole(
    harness: Harness,
) -> None:
    file = a_file("Informe (final) ñ's #1&2=3+4?.pdf", b"%PDF-1.4\n%%EOF\n")
    harness.deliver(DEMO_USER_A, a_message_with(0x1301, file))

    download = await fetch(harness.gateway(), 0x1301, file)

    assert download is not None
    assert download.name == file.name
    assert download.data == file.data


async def test_the_message_is_opened_and_read_again_just_before_the_file_is_fetched(
    harness: Harness,
) -> None:
    (file,) = seeded(0x1002).files
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1002)
    token = attachment_token(file.id)
    before = len(harness.sim.requests)

    await gateway.call(lambda tx: download_attachment(tx, "received", row, token, LIMIT))

    sent = [request.path.rsplit("/", 1)[-1] for request in harness.sim.requests[before:]]
    assert sent == [
        "CarpetaSeleccionada",
        "Comunicado.aspx",
        "GetDatosPaginaComunicado",
        "ControladorRepositorio.ashx",
    ]


async def test_the_folder_of_the_message_is_shown_before_its_file_is_fetched(
    harness: Harness,
) -> None:
    (file,) = seeded(0x1002).files
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1002)
    token = attachment_token(file.id)
    await gateway.call(lambda tx: select_folder(tx, "sent"))

    await gateway.call(lambda tx: download_attachment(tx, "received", row, token, LIMIT))

    assert [session.folder for session in harness.sim.sessions.values()] == ["received"]


async def test_the_file_of_a_sent_message_is_fetched_with_the_sent_folder_shown(
    harness: Harness,
) -> None:
    file = a_file("lista.pdf", b"%PDF-1.4\n%%EOF\n")
    harness.deliver(
        DEMO_USER_A, replace(seeded(0x2001), guid=synthetic_guid(0x2003), files=(file,))
    )
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x2003, "sent")
    token = attachment_token(file.id)
    await gateway.call(lambda tx: select_folder(tx, "received"))

    download = await gateway.call(lambda tx: download_attachment(tx, "sent", row, token, LIMIT))

    assert download is not None
    assert [session.folder for session in harness.sim.sessions.values()] == ["sent"]


async def test_a_file_the_message_does_not_list_is_never_asked_for(harness: Harness) -> None:
    (elsewhere,) = seeded(0x1006).files

    download = await fetch(harness.gateway(), 0x1002, elsewhere)

    assert download is None
    assert harness.sim.counters.downloads == 0


async def test_a_file_the_school_took_away_since_the_list_was_read_is_not_asked_for(
    harness: Harness,
) -> None:
    file = a_file("plantilla.pdf", b"%PDF-1.4\n%%EOF\n")
    harness.deliver(DEMO_USER_A, a_message_with(0x1302, file))
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1302)
    harness.revise(DEMO_USER_A, synthetic_guid(0x1302), files=())
    token = attachment_token(file.id)

    download = await gateway.call(lambda tx: download_attachment(tx, "received", row, token, LIMIT))

    assert download is None
    assert harness.sim.counters.downloads == 0


async def test_a_file_the_school_replaced_arrives_as_it_is_now(harness: Harness) -> None:
    old = a_file("horario.pdf", b"%PDF-1.4\nviejo\n%%EOF\n")
    harness.deliver(DEMO_USER_A, a_message_with(0x1303, old))
    gateway = harness.gateway()
    row = await listed_row(gateway, 0x1303)
    new = replace(old, data=b"%PDF-1.7\nel horario nuevo, que es mas largo\n%%EOF\n")
    harness.revise(DEMO_USER_A, synthetic_guid(0x1303), files=(new,))
    token = attachment_token(old.id)

    download = await gateway.call(lambda tx: download_attachment(tx, "received", row, token, LIMIT))

    assert download is not None
    assert download.data == new.data


async def test_a_file_over_the_limit_is_refused_before_any_byte_moves(
    harness: Harness, failure: Failure
) -> None:
    file = a_file("video.bin", b"x" * 1001)
    harness.deliver(DEMO_USER_A, a_message_with(0x1304, file))

    detail = await failure(fetch(harness.gateway(), 0x1304, file, limit=1000))

    assert detail == AttachmentTooLarge(limit=1000)
    assert harness.sim.counters.downloads == 0


async def test_a_file_exactly_at_the_limit_is_fetched(harness: Harness) -> None:
    file = a_file("justo.bin", b"x" * 1000)
    harness.deliver(DEMO_USER_A, a_message_with(0x1305, file))

    download = await fetch(harness.gateway(), 0x1305, file, limit=1000)

    assert download is not None
    assert len(download.data) == 1000


async def test_the_limit_of_the_operator_replaces_the_general_cap_on_a_reply(
    harness: Harness,
) -> None:
    file = a_file("libro.bin", b"x" * (9 * MEBIBYTE))
    harness.deliver(DEMO_USER_A, a_message_with(0x1306, file))

    download = await fetch(harness.gateway(), 0x1306, file)

    assert download is not None
    assert len(download.data) == 9 * MEBIBYTE


async def test_a_web_page_where_the_file_should_be_is_refused(
    harness: Harness, failure: Failure
) -> None:
    (file,) = seeded(0x1002).files
    harness.sim.options.download_as_page = True

    detail = await failure(fetch(harness.gateway(), 0x1002, file))

    assert detail == UnexpectedReply(where="the file came back as a web page")


@pytest.mark.parametrize("extra", [-1, 1])
async def test_a_file_that_is_not_the_size_the_message_lists_is_refused(
    harness: Harness, failure: Failure, extra: int
) -> None:
    (file,) = seeded(0x1002).files
    harness.sim.options.download_extra_bytes = extra

    detail = await failure(fetch(harness.gateway(), 0x1002, file))

    assert detail == UnexpectedReply(where="the file is not the size the message lists")


@pytest.mark.parametrize("content_type", ["text/html", "TEXT/HTML; charset=utf-8"])
async def test_a_page_is_recognised_whatever_the_case_of_its_type(
    harness: Harness, failure: Failure, content_type: str
) -> None:
    (file,) = seeded(0x1002).files

    def say_page(response: PortalResponse) -> PortalResponse:
        return replace(response, headers=httpx.Headers({"content-type": content_type}))

    detail = await failure(fetch_doctored(harness.gateway(), file, say_page))

    assert detail == UnexpectedReply(where="the file came back as a web page")


async def test_a_status_the_portal_does_not_use_names_the_download_in_the_error(
    harness: Harness, failure: Failure
) -> None:
    (file,) = seeded(0x1002).files

    detail = await failure(
        fetch_doctored(harness.gateway(), file, lambda response: replace(response, status=500))
    )

    assert detail == UnexpectedReply(where="page:attachment HTTP 500")


async def test_a_redirect_away_from_the_logon_page_is_not_followed(
    harness: Harness, failure: Failure
) -> None:
    (file,) = seeded(0x1002).files

    detail = await failure(
        fetch_doctored(
            harness.gateway(),
            file,
            lambda response: replace(response, status=302, location="/ACWeb/elsewhere.aspx"),
        )
    )

    assert detail == UnexpectedReply(where="page:attachment redirect")


async def test_a_session_that_ended_is_replaced_and_the_download_never_notices(
    harness: Harness,
) -> None:
    (file,) = seeded(0x1002).files
    gateway = harness.gateway()
    await fetch(gateway, 0x1002, file)
    harness.sim.expire_all_sessions()

    download = await fetch(gateway, 0x1002, file)

    assert download is not None
    assert download.data == file.data
    assert harness.sim.counters.login_attempts == 2


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        ("a b", "a%20b"),
        ("a/b", "a%2Fb"),
        ("Autorización", "Autorizaci%C3%B3n"),
        ("!~*'()", "!~*'()"),
        ("-_.", "-_."),
        ("&=+#?%;", "%26%3D%2B%23%3F%25%3B"),
    ],
)
def test_the_address_escapes_the_way_a_browser_does(text: str, escaped: str) -> None:
    path = attachment_path(text, text)

    assert path == f"{REPOSITORY_PATH}?tipo=6&nombre={escaped}&alias={escaped}"


@given(st.text(min_size=1, max_size=40), st.text(min_size=1, max_size=40))
def test_the_address_carries_any_id_and_name_back_unchanged(file_id: str, name: str) -> None:
    query = parse_qs(urlsplit(attachment_path(file_id, name)).query, keep_blank_values=True)

    assert query == {"tipo": ["6"], "nombre": [file_id], "alias": [name]}

"""Downloading the files of a message."""

from dataclasses import replace

import pytest

from alexia_api.domain.ids import attachment_token
from alexia_api.domain.media import MEBIBYTE
from alexia_api.sim.mail import SimFile
from alexia_api.sim.world import DEMO_USER_A, synthetic_guid
from tests.api.support import Api, MakeApi, problem_of
from tests.harness import A_NEW_MESSAGE, seeded

ACCOUNT = "/v1/accounts/marta"
MESSAGES = f"{ACCOUNT}/messages"
WITH_FILE = synthetic_guid(0x1002)
MESSAGE_DATA = "GetDatosPaginaComunicado"


def address_of(file: SimFile, message: str = WITH_FILE) -> str:
    return f"{MESSAGES}/{message}/attachments/{attachment_token(file.id)}"


def deliver_file(api: Api, name: str, data: bytes, number: int = 0x1300) -> tuple[str, SimFile]:
    file = SimFile(id=f"{synthetic_guid(0xB01)}/{number:x}", name=name, data=data)
    message = replace(A_NEW_MESSAGE, guid=synthetic_guid(number), files=(file,))
    api.harness.deliver(DEMO_USER_A, message)
    return message.guid, file


async def test_a_file_arrives_whole_with_the_type_its_bytes_show_and_a_name_to_save_it_under(
    api: Api,
) -> None:
    (file,) = seeded(0x1002).files

    response = await api.get(address_of(file))

    assert response.status_code == 200
    assert response.content == file.data
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(len(file.data))
    assert response.headers["content-disposition"] == (
        'attachment; filename="Autorizacion museo.pdf"; '
        "filename*=UTF-8''Autorizaci%C3%B3n%20museo.pdf"
    )


async def test_a_download_carries_the_protective_headers_of_every_answer(api: Api) -> None:
    (file,) = seeded(0x1002).files

    response = await api.get(address_of(file))

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-request-id"]


async def test_a_file_is_fetched_from_the_portal_every_time_and_never_stored(api: Api) -> None:
    (file,) = seeded(0x1002).files

    first = await api.get(address_of(file))
    second = await api.get(address_of(file))

    assert first.content == second.content == file.data
    assert api.harness.sim.counters.downloads == 2
    assert "x-cache" not in first.headers
    assert "age" not in first.headers


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("pagina.html", b"<html><script>alert(1)</script></html>"),
        ("dibujo.svg", b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'),
    ],
)
async def test_a_file_that_could_run_in_a_browser_comes_as_text_to_be_saved(
    api: Api, name: str, data: bytes
) -> None:
    message, file = deliver_file(api, name, data)

    response = await api.get(address_of(file, message))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.content == data


async def test_a_name_that_tries_to_split_the_header_cannot(api: Api) -> None:
    name = "a\r\nSet-Cookie: stolen=1\r\n\r\n<b>.pdf"
    message, file = deliver_file(api, name, b"%PDF-1.4\n%%EOF\n")

    response = await api.get(address_of(file, message))

    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert "\r" not in response.headers["content-disposition"]
    assert "\n" not in response.headers["content-disposition"]
    assert response.content == file.data


async def test_the_message_of_the_address_must_be_one_the_account_was_listed(api: Api) -> None:
    (file,) = seeded(0x1002).files

    response = await api.get(address_of(file, synthetic_guid(0x9999)))

    problem_of(response, status=404, code="message_not_found")
    assert api.harness.sim.counters.downloads == 0
    assert api.harness.requests_to(MESSAGE_DATA) == 0


async def test_a_message_the_family_sent_needs_the_sent_folder_for_its_files(api: Api) -> None:
    (file,) = seeded(0x1002).files

    response = await api.get(f"{address_of(file)}?folder=sent")

    problem_of(response, status=404, code="message_not_found")
    assert api.harness.sim.counters.downloads == 0


@pytest.mark.parametrize("token", ["not-a-token", "AAAA", "dG9rZW4=", "x" * 2000])
async def test_what_is_no_file_token_is_not_found_without_asking_the_portal_for_the_file(
    api: Api, token: str
) -> None:
    response = await api.get(f"{MESSAGES}/{WITH_FILE}/attachments/{token}")

    body = problem_of(response, status=404, code="attachment_not_found")
    assert "fresh=true" in body["detail"]
    assert api.harness.requests_to(MESSAGE_DATA) == 0
    assert api.harness.sim.counters.downloads == 0


async def test_a_token_the_message_does_not_list_is_not_found_and_never_downloaded(
    api: Api,
) -> None:
    (elsewhere,) = seeded(0x1006).files

    response = await api.get(address_of(elsewhere))

    problem_of(response, status=404, code="attachment_not_found")
    assert api.harness.sim.counters.downloads == 0


async def test_a_long_file_reference_is_cut_before_it_is_echoed(api: Api) -> None:
    response = await api.get(f"{MESSAGES}/{WITH_FILE}/attachments/{'x' * 200}")

    body = problem_of(response, status=404, code="attachment_not_found")
    assert "x" * 80 + "..." in body["detail"]
    assert "x" * 81 not in body["detail"]


async def test_the_file_of_a_message_of_another_account_is_not_found(api: Api) -> None:
    (theirs,) = seeded(0x1102, "pablo.prueba").files
    token = attachment_token(theirs.id)
    path = f"/v1/accounts/pablo/messages/{synthetic_guid(0x1102)}/attachments/{token}"

    assert (await api.get(path)).status_code == 200
    mine = f"{MESSAGES}/{synthetic_guid(0x1102)}/attachments/{token}"
    problem_of(await api.get(mine), status=404, code="message_not_found")


async def test_a_message_that_arrived_lately_needs_a_fresh_read_of_its_folder(api: Api) -> None:
    await api.get(MESSAGES)
    message, file = deliver_file(api, "aviso.pdf", b"%PDF-1.4\n%%EOF\n")

    stale = await api.get(address_of(file, message))
    fresh = await api.get(f"{address_of(file, message)}?fresh=true")

    problem_of(stale, status=404, code="message_not_found")
    assert fresh.status_code == 200
    assert fresh.content == file.data


async def test_a_file_over_the_limit_of_the_operator_is_a_413_that_says_how_to_raise_it(
    make_api: MakeApi,
) -> None:
    api = await make_api(max_attachment_mib=1)
    message, file = deliver_file(api, "video.bin", b"x" * (MEBIBYTE + 1))

    response = await api.get(address_of(file, message))

    body = problem_of(response, status=413, code="attachment_too_large")
    assert "1 MiB" in body["detail"]
    assert "ALEXIA_API_MAX_ATTACHMENT_MIB" in body["detail"]
    assert api.harness.sim.counters.downloads == 0


async def test_a_file_of_exactly_the_limit_is_served(make_api: MakeApi) -> None:
    api = await make_api(max_attachment_mib=1)
    message, file = deliver_file(api, "justo.bin", b"x" * MEBIBYTE)

    response = await api.get(address_of(file, message))

    assert response.status_code == 200
    assert len(response.content) == MEBIBYTE


async def test_a_web_page_where_the_file_should_be_is_a_bad_gateway(api: Api) -> None:
    (file,) = seeded(0x1002).files
    api.harness.sim.options.download_as_page = True

    response = await api.get(address_of(file))

    body = problem_of(response, status=502, code="unexpected_reply")
    assert "web page" in body["detail"]


async def test_a_file_of_the_wrong_size_is_a_bad_gateway_and_never_reaches_the_client(
    api: Api,
) -> None:
    (file,) = seeded(0x1002).files
    api.harness.sim.options.download_extra_bytes = -1

    response = await api.get(address_of(file))

    problem_of(response, status=502, code="unexpected_reply")
    assert file.data[:5] not in response.content


async def test_a_session_that_ended_is_replaced_and_the_client_never_notices(api: Api) -> None:
    (file,) = seeded(0x1002).files
    await api.get(address_of(file))
    api.harness.sim.expire_all_sessions()

    response = await api.get(address_of(file))

    assert response.status_code == 200
    assert response.content == file.data

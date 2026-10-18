import base64
import re
import uuid
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.domain import ids

GUID_PARSERS: list[Callable[[str], str]] = [
    ids.parse_student_id,
    ids.parse_person_id,
    ids.parse_staff_id,
    ids.parse_role_id,
    ids.parse_message_id,
    ids.parse_form_id,
    ids.parse_meeting_id,
    ids.parse_absence_id,
    ids.parse_outbox_id,
]
SAMPLE = "5afe0000-0000-4000-8000-0000000000ab"
NOT_GUIDS = [
    "",
    " ",
    "not-a-guid",
    "5afe0000000040008000000000000001",
    "5afe0000-0000-4000-8000-00000000000",
    "5afe0000-0000-4000-8000-0000000000012",
    "5afe0000-0000-4000-8000-00000000000g",
    " 5afe0000-0000-4000-8000-000000000001",
    "5afe0000-0000-4000-8000-000000000001\n",
    "{5afe0000-0000-4000-8000-000000000001}",
]


@pytest.mark.parametrize("parse", GUID_PARSERS)
def test_guid_parsers_lower_case_what_they_accept(parse: Callable[[str], str]) -> None:
    assert parse(SAMPLE.upper()) == SAMPLE


@pytest.mark.parametrize("bad", NOT_GUIDS)
@pytest.mark.parametrize("parse", GUID_PARSERS)
def test_guid_parsers_reject_everything_else(parse: Callable[[str], str], bad: str) -> None:
    with pytest.raises(ids.InvalidIdError):
        parse(bad)


@given(st.uuids())
def test_guid_parsers_accept_any_uuid_in_either_case(value: uuid.UUID) -> None:
    for parse in GUID_PARSERS:
        assert parse(str(value).upper()) == str(value)


def test_the_error_names_the_kind_and_hides_the_value() -> None:
    with pytest.raises(ids.InvalidIdError) as caught:
        ids.parse_student_id("pasted-secret-value")

    assert caught.value.kind == "student id"
    assert str(caught.value) == "not a valid student id"


@pytest.mark.parametrize("value", ["a", "family-a", "mum", "kid-2", "a1-b2-c3", "x" * 40])
def test_slugs_accept_lower_case_words_joined_by_single_hyphens(value: str) -> None:
    assert ids.parse_account_id(value) == value
    assert ids.parse_child_slug(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "Family", "-a", "a-", "a--b", "a b", "a_b", "ñ", "a\n", "x" * 41],
)
def test_slugs_reject_everything_else(value: str) -> None:
    with pytest.raises(ids.InvalidIdError):
        ids.parse_account_id(value)
    with pytest.raises(ids.InvalidIdError):
        ids.parse_child_slug(value)


FILE_IDS = [
    "2a7f.report 1.pdf",
    "folder/a b.pdf",
    "100%.pdf",
    "ñandú ✓.pdf",
    "x" * 768,
    "ñ" * 384,
    ">>>",
    "???",
]
PRINTABLE = st.characters(
    blacklist_categories=("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs")
) | st.just(" ")


def token_of(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@pytest.mark.parametrize("file_id", FILE_IDS)
def test_a_file_token_is_safe_in_a_path_and_reads_back_to_the_portals_id(file_id: str) -> None:
    token = ids.attachment_token(file_id)

    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert ids.parse_attachment_id(token) == token
    assert ids.portal_file_id(token) == file_id


@given(st.text(PRINTABLE, min_size=1, max_size=100))
def test_any_printable_file_id_survives_the_round_trip(file_id: str) -> None:
    token = ids.attachment_token(file_id)

    assert ids.portal_file_id(token) == file_id
    assert ids.parse_attachment_id(token) == token


@pytest.mark.parametrize("bad", ["", "line\nbreak", "tab\there", "x" * 769, "ñ" * 385, "\ud800"])
def test_a_file_id_the_portal_could_not_have_sent_gets_no_token(bad: str) -> None:
    with pytest.raises(ids.InvalidIdError):
        ids.attachment_token(bad)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "a b",
        "a/b",
        "YQ==",
        "YQ+/",
        "A",
        "QR",
        "YWJ",
        token_of(b"\xff"),
        token_of(b"a\nb"),
        token_of(b"x" * (ids.MAX_FILE_ID_BYTES + 1)),
        "ñ",
    ],
    ids=[
        "empty",
        "space",
        "slash",
        "padding",
        "standard-alphabet",
        "one-character",
        "alias-of-QQ",
        "alias-of-YWI",
        "not-utf8",
        "not-printable",
        "too-long",
        "not-ascii",
    ],
)
def test_text_that_no_file_gets_as_a_token_is_refused(bad: str) -> None:
    with pytest.raises(ids.InvalidIdError) as caught:
        ids.parse_attachment_id(bad)

    assert caught.value.kind == "attachment id"

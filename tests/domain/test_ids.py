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


def test_attachment_ids_are_opaque_but_must_be_short_printable_text() -> None:
    assert ids.parse_attachment_id("2a7f.report 1.pdf") == "2a7f.report 1.pdf"
    for bad in ["", "line\nbreak", "tab\there", "x" * 513]:
        with pytest.raises(ids.InvalidIdError):
            ids.parse_attachment_id(bad)

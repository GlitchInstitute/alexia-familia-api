"""The name a client is told to save a file under."""

import re
import unicodedata
from urllib.parse import unquote

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.api.files import (
    FALLBACK_NAME,
    MAX_NAME_CHARACTERS,
    clean_name,
    content_disposition,
)

HEADER = re.compile(
    r"""attachment; filename="([A-Za-z0-9 ._-]+)"; filename\*=UTF-8''([A-Za-z0-9%_.~-]+)"""
)


def test_a_name_with_accents_is_given_in_both_forms() -> None:
    assert content_disposition("Autorización museo.pdf") == (
        'attachment; filename="Autorizacion museo.pdf"; '
        "filename*=UTF-8''Autorizaci%C3%B3n%20museo.pdf"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("informe.pdf", "informe.pdf"),
        ("a/b\\c.pdf", "a_b_c.pdf"),
        ("  .oculto  ", "oculto"),
        ("a.", "a"),
        ("...", FALLBACK_NAME),
        ("", FALLBACK_NAME),
        ("   ", FALLBACK_NAME),
        ("ficha\u202egpj.exe", "fichagpj.exe"),
        ("a\u200bb", "ab"),
        ("a\x00b\nc\td\x7fe", "abcde"),
        ("a\u2028b\u2029c", "abc"),
        ("a\ud800b", "ab"),
        ("文件.pdf", "文件.pdf"),
    ],
)
def test_a_name_loses_what_could_mislead_a_person_or_break_a_file_system(
    name: str, expected: str
) -> None:
    assert clean_name(name) == expected


def test_a_name_of_the_longest_size_is_kept_whole() -> None:
    name = "a" * (MAX_NAME_CHARACTERS - 4) + ".pdf"

    assert clean_name(name) == name


def test_a_name_is_cut_to_its_last_200_characters() -> None:
    assert clean_name("a" + "b" * 250) == "b" * 200


def test_a_name_with_nothing_left_is_saved_as_file() -> None:
    assert content_disposition("...") == "attachment; filename=\"file\"; filename*=UTF-8''file"


def test_a_name_that_is_too_long_keeps_its_end_where_the_extension_is() -> None:
    shown = clean_name("a" + "b" * MAX_NAME_CHARACTERS + ".pdf")

    assert len(shown) == MAX_NAME_CHARACTERS
    assert shown.endswith("b.pdf")
    assert not shown.startswith("a")


@pytest.mark.parametrize("mark", [" ", "."])
def test_a_cut_that_lands_on_a_space_or_a_dot_does_not_leave_it_at_the_start(mark: str) -> None:
    name = "z" * 50 + mark + "y" * (MAX_NAME_CHARACTERS - 1)

    assert clean_name(name) == "y" * (MAX_NAME_CHARACTERS - 1)


@pytest.mark.parametrize(
    ("name", "plain"),
    [
        ("Ñandú.txt", "Nandu.txt"),
        ("ficha\u202egpj.exe", "fichagpj.exe"),
        ("  informe.pdf  ", "informe.pdf"),
        ("\uff21\uff22.pdf", "AB.pdf"),
        ("文件.pdf", "__.pdf"),
        ("\U0001d242", FALLBACK_NAME),
        ("\u0301.pdf", "pdf"),
        ("a.\u0301", "a"),
        ('a"b.pdf', "a_b.pdf"),
        ("a;b=c.pdf", "a_b_c.pdf"),
        ("100%.pdf", "100_.pdf"),
        ("it's.pdf", "it_s.pdf"),
        ("a b-c_d.e.pdf", "a b-c_d.e.pdf"),
    ],
)
def test_the_plain_form_keeps_letters_digits_and_a_few_marks_only(name: str, plain: str) -> None:
    match = HEADER.fullmatch(content_disposition(name))

    assert match is not None
    assert match.group(1) == plain


def test_the_encoded_form_escapes_every_mark_that_is_not_plainly_safe() -> None:
    header = content_disposition("it's (1)*.pdf")

    assert header.endswith("filename*=UTF-8''it%27s%20%281%29%2A.pdf")


@given(st.text(max_size=300))
def test_any_name_gives_a_one_line_ascii_header_that_names_the_cleaned_file(name: str) -> None:
    header = content_disposition(name)
    match = HEADER.fullmatch(header)

    assert header.isascii()
    assert header.isprintable()
    assert match is not None
    assert unquote(match.group(2)) == clean_name(name)
    assert match.group(1) == match.group(1).strip(" .")


@given(st.text(max_size=300))
def test_a_cleaned_name_is_never_empty_never_long_and_never_holds_what_was_taken_out(
    name: str,
) -> None:
    shown = clean_name(name)

    assert 0 < len(shown) <= MAX_NAME_CHARACTERS
    assert "/" not in shown
    assert "\\" not in shown
    assert not any(unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for char in shown)
    assert shown == shown.strip(" .")


@given(st.text(max_size=300))
def test_cleaning_a_cleaned_name_changes_nothing(name: str) -> None:
    assert clean_name(clean_name(name)) == clean_name(name)

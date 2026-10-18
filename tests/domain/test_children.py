"""Child names become short, unique, stable slugs for URLs."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from alexia_api.domain.children import (
    Child,
    Guardian,
    StaffMember,
    TrackingCounters,
    assign_slugs,
    slugify,
)
from alexia_api.domain.ids import (
    MAX_SLUG_LENGTH,
    InvalidIdError,
    parse_child_slug,
    parse_person_id,
    parse_staff_id,
    parse_student_id,
)


def guid(number: int) -> str:
    return f"5afe0000-0000-4000-8000-{number:012x}"


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Lucía", "lucia"),
        ("Álvaro Íñigo", "alvaro-inigo"),
        ("  Eva--Zoë ", "eva-zoe"),
        ("Ñandú", "nandu"),
        ("O'Brien", "o-brien"),
        ("日本", "child"),
        ("", "child"),
        ("---", "child"),
    ],
)
def test_a_name_folds_to_ascii_words(name: str, slug: str) -> None:
    assert slugify(name) == slug


def test_a_long_name_is_cut_and_never_ends_in_a_hyphen() -> None:
    assert slugify("a" * 50) == "a" * (MAX_SLUG_LENGTH - 4)
    assert slugify("a" * 35 + " b") == "a" * 35


def test_the_smallest_student_id_keeps_the_plain_slug() -> None:
    first, second, third = (parse_student_id(guid(n)) for n in (1, 2, 3))

    slugs = assign_slugs([(third, "Ana"), (first, "Ana"), (second, "Ana")])

    assert slugs == {first: "ana", second: "ana-2", third: "ana-3"}


def test_a_suffix_never_collides_with_a_natural_slug() -> None:
    first, second, third = (parse_student_id(guid(n)) for n in (1, 2, 3))

    slugs = assign_slugs([(first, "Ana"), (second, "Ana"), (third, "Ana 2")])

    assert len(set(slugs.values())) == 3
    assert slugs[third] == "ana-2-2"


def test_no_children_means_no_slugs() -> None:
    assert assign_slugs([]) == {}


guids = st.integers(min_value=0, max_value=2**40).map(guid)


@given(st.lists(st.tuples(guids, st.text(max_size=60)), unique_by=lambda pair: pair[0], max_size=8))
def test_slugs_are_unique_valid_and_independent_of_input_order(
    children: list[tuple[str, str]],
) -> None:
    typed = [(parse_student_id(student_id), name) for student_id, name in children]

    slugs = assign_slugs(typed)

    assert len(set(slugs.values())) == len(typed)
    for slug in slugs.values():
        assert len(slug) <= MAX_SLUG_LENGTH
        assert parse_child_slug(slug) == slug
    assert assign_slugs(list(reversed(typed))) == slugs


def test_a_slug_is_not_a_child_id() -> None:
    with pytest.raises(InvalidIdError):
        parse_child_slug("Not A Slug")


def test_the_models_are_frozen_and_refuse_unknown_fields() -> None:
    guardian = Guardian(person_id=parse_person_id(guid(1)), first_name="Marta")

    with pytest.raises(ValidationError):
        guardian.first_name = "Other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Guardian(person_id=parse_person_id(guid(1)), first_name="Marta", extra="x")  # type: ignore[call-arg]


def test_counters_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        TrackingCounters(tasks=-1, activities=0, notes=0, tests=0, incidents=0)


def test_a_child_and_a_staff_member_carry_their_ids() -> None:
    child = Child(
        id=parse_student_id(guid(1)),
        person_id=parse_person_id(guid(2)),
        slug=parse_child_slug("lucia"),
        name="Lucía Ejemplo",
        first_name="Lucía",
        relation=None,
    )
    staff = StaffMember(id=parse_staff_id(guid(3)), name="Ana", role=None)

    assert (child.slug, child.relation, staff.role) == ("lucia", None, None)

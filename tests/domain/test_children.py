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
    apply_pins,
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


def a_child(number: int, first_name: str, slug: str) -> Child:
    return Child(
        id=parse_student_id(guid(number)),
        person_id=parse_person_id(guid(number + 1000)),
        slug=parse_child_slug(slug),
        name=f"{first_name} Ejemplo",
        first_name=first_name,
        relation=None,
    )


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


def test_a_pinned_slug_wins_and_the_others_work_around_it() -> None:
    first, second = (parse_student_id(guid(n)) for n in (1, 2))

    slugs = assign_slugs(
        [(first, "Ana"), (second, "Ana")], pinned={second: parse_child_slug("ana")}
    )

    assert slugs == {second: "ana", first: "ana-2"}


def test_a_pinned_slug_may_differ_from_the_name() -> None:
    only = parse_student_id(guid(1))

    assert assign_slugs([(only, "Ana")], pinned={only: parse_child_slug("the-eldest")}) == {
        only: "the-eldest"
    }


def test_a_pin_for_a_child_the_portal_no_longer_lists_frees_its_slug() -> None:
    present, gone = (parse_student_id(guid(n)) for n in (1, 2))

    slugs = assign_slugs([(present, "Ana")], pinned={gone: parse_child_slug("ana")})

    assert slugs == {present: "ana"}


def test_two_children_pinned_to_one_slug_are_refused() -> None:
    first, second = (parse_student_id(guid(n)) for n in (1, 2))
    shared = parse_child_slug("twins")

    with pytest.raises(ValueError, match="same slug"):
        assign_slugs([(first, "Ana"), (second, "Eva")], pinned={first: shared, second: shared})


def test_pins_are_applied_to_whole_children_without_changing_the_originals() -> None:
    children = [a_child(1, "Ana", "ana"), a_child(2, "Ana", "ana-2")]

    pinned = apply_pins(children, {children[1].id: parse_child_slug("ana")})

    assert [(child.id, child.slug) for child in pinned] == [
        (children[0].id, "ana-2"),
        (children[1].id, "ana"),
    ]
    assert [child.slug for child in children] == ["ana", "ana-2"]


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


@given(
    st.lists(st.tuples(guids, st.text(max_size=60)), unique_by=lambda pair: pair[0], max_size=8),
    st.integers(min_value=0, max_value=8),
)
def test_pinned_slugs_are_kept_and_every_slug_stays_unique(
    children: list[tuple[str, str]], how_many: int
) -> None:
    typed = [(parse_student_id(student_id), name) for student_id, name in children]
    pinned = {
        student_id: parse_child_slug(f"pin-{index}")
        for index, (student_id, _) in enumerate(typed[:how_many])
    }

    slugs = assign_slugs(typed, pinned)

    assert {student_id: slugs[student_id] for student_id in pinned} == pinned
    assert len(set(slugs.values())) == len(typed)
    assert assign_slugs(list(reversed(typed)), pinned) == slugs


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

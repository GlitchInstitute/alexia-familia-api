"""Reading the guardian and the children from the home page."""

import pytest

from alexia_api.domain.children import Guardian
from alexia_api.domain.errors import PortalError, SessionExpired, UnexpectedReply
from alexia_api.domain.ids import parse_person_id
from alexia_api.portal.children import parse_home, read_home
from alexia_api.sim.app import render_home
from alexia_api.sim.world import DEMO_USER_A, default_world, synthetic_guid
from tests.harness import A_NEW_SIBLING, Failure, Harness


def photo(person: int) -> str:
    key = synthetic_guid(person)
    return f"/ACWeb/controladores/ControladorFotografias.ashx?tipo=2&amp;key={key}&amp;formato=0"


def tracked(student: int, person: int, name: str, *, student_text: str | None = None) -> str:
    student_id = student_text if student_text is not None else synthetic_guid(student)
    return (
        f'<li onclick="javascript:CambiarHijoSeguimiento(event);" hijo="{student_id}">'
        f'<a href="#"><img src="{photo(person)}"><p>{name}</p></a></li>'
    )


def picker(person: int, first: str, relation: str, *, flag: str = "False") -> str:
    return (
        f"<li onclick=\"javascript:HijoClicked(this,'{synthetic_guid(person)}', '{flag}');\">"
        f"<strong>{relation}</strong><h3>{first}</h3></li>"
    )


def page(tracked_items: list[str], picker_items: list[str]) -> str:
    return (
        f'<ul class="lienzo_hijos">{"".join(tracked_items)}</ul>'
        f'<ul class="lista_users">{"".join(picker_items)}</ul>'
    )


def test_reads_the_guardian_and_both_children() -> None:
    snapshot = parse_home(render_home(default_world().families[0]))

    assert snapshot.guardian == Guardian(
        person_id=parse_person_id(synthetic_guid(0x301)), first_name="Marta"
    )
    assert [
        (child.id, child.person_id, child.slug, child.name, child.first_name, child.relation)
        for child in snapshot.children
    ] == [
        (
            synthetic_guid(0x101),
            synthetic_guid(0x201),
            "lucia",
            "Lucía Ejemplo Muestra",
            "Lucía",
            "Hija",
        ),
        (
            synthetic_guid(0x102),
            synthetic_guid(0x202),
            "mateo",
            "Mateo Ejemplo Muestra",
            "Mateo",
            "Hijo",
        ),
    ]


def test_reads_the_other_family_too() -> None:
    snapshot = parse_home(render_home(default_world().families[1]))

    assert [child.slug for child in snapshot.children] == ["hugo", "alba"]


def test_a_home_page_that_lists_no_guardian_still_lists_the_children() -> None:
    html = render_home(default_world().families[0], guardian_listed=False)

    snapshot = parse_home(html)

    assert snapshot.guardian is None
    assert [child.slug for child in snapshot.children] == ["lucia", "mateo"]


async def test_the_simulator_can_serve_a_home_page_without_a_guardian(harness: Harness) -> None:
    harness.sim.options.home_without_guardian = True

    snapshot = await harness.gateway().call(read_home)

    assert snapshot.guardian is None
    assert [child.slug for child in snapshot.children] == ["lucia", "mateo"]


def test_a_child_missing_from_the_switcher_falls_back_to_the_full_name() -> None:
    html = page(
        [tracked(0x101, 0x201, "Lucía Ejemplo Muestra")],
        [picker(0x301, "Marta", "Madre", flag="True")],
    )

    [child] = parse_home(html).children

    assert child.first_name == "Lucía"
    assert child.relation is None


def test_entries_with_ids_that_are_not_guids_are_skipped() -> None:
    html = page(
        [
            tracked(0x101, 0x201, "Lucía Ejemplo Muestra"),
            tracked(0x102, 0x202, "Bad Student", student_text="123"),
            '<li hijo="'
            + synthetic_guid(0x103)
            + '"><img src="/photo?key=nope"><p>No Key</p></li>',
        ],
        [
            picker(0x201, "Lucía", "Hija"),
            "<li onclick=\"javascript:HijoClicked(this,'nope', 'False');\"><h3>Ghost</h3></li>",
        ],
    )

    snapshot = parse_home(html)

    assert [child.first_name for child in snapshot.children] == ["Lucía"]


def test_siblings_with_one_first_name_get_distinct_slugs_in_id_order() -> None:
    html = page(
        [tracked(0x102, 0x202, "Ana Segunda"), tracked(0x101, 0x201, "Ana Primera")],
        [],
    )

    snapshot = parse_home(html)

    assert {child.id: child.slug for child in snapshot.children} == {
        synthetic_guid(0x101): "ana",
        synthetic_guid(0x102): "ana-2",
    }
    assert [child.name for child in snapshot.children] == ["Ana Segunda", "Ana Primera"]


def test_a_guardian_without_children_is_a_valid_page() -> None:
    snapshot = parse_home(page([], [picker(0x301, "Marta", "Madre", flag="True")]))

    assert snapshot.children == ()
    assert snapshot.guardian is not None
    assert snapshot.guardian.first_name == "Marta"


def test_the_guardian_flag_is_case_insensitive() -> None:
    snapshot = parse_home(page([], [picker(0x301, "Marta", "Madre", flag="TRUE")]))

    assert snapshot.guardian is not None


def test_a_page_with_neither_children_nor_guardian_is_unexpected() -> None:
    with pytest.raises(PortalError) as raised:
        parse_home("<html><body>nothing here</body></html>")

    assert raised.value.detail == UnexpectedReply(where="home: no child or guardian switcher")


def test_names_have_their_whitespace_collapsed() -> None:
    html = page([tracked(0x101, 0x201, "  Lucía \n  Ejemplo   Muestra ")], [])

    [child] = parse_home(html).children

    assert child.name == "Lucía Ejemplo Muestra"


async def test_reads_the_home_page_through_a_signed_in_gateway(harness: Harness) -> None:
    snapshot = await harness.gateway().call(read_home)

    assert [child.slug for child in snapshot.children] == ["lucia", "mateo"]


async def test_a_change_at_the_portal_shows_to_a_session_that_is_already_open(
    harness: Harness,
) -> None:
    gateway = harness.gateway()
    await gateway.call(read_home)

    harness.enrol(DEMO_USER_A, A_NEW_SIBLING)
    snapshot = await gateway.call(read_home)

    assert [child.slug for child in snapshot.children] == ["lucia", "mateo", "ines"]
    assert harness.sim.counters.login_attempts == 1


async def test_an_expired_session_is_reported_when_reading_home(
    harness: Harness, failure: Failure
) -> None:
    detail = await failure(read_home(harness.session()))

    assert detail == SessionExpired()

"""Reading the staff a guardian can meet about a child."""

import pytest

from alexia_api.domain.children import StaffMember
from alexia_api.domain.ids import parse_staff_id, parse_student_id
from alexia_api.portal import wire
from alexia_api.portal.roster import parse_roster, parse_roster_text, read_roster
from alexia_api.sim.world import default_world, synthetic_guid
from tests.harness import Harness


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Ana Muestra (Tutora)", ("Ana Muestra", "Tutora")),
        ("  Ana   Muestra   (Tutora)  ", ("Ana   Muestra", "Tutora")),
        ("Ana Muestra (Lengua) (Tutora)", ("Ana Muestra (Lengua)", "Tutora")),
        ("Ana Muestra", ("Ana Muestra", None)),
        ("Ana Muestra (  )", ("Ana Muestra", None)),
        ("Ana Muestra ()", ("Ana Muestra", None)),
        ("(Only a role)", ("", "Only a role")),
        ("", ("", None)),
    ],
)
def test_splits_the_name_from_the_trailing_role(
    text: str, expected: tuple[str, str | None]
) -> None:
    assert parse_roster_text(text) == expected


def test_keeps_valid_staff_and_skips_placeholders_and_nameless_entries() -> None:
    items = [
        wire.RosterItem(value="", text="-- Seleccione --"),
        wire.RosterItem(value="not-a-guid", text="Junk (Role)"),
        wire.RosterItem(value=synthetic_guid(0x601).upper(), text="Ana Muestra (Tutora)"),
        wire.RosterItem(value=synthetic_guid(0x602), text="(Only a role)"),
        wire.RosterItem(value=synthetic_guid(0x603), text="Rosa Prueba"),
    ]

    assert parse_roster(items) == [
        StaffMember(id=parse_staff_id(synthetic_guid(0x601)), name="Ana Muestra", role="Tutora"),
        StaffMember(id=parse_staff_id(synthetic_guid(0x603)), name="Rosa Prueba", role=None),
    ]


def test_an_empty_list_is_an_empty_roster() -> None:
    assert parse_roster([]) == []


async def test_reads_the_staff_the_portal_lists_for_a_child(harness: Harness) -> None:
    child = default_world().families[0].children[0]

    staff = await harness.gateway().call(
        lambda tx: read_roster(tx, parse_student_id(child.student_id))
    )

    assert [(member.id, member.name, member.role) for member in staff] == [
        (synthetic_guid(0x601), "Ana Muestra Tutora", "Tutora"),
        (synthetic_guid(0x602), "Carlos Ejemplo Profesor", "Matemáticas"),
    ]

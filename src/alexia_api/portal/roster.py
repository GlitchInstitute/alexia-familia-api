"""Reading the staff a guardian can meet about one child."""

import re

from alexia_api.domain.children import StaffMember
from alexia_api.domain.ids import InvalidIdError, StudentId, parse_staff_id
from alexia_api.portal import wire
from alexia_api.portal.allowlist import GET_ROSTER
from alexia_api.portal.session import Tx
from alexia_api.portal.ws import call_ws

_ROLE_SUFFIX = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")


def parse_roster_text(text: str) -> tuple[str, str | None]:
    """Split "Name (Role)" into the name and the role. The role is the last bracketed part."""
    stripped = text.strip()
    found = _ROLE_SUFFIX.match(stripped)
    if found is None:
        return stripped, None
    return found.group(1).strip(), found.group(2).strip() or None


def parse_roster(reply: list[wire.RosterItem]) -> list[StaffMember]:
    """Keep the entries with a valid employee id and a name. The portal sometimes lists others."""
    members: list[StaffMember] = []
    for item in reply:
        try:
            staff_id = parse_staff_id(item.value)
        except InvalidIdError:
            continue
        name, role = parse_roster_text(item.text)
        if name:
            members.append(StaffMember(id=staff_id, name=name, role=role))
    return members


async def read_roster(tx: Tx, student_id: StudentId) -> list[StaffMember]:
    return parse_roster(await call_ws(tx, GET_ROSTER, wire.RosterParams(student_id=student_id)))

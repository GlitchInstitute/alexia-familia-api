"""Typed identifiers.

The portal names almost everything with a GUID, and it uses two GUIDs for one child. The student
id feeds the tracking widget, the staff roster, and the grids. The person id feeds the agenda and
the photo. Mixing them works in a test and fails in production, so each kind of id gets its own
type and a parser that lower-cases the GUID and rejects anything else.
"""

import re
from collections.abc import Callable
from typing import Final, NewType

GUID_PATTERN: Final = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SLUG_PATTERN: Final = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_SLUG_LENGTH: Final = 40
MAX_ATTACHMENT_ID_LENGTH: Final = 512

_GUID = re.compile(GUID_PATTERN)
_SLUG = re.compile(SLUG_PATTERN)

StudentId = NewType("StudentId", str)
PersonId = NewType("PersonId", str)
StaffId = NewType("StaffId", str)
RoleId = NewType("RoleId", str)
MessageId = NewType("MessageId", str)
FormId = NewType("FormId", str)
MeetingId = NewType("MeetingId", str)
AbsenceId = NewType("AbsenceId", str)
OutboxId = NewType("OutboxId", str)
AttachmentId = NewType("AttachmentId", str)
AccountId = NewType("AccountId", str)
ChildSlug = NewType("ChildSlug", str)


class InvalidIdError(ValueError):
    """A string that is not the kind of identifier it was meant to be.

    The message names the kind and never the value, because a bad value is often a pasted secret.
    """

    def __init__(self, kind: str) -> None:
        super().__init__(f"not a valid {kind}")
        self.kind = kind


def _guid_parser[T](kind: str, make: Callable[[str], T]) -> Callable[[str], T]:
    def parse(value: str) -> T:
        if _GUID.fullmatch(value) is None:
            raise InvalidIdError(kind)
        return make(value.lower())

    return parse


def _slug_parser[T](kind: str, make: Callable[[str], T]) -> Callable[[str], T]:
    def parse(value: str) -> T:
        if len(value) > MAX_SLUG_LENGTH or _SLUG.fullmatch(value) is None:
            raise InvalidIdError(kind)
        return make(value)

    return parse


parse_student_id = _guid_parser("student id", StudentId)
parse_person_id = _guid_parser("person id", PersonId)
parse_staff_id = _guid_parser("staff id", StaffId)
parse_role_id = _guid_parser("role id", RoleId)
parse_message_id = _guid_parser("message id", MessageId)
parse_form_id = _guid_parser("form id", FormId)
parse_meeting_id = _guid_parser("meeting id", MeetingId)
parse_absence_id = _guid_parser("absence id", AbsenceId)
parse_outbox_id = _guid_parser("outbox id", OutboxId)

parse_account_id = _slug_parser("account id", AccountId)
parse_child_slug = _slug_parser("child slug", ChildSlug)


def parse_attachment_id(value: str) -> AttachmentId:
    """Accept the portal's opaque file id. It is not a GUID, so only its shape is checked."""
    if not value or len(value) > MAX_ATTACHMENT_ID_LENGTH or not value.isprintable():
        raise InvalidIdError("attachment id")
    return AttachmentId(value)

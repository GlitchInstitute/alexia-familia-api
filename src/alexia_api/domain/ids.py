"""Typed identifiers.

The portal names almost everything with a GUID, and it uses two GUIDs for one child. The student
id feeds the tracking widget, the staff roster, and the grids. The person id feeds the agenda and
the photo. Mixing them works in a test and fails in production, so each kind of id gets its own
type and a parser that lower-cases the GUID and rejects anything else.
"""

import base64
import re
from collections.abc import Callable
from typing import Final, NewType

GUID_PATTERN: Final = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
SLUG_PATTERN: Final = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_SLUG_LENGTH: Final = 40
MAX_FILE_ID_BYTES: Final = 768

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


def _is_file_id(text: str) -> bool:
    return bool(text) and text.isprintable() and len(text.encode("utf-8")) <= MAX_FILE_ID_BYTES


def attachment_token(file_id: str) -> AttachmentId:
    """Name a file by a token that is safe in a URL path.

    The portal's file id is any printable text and is not a GUID. Some ids hold slashes, percent
    signs, or spaces, and a path breaks on them. The token is the id's UTF-8 bytes in URL-safe
    base64 without padding. Clients treat it as opaque. The server reads it back with
    `portal_file_id`.
    """
    if not _is_file_id(file_id):
        raise InvalidIdError("attachment id")
    encoded = base64.urlsafe_b64encode(file_id.encode("utf-8"))
    return AttachmentId(encoded.rstrip(b"=").decode("ascii"))


def _decode_token(value: str) -> str:
    """Decode loosely, then demand that encoding the result gives back the same text.

    That one comparison refuses padding, stray characters, the standard alphabet's `+` and `/`,
    and the other spellings base64 allows for the same bytes. It also refuses an id the portal
    could not have sent, because `attachment_token` does.
    """
    try:
        file_id = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
    except ValueError:
        raise InvalidIdError("attachment id") from None
    if attachment_token(file_id) != value:
        raise InvalidIdError("attachment id")
    return file_id


def parse_attachment_id(value: str) -> AttachmentId:
    """Accept a token that `attachment_token` made, and only the exact text it makes.

    One file has one token, so a token can be compared as text.
    """
    _decode_token(value)
    return AttachmentId(value)


def portal_file_id(token: AttachmentId) -> str:
    """The portal's own id for the file that a token names."""
    return _decode_token(token)

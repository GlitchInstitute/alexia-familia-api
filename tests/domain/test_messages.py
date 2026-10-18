"""The folders that hold messages, and a message as the list and its page describe it."""

from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from alexia_api.domain.ids import AttachmentId, MessageId
from alexia_api.domain.messages import (
    FOLDER_NAMES,
    Attachment,
    Body,
    Folder,
    Link,
    Message,
    MessageContent,
    MessageSummary,
    Translation,
)

SUMMARY = MessageSummary(
    id=MessageId("5afe0000-0000-4000-8000-000000001001"),
    read=False,
    institutional=False,
    sender="Ana Muestra Tutora",
    subject="Reto de matemáticas",
    received_on=date(2026, 10, 15),
    expires_on=None,
    anonymous=False,
    category="Aviso",
    has_attachments=True,
)
BODY = Body(html="<p>Hola</p>", text="Hola", simplified=False)
CONTENT = MessageContent(
    sent_at=datetime(2026, 10, 15, 9, 12, tzinfo=timezone(timedelta(hours=2))),
    body=BODY,
    links=(Link(url="https://example.test/a", host="example.test", kind="other"),),
    attachments=(Attachment(id=AttachmentId("YS5wZGY"), name="a.pdf", size=3),),
    translations=(),
    child_names=None,
    can_reply=True,
)


def test_the_folders_the_api_serves_are_received_and_sent() -> None:
    assert FOLDER_NAMES == ("received", "sent")


def test_a_folder_count_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        Folder(name="received", label="Recibidos", count=-1)


def test_a_folder_must_be_one_the_api_serves() -> None:
    with pytest.raises(ValidationError):
        Folder(name="drafts", label="Borradores", count=None)  # type: ignore[arg-type]


def test_a_folder_is_frozen_and_refuses_unknown_fields() -> None:
    folder = Folder(name="sent", label="Enviados", count=None)

    with pytest.raises(ValidationError):
        folder.count = 3  # type: ignore[misc]
    with pytest.raises(ValidationError):
        Folder(name="sent", label="Enviados", count=None, extra=1)  # type: ignore[call-arg]


def test_a_message_is_a_row_of_the_list_joined_to_its_page() -> None:
    message = Message.of(SUMMARY, CONTENT)

    assert message.id == SUMMARY.id
    assert message.subject == SUMMARY.subject
    assert message.read is False
    assert message.body == BODY
    assert message.attachments == CONTENT.attachments
    assert message.sent_at == CONTENT.sent_at


def test_the_row_and_the_page_share_no_field_so_neither_can_hide_the_other() -> None:
    assert not set(MessageSummary.model_fields) & set(MessageContent.model_fields)


def test_the_fields_of_the_row_come_before_the_fields_of_the_page() -> None:
    assert list(Message.model_fields) == [
        *MessageSummary.model_fields,
        *MessageContent.model_fields,
    ]


def test_a_message_keeps_the_offset_of_the_school_in_json() -> None:
    assert '"sent_at":"2026-10-15T09:12:00+02:00"' in Message.of(SUMMARY, CONTENT).model_dump_json()


def test_the_time_a_message_was_sent_must_say_its_offset() -> None:
    naive = {**CONTENT.model_dump(), "sent_at": datetime(2026, 10, 15, 9, 12)}

    with pytest.raises(ValidationError, match="sent_at"):
        MessageContent.model_validate(naive)


def test_an_attachment_cannot_be_smaller_than_nothing() -> None:
    with pytest.raises(ValidationError):
        Attachment(id=AttachmentId("YQ"), name="a", size=-1)


@pytest.mark.parametrize("slot", [1, 4])
def test_a_translation_is_the_second_or_the_third_version(slot: int) -> None:
    with pytest.raises(ValidationError):
        Translation(slot=slot, subject="Hello", body=BODY)  # type: ignore[arg-type]

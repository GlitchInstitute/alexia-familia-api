"""Messages between the school and the guardian, and the folders that hold them."""

from datetime import date
from typing import Final, Literal, get_args

from pydantic import Field

from alexia_api.domain.base import Model
from alexia_api.domain.ids import MessageId

FolderName = Literal["received", "sent"]
FOLDER_NAMES: Final[tuple[FolderName, ...]] = get_args(FolderName)


class Folder(Model):
    """A folder of messages, as the portal lists it."""

    name: FolderName = Field(description="`received` or `sent`. The message routes take this name.")
    label: str = Field(
        description="The folder's name as the portal shows it, in the school's language."
    )
    count: int | None = Field(
        ge=0,
        description=(
            "The number the portal prints next to the folder's name, or null when it prints "
            "none. Treat it as a hint. The message list reports the exact total."
        ),
    )


class MessageSummary(Model):
    """A message as the portal lists it, without its text."""

    id: MessageId = Field(
        description="The portal's message id. The detail and attachment routes take it."
    )
    read: bool | None = Field(
        description=(
            "Whether the guardian has read the message, or null when the portal's icon is not "
            "one this API knows."
        )
    )
    institutional: bool = Field(description="True for a message sent in the school's own name.")
    sender: str = Field(description="The sender's name as the portal shows it.")
    subject: str
    received_on: date = Field(
        description="The day the portal lists the message under, on the school's calendar."
    )
    expires_on: date | None = Field(
        description="The last day the portal shows the message, when it has one."
    )
    anonymous: bool = Field(description="True when the portal marks the message as anonymous.")
    category: str | None = Field(description="The category the portal files the message under.")
    has_attachments: bool = Field(description="True when the portal shows a paperclip.")

"""Messages between the school and the guardian, and the folders that hold them."""

from datetime import date
from typing import Final, Literal, Self, get_args

from pydantic import AwareDatetime, Field

from alexia_api.domain.base import Model
from alexia_api.domain.ids import AttachmentId, MessageId

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


class Body(Model):
    """The words of a message, as safe HTML and as plain text."""

    html: str = Field(
        description=(
            "The message as HTML that is safe to show. Scripts, styles, forms, frames, and event "
            "handlers are gone, and so are classes and inline styles. A link keeps only an "
            "`http`, `https`, `mailto`, or `tel` address. An image stays only when the message "
            "carries it inline as a PNG, JPEG, GIF, or WebP picture."
        )
    )
    text: str = Field(
        description=(
            "The message as plain text. A blank line separates paragraphs. A list item starts "
            "with `- `, or with its number and a dot in a numbered list, and a list inside a list "
            "is indented by two spaces. Table cells in a row are separated by ` | `. A link shows "
            "its address in parentheses after its words."
        )
    )
    simplified: bool = Field(
        description=(
            "True when the message was nested too deeply to read as HTML. Then `html` holds only "
            "the words of the message, in one paragraph."
        )
    )


LinkKind = Literal["email", "video_call", "form", "video", "document", "other"]


class Link(Model):
    """An address that a message mentions, in a link or in its words."""

    url: str = Field(description="The address as the message writes it.")
    host: str = Field(
        description=(
            "The host the address points to, without a leading `www.`. For a mail address, the "
            "part after the `@`."
        )
    )
    kind: LinkKind = Field(
        description=(
            "What the address is for, judged from its host and its file name. `other` when it "
            "is none of the kinds this API knows."
        )
    )


class Attachment(Model):
    """A file that came with a message."""

    id: AttachmentId = Field(
        description=(
            "A token that names the file within its message. Treat it as opaque. It is safe to "
            "put in a URL path."
        )
    )
    name: str = Field(description="The file's name as the sender gave it.")
    size: int = Field(ge=0, description="The file's size in bytes, as the portal lists it.")


class Translation(Model):
    """The message in another language, when the sender wrote one."""

    slot: Literal[2, 3] = Field(
        description=(
            "The portal keeps up to three versions of a message and does not name their "
            "languages. The message itself is the first version, so a translation is the "
            "second or the third."
        )
    )
    subject: str
    body: Body


class MessageContent(Model):
    """What the page of a message adds to the message's row in the list."""

    sent_at: AwareDatetime = Field(
        description=(
            "When the school sent the message, to the minute, with the school's offset. The "
            "list gives only a day, and the time comes from the message itself."
        )
    )
    body: Body = Field(description="The words of the message.")
    links: tuple[Link, ...] = Field(
        description=(
            "The addresses in the body, each once. The ones in links come first, then the ones "
            "written out in the words. Translations are not searched."
        )
    )
    attachments: tuple[Attachment, ...]
    translations: tuple[Translation, ...] = Field(
        description="Other versions of the message, second before third. Empty when there are none."
    )
    child_names: str | None = Field(
        description=(
            "The names of the children the portal says the message is about, in the one text "
            "the portal writes them in, or null when it names none. The portal gives names and "
            "no ids, so this API cannot tie them to its list of children."
        )
    )
    can_reply: bool = Field(description="Whether the portal offers a reply to this message.")


class Message(MessageContent, MessageSummary):
    """A message with its words. The fields of its row in the list come first."""

    @classmethod
    def of(cls, summary: MessageSummary, content: MessageContent) -> Self:
        """Join a row of the list to the message page that the row opens."""
        return cls(**dict(summary), **dict(content))

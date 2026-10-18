"""Messages between the school and the guardian, and the folders that hold them."""

from typing import Final, Literal, get_args

from pydantic import Field

from alexia_api.domain.base import Model

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

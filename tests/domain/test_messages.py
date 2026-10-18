"""The folders that hold messages."""

import pytest
from pydantic import ValidationError

from alexia_api.domain.messages import FOLDER_NAMES, Folder


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

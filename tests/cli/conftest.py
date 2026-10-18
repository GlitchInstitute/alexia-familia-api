"""Every command-line test starts in an empty folder, so no file of the developer's is found."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder the command runs in. It is empty until a test puts a file there."""
    folder = tmp_path / "cwd"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder

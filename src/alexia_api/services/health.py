"""Checks on the server's own files, shared by the readiness route and the doctor command."""

import os
from pathlib import Path


def state_dir_writable(path: Path) -> bool:
    """Whether the server can keep its files in `path`.

    A directory that does not exist yet counts when the nearest parent that does exist can be
    written, because the server makes the directory when it first needs it. A place that cannot
    even be looked at, because a directory above it cannot be entered, does not count.
    """
    for place in (path, *path.parents):
        try:
            if place.exists():
                return place.is_dir() and os.access(place, os.W_OK | os.X_OK)
        except OSError:
            return False
    return False

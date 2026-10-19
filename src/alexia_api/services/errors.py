"""Failures that are the caller's doing and not the portal's."""

from typing import Literal

NotFoundKind = Literal["account", "child", "guardian", "staff", "message", "attachment", "form"]


class NotFoundError(Exception):
    """The caller named something this server does not have."""

    def __init__(self, kind: NotFoundKind, reference: str) -> None:
        super().__init__(f"no {kind} matches {reference!r}")
        self.kind = kind
        self.reference = reference

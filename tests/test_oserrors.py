"""The reason a failed system call gives, in words a person can read."""

import errno

from alexia_api.oserrors import why


def test_the_reason_the_system_gave_is_used() -> None:
    assert why(PermissionError(errno.EACCES, "Permission denied")) == "Permission denied"


def test_an_error_without_a_reason_is_named_by_its_kind() -> None:
    assert why(OSError("odd")) == "OSError"

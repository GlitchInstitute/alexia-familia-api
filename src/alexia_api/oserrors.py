"""Words for a call to the operating system that failed."""


def why(error: OSError) -> str:
    """The reason the system gave, or the kind of error when it gave none."""
    return error.strerror or type(error).__name__

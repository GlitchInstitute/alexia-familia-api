"""How a file is named to the client that saves it.

The name comes from the school and is free text. Before it reaches a header, anything that could
mislead a person or break a file system is taken out of it, and the header says the name in the
two forms that every client understands.
"""

import re
import unicodedata
from typing import Final
from urllib.parse import quote

MAX_NAME_CHARACTERS: Final = 200
FALLBACK_NAME: Final = "file"

_NEVER_SHOWN: Final = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})
_SEPARATORS: Final = str.maketrans({"/": "_", "\\": "_"})
_NOT_PLAIN_ASCII: Final = re.compile(r"[^A-Za-z0-9 ._-]")


def clean_name(name: str) -> str:
    """The name without control, invisible, and direction-changing characters or path separators.

    A character that reverses the text can make `fdp.exe` read as `exe.pdf`, so those go. Spaces
    and dots at either end go too, because they hide a file or are dropped by some systems. A name
    that is too long keeps its end, where the extension is. A name with nothing left is `file`.
    """
    shown = "".join(char for char in name if unicodedata.category(char) not in _NEVER_SHOWN)
    shown = shown.translate(_SEPARATORS).strip(" .")
    return shown[-MAX_NAME_CHARACTERS:].lstrip(" .") or FALLBACK_NAME


def _plain_ascii(name: str) -> str:
    """A name for the old clients that read no other form. Accents drop, other letters become _."""
    decomposed = unicodedata.normalize("NFKD", name)
    unmarked = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _NOT_PLAIN_ASCII.sub("_", unmarked)


def content_disposition(name: str) -> str:
    """A `Content-Disposition` header value that saves a file under a safe form of its name."""
    shown = clean_name(name)
    return (
        f"attachment; filename=\"{_plain_ascii(shown)}\"; filename*=UTF-8''{quote(shown, safe='')}"
    )

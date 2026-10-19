"""What a downloaded file is, judged from its first bytes.

The portal sends every attachment as `application/octet-stream`, whatever the file holds, so the
type has to come from the bytes. The types named here are the only ones this server ever
reports. A page of HTML is named `text/plain` and a vector picture is never named at all, so a
client that shows a file by its type cannot be made to run it.
"""

import codecs
from dataclasses import dataclass
from typing import Final

OCTET_STREAM: Final = "application/octet-stream"
MEBIBYTE: Final = 1024 * 1024
_TEXT_SAMPLE_BYTES: Final = 4096

_PREFIXES: Final[tuple[tuple[bytes, str], ...]] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"{\\rtf", "application/rtf"),
)
_ZIP_TYPES: Final = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
}
_OLE_TYPES: Final = {
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
}
_TEXT_TYPES: Final = {"csv": "text/csv", "ics": "text/calendar", "json": "application/json"}
_HEIF_BRANDS: Final = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"})

MEDIA_TYPES: Final = frozenset(
    {
        *(media_type for _, media_type in _PREFIXES),
        *_ZIP_TYPES.values(),
        *_OLE_TYPES.values(),
        *_TEXT_TYPES.values(),
        "image/webp",
        "image/heic",
        "image/avif",
        "image/bmp",
        "video/quicktime",
        "video/mp4",
        "application/zip",
        "application/x-ole-storage",
        "text/plain",
        OCTET_STREAM,
    }
)
"""Every type `sniff_media_type` can return."""


@dataclass(frozen=True, slots=True)
class Download:
    """A file the portal sent, with its name and the type its bytes show."""

    name: str
    media_type: str
    data: bytes


def _extension_of(name: str) -> str:
    _, dot, tail = name.rpartition(".")
    return tail.lower() if dot else ""


def _looks_like_text(data: bytes) -> bool:
    sample = data[:_TEXT_SAMPLE_BYTES]
    if not sample or b"\x00" in sample:
        return False
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample)
    except UnicodeDecodeError:
        return False
    return True


def _from_container_brand(brand: bytes) -> str:
    if brand in _HEIF_BRANDS:
        return "image/heic"
    if brand == b"avif":
        return "image/avif"
    return "video/quicktime" if brand == b"qt  " else "video/mp4"


def sniff_media_type(data: bytes, name: str = "") -> str:
    """The type that the first bytes of a file show, with its extension to tell similar ones apart.

    Office files are zip archives and older ones share one container, so only the extension
    separates them. Text is anything that reads as UTF-8 up to the first 4096 bytes. A file that
    is none of these is `application/octet-stream`.
    """
    for prefix, media_type in _PREFIXES:
        if data.startswith(prefix):
            return media_type
    extension = _extension_of(name)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        return _from_container_brand(data[8:12])
    if len(data) >= 26 and data.startswith(b"BM") and data[6:10] == b"\x00\x00\x00\x00":
        return "image/bmp"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return _ZIP_TYPES.get(extension, "application/zip")
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return _OLE_TYPES.get(extension, "application/x-ole-storage")
    if _looks_like_text(data):
        return _TEXT_TYPES.get(extension, "text/plain")
    return OCTET_STREAM

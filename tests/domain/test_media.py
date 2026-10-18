"""A downloaded file is named by its bytes, because the portal names every file the same way."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from alexia_api.domain.media import MEDIA_TYPES, OCTET_STREAM, sniff_media_type

PADDING = b"\x00" * 32
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
BMP = b"BM" + b"\x1a\x00\x00\x00" + b"\x00\x00\x00\x00" + b"\x00" * 18

CASES = [
    pytest.param(b"%PDF-1.4\n%%EOF\n", "a.pdf", "application/pdf", id="pdf"),
    pytest.param(b"\x89PNG\r\n\x1a\n" + PADDING, "a.png", "image/png", id="png"),
    pytest.param(b"\xff\xd8\xff\xe0" + PADDING, "a.jpg", "image/jpeg", id="jpeg"),
    pytest.param(b"GIF89a" + PADDING, "a.gif", "image/gif", id="gif"),
    pytest.param(b"RIFF\x24\x00\x00\x00WEBPVP8 " + PADDING, "a.webp", "image/webp", id="webp"),
    pytest.param(b"II*\x00" + PADDING, "a.tif", "image/tiff", id="tiff-little-endian"),
    pytest.param(b"MM\x00*" + PADDING, "a.tif", "image/tiff", id="tiff-big-endian"),
    pytest.param(BMP, "a.bmp", "image/bmp", id="bmp"),
    pytest.param(b"\x00\x00\x00\x18ftypheic" + PADDING, "a.heic", "image/heic", id="heic"),
    pytest.param(b"\x00\x00\x00\x18ftypmif1" + PADDING, "a.heif", "image/heic", id="heif"),
    pytest.param(b"\x00\x00\x00\x18ftypavif" + PADDING, "a.avif", "image/avif", id="avif"),
    pytest.param(b"\x00\x00\x00\x14ftypqt  " + PADDING, "a.mov", "video/quicktime", id="mov"),
    pytest.param(b"\x00\x00\x00\x18ftypisom" + PADDING, "a.mp4", "video/mp4", id="mp4"),
    pytest.param(b"PK\x03\x04" + PADDING, "a.zip", "application/zip", id="zip"),
    pytest.param(b"PK\x05\x06" + PADDING, "a.zip", "application/zip", id="zip-empty"),
    pytest.param(b"PK\x03\x04" + PADDING, "a.docx", DOCX, id="docx"),
    pytest.param(b"PK\x03\x04" + PADDING, "A.XLSX", XLSX, id="xlsx-in-capitals"),
    pytest.param(b"PK\x03\x04" + PADDING, "a.pptx", PPTX, id="pptx"),
    pytest.param(
        b"PK\x03\x04" + PADDING, "a.odt", "application/vnd.oasis.opendocument.text", id="odt"
    ),
    pytest.param(
        b"PK\x03\x04" + PADDING,
        "a.ods",
        "application/vnd.oasis.opendocument.spreadsheet",
        id="ods",
    ),
    pytest.param(
        b"PK\x03\x04" + PADDING,
        "a.odp",
        "application/vnd.oasis.opendocument.presentation",
        id="odp",
    ),
    pytest.param(OLE + PADDING, "a.doc", "application/msword", id="doc"),
    pytest.param(OLE + PADDING, "a.xls", "application/vnd.ms-excel", id="xls"),
    pytest.param(OLE + PADDING, "a.ppt", "application/vnd.ms-powerpoint", id="ppt"),
    pytest.param(OLE + PADDING, "a.bin", "application/x-ole-storage", id="ole-of-another-name"),
    pytest.param(b"{\\rtf1\\ansi Hola}", "a.rtf", "application/rtf", id="rtf"),
    pytest.param(b"Hola, familias.\n", "a.txt", "text/plain", id="text"),
    pytest.param("café".encode(), "", "text/plain", id="text-without-a-name"),
    pytest.param(b"a,b\n1,2\n", "a.csv", "text/csv", id="csv"),
    pytest.param(b"BEGIN:VCALENDAR\nEND:VCALENDAR\n", "a.ics", "text/calendar", id="ics"),
    pytest.param(b'{"a": 1}', "a.json", "application/json", id="json"),
    pytest.param(b"<html><script>alert(1)</script></html>", "a.html", "text/plain", id="html"),
    pytest.param(b'<svg xmlns="http://www.w3.org/2000/svg"/>', "a.svg", "text/plain", id="svg"),
    pytest.param(b"\x00\x01\x02\x03", "a.bin", OCTET_STREAM, id="binary"),
    pytest.param(b"", "a.pdf", OCTET_STREAM, id="empty"),
]


@pytest.mark.parametrize(("data", "name", "expected"), CASES)
def test_a_file_is_named_by_its_first_bytes(data: bytes, name: str, expected: str) -> None:
    assert sniff_media_type(data, name) == expected


def test_every_type_the_module_can_name_has_a_sample_and_no_sample_names_another() -> None:
    shown = {case.values[2] for case in CASES}

    assert shown == MEDIA_TYPES


def test_a_page_of_html_and_a_vector_picture_are_never_named_as_such() -> None:
    assert not any("html" in media_type or "svg" in media_type for media_type in MEDIA_TYPES)


@pytest.mark.parametrize("name", ["a.docx", "a.xls", "a.csv", "photo.jpg", "", "no-dot", "a."])
def test_a_signature_decides_the_type_whatever_the_name_says(name: str) -> None:
    assert sniff_media_type(b"%PDF-1.7", name) == "application/pdf"
    assert sniff_media_type(b"\x89PNG\r\n\x1a\n", name) == "image/png"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.", "application/zip"),
        ("a", "application/zip"),
        ("docx", "application/zip"),
        ("a.docx.", "application/zip"),
        (".docx", DOCX),
        ("a.tar.docx", DOCX),
    ],
)
def test_only_what_follows_the_last_dot_is_the_extension(name: str, expected: str) -> None:
    assert sniff_media_type(b"PK\x03\x04", name) == expected


@pytest.mark.parametrize("brand", [b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"])
def test_every_brand_of_the_heif_family_is_a_heic_picture(brand: bytes) -> None:
    assert sniff_media_type(b"\x00\x00\x00\x18ftyp" + brand + PADDING) == "image/heic"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(b"%PDF", id="pdf-without-its-dash"),
        pytest.param(b"GIF", id="gif-one-byte-short"),
        pytest.param(b"{\\rt", id="rtf-short"),
        pytest.param(b"\x89PNG\r\n\x1a", id="png-one-byte-short"),
        pytest.param(b"\xff\xd8", id="jpeg-one-byte-short"),
        pytest.param(b"PK\x03", id="zip-one-byte-short"),
        pytest.param(OLE[:-1], id="ole-one-byte-short"),
        pytest.param(b"II*", id="tiff-one-byte-short"),
    ],
)
def test_a_signature_cut_short_names_nothing_but_what_the_rest_shows(data: bytes) -> None:
    assert sniff_media_type(data) in {"text/plain", OCTET_STREAM}


def test_a_name_may_hold_anything_without_changing_what_the_bytes_show() -> None:
    assert sniff_media_type(b"Hola", "a.\x00.\n.pdf") == "text/plain"
    assert sniff_media_type(b"\xff\xd8\xff", "x" * 5000) == "image/jpeg"


def test_a_bmp_needs_its_whole_header_and_its_reserved_bytes_empty() -> None:
    assert sniff_media_type(BMP[:25]) == OCTET_STREAM
    assert sniff_media_type(BMP[:26]) == "image/bmp"
    assert sniff_media_type(BMP) == "image/bmp"
    assert sniff_media_type(BMP[:6] + b"\x01" + BMP[7:]) == OCTET_STREAM
    assert sniff_media_type(BMP[:9] + b"\x01" + BMP[10:]) == OCTET_STREAM
    assert sniff_media_type(BMP[:10] + b"\x01" + BMP[11:]) == "image/bmp"


def test_a_riff_file_is_a_picture_only_when_it_says_webp() -> None:
    assert sniff_media_type(b"RIFF\x24\x00\x00\x00WAVEfmt " + PADDING) == OCTET_STREAM


def test_only_the_first_bytes_decide_whether_a_file_is_text() -> None:
    cut_inside_a_letter = b"a" + "ñ".encode() * 3000
    bad_early = b"abc\xff\xfedef"
    nul_early = b"abc\x00def"
    nul_in_the_last_byte = b"a" * 4095 + b"\x00"
    nul_just_after = b"a" * 4096 + b"\x00"
    bad_just_after = b"a" * 4096 + b"\xff"

    assert sniff_media_type(cut_inside_a_letter) == "text/plain"
    assert sniff_media_type(bad_early) == OCTET_STREAM
    assert sniff_media_type(nul_early) == OCTET_STREAM
    assert sniff_media_type(nul_in_the_last_byte) == OCTET_STREAM
    assert sniff_media_type(nul_just_after) == "text/plain"
    assert sniff_media_type(bad_just_after) == "text/plain"


@given(st.binary(max_size=8192), st.text(max_size=40))
def test_every_file_gets_one_of_the_types_the_module_names(data: bytes, name: str) -> None:
    assert sniff_media_type(data, name) in MEDIA_TYPES


@given(st.binary(max_size=64), st.text(max_size=20))
def test_what_follows_a_signature_never_changes_the_type(tail: bytes, name: str) -> None:
    assert sniff_media_type(b"%PDF-" + tail, name) == "application/pdf"
    assert sniff_media_type(b"\xff\xd8\xff" + tail, name) == "image/jpeg"
    assert sniff_media_type(b"GIF8" + tail, name) == "image/gif"

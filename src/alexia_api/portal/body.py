"""Turning the HTML of a message into safe HTML, plain text, and a list of links.

The school writes a message in a rich text editor and the portal serves the markup as it was
typed, so none of it is trusted. One library, `nh3`, writes every byte of the HTML that leaves
this module, from an allowlist of tags and attributes. A slip in the rules here can lose
formatting but cannot let markup through. The plain text and the links are read back from that
clean HTML and never from the original. Two parsers can disagree about the original, and a
`<noscript>` at the top of a message is enough to make one of them show words the other hides.
Reading the clean HTML means the text always says what the HTML shows.

Both parsers take time in proportion to the square of the nesting depth. A message nested a hundred
thousand levels deep fits in one megabyte and would hold the server for seconds. A message nested
past `MAX_NESTING` is not parsed at all. Its words are pulled out with a scan that takes time in
proportion to its length.
"""

import base64
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from html import escape, unescape
from typing import Final
from urllib.parse import urlsplit

import nh3
from selectolax.lexbor import LexborHTMLParser, LexborNode

from alexia_api.domain.messages import Body, Link, LinkKind

MAX_NESTING: Final = 200
"""The deepest nesting that is parsed. Word processors and newsletter tools stay far below it."""

LINK_REL: Final = "noopener noreferrer"

_SPACE_CHARS: Final = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_SPACES: Final = re.compile(f"[{_SPACE_CHARS}]+")

_DROPPED: Final = frozenset(
    {
        "script", "style", "iframe", "frame", "frameset", "object", "embed", "applet",
        "noscript", "template", "head", "title", "meta", "link", "base", "svg", "math",
        "canvas", "audio", "video", "source", "track", "input", "select", "textarea",
        "button", "option",
    }
)  # fmt: skip
_KEPT: Final = frozenset(
    {
        "a", "p", "br", "hr", "ul", "ol", "li", "strong", "em", "b", "i", "u", "h1", "h2", "h3",
        "h4", "h5", "h6", "blockquote", "pre", "code", "div", "table", "thead", "tbody", "tfoot",
        "tr", "th", "td", "img",
    }
)  # fmt: skip
_ATTRIBUTES: Final = {
    "*": set(),  # Without this entry nh3 still lets `lang` and `title` through on every tag.
    "a": {"href"},
    "ol": {"start"},
    "img": {"src", "alt"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
_LINK_SCHEMES: Final = frozenset({"http", "https", "mailto", "tel"})
_NH3_SCHEMES: Final = {*_LINK_SCHEMES, "data"}
"""`data` is allowed here only so that `_checked_attribute` sees picture sources. It refuses `data`
everywhere except on a picture it has checked."""

_SPAN: Final = re.compile(r"[0-9]{1,2}", re.ASCII)
_LIST_START: Final = re.compile(r"[0-9]{1,4}", re.ASCII)
_PICTURE: Final = re.compile(
    r"data:image/(?:png|jpe?g|gif|webp);base64,([A-Za-z0-9+/\s]+={0,2})", re.ASCII | re.IGNORECASE
)
_WHITESPACE: Final = re.compile(r"\s+")


def _picture_type(head: bytes) -> str | None:
    """Name a picture by its first bytes. What the address claims does not count."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


def _inline_picture(value: str) -> str | None:
    found = _PICTURE.fullmatch(value.strip())
    if found is None:
        return None
    payload = _WHITESPACE.sub("", found.group(1))
    if len(payload) % 4:
        return None
    # Padding can only sit at the end and the length is a multiple of four, so this always decodes.
    kind = _picture_type(base64.b64decode(payload[:16]))
    return f"data:{kind};base64,{payload}" if kind else None


def _safe_address(value: str) -> str | None:
    address = value.strip()
    try:
        parts = urlsplit(address)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in _LINK_SCHEMES:
        return None
    if scheme in {"http", "https"} and not parts.hostname:
        return None
    return address


def _checked_attribute(_tag: str, attribute: str, value: str) -> str | None:
    if attribute == "href":
        return _safe_address(value)
    if attribute == "src":
        return _inline_picture(value)
    if attribute in {"colspan", "rowspan"}:
        return value if _SPAN.fullmatch(value) else None
    if attribute == "start":
        return value if _LIST_START.fullmatch(value) else None
    return value


_NH3_TAGS: Final = set(_KEPT)
_NH3_DROPPED: Final = set(_DROPPED)


def safe_html(raw: str) -> str:
    """The message as HTML that is safe to show. Only the allowlisted tags and attributes stay."""
    cleaned = nh3.clean(
        raw,
        tags=_NH3_TAGS,
        clean_content_tags=_NH3_DROPPED,
        attributes=_ATTRIBUTES,
        attribute_filter=_checked_attribute,
        url_schemes=_NH3_SCHEMES,
        link_rel=LINK_REL,
    )
    return cleaned.strip(_SPACE_CHARS)


_TAG: Final = re.compile(r"<!--.*?(?:-->|\Z)|<(/?)([A-Za-z][A-Za-z0-9:-]*)[^<>]*>", re.DOTALL)
_VOID: Final = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
     "wbr"}
)  # fmt: skip
_END_IMPLIED: Final = frozenset(
    {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot", "colgroup", "option",
     "optgroup"}
)  # fmt: skip


def too_nested(raw: str, limit: int = MAX_NESTING) -> bool:
    """Whether the markup opens more than `limit` elements at once, judged without parsing it.

    HTML lets a writer leave out the end tag of a paragraph or a list item, and old messages do,
    so those tags are not counted. Comments are skipped whole, because word processors fill them
    with tags. An end tag closes the nearest open tag of its name and a stray end tag closes
    nothing, as a browser would read them. The scan stops as soon as the limit is passed, so the
    open tags it keeps never outgrow the limit.
    """
    open_tags: list[str] = []
    for found in _TAG.finditer(raw):
        name = (found.group(2) or "").lower()
        if not name or name in _VOID or name in _END_IMPLIED:
            continue
        if found.group(1):
            for position in range(len(open_tags) - 1, -1, -1):
                if open_tags[position] == name:
                    del open_tags[position:]
                    break
        else:
            open_tags.append(name)
            if len(open_tags) > limit:
                return True
    return False


_SOFT: Final = "\ufdd0"
_HARD: Final = "\ufdd1"
_INDENT: Final = "\ufdd2"
# Editors put a newline between block tags, and that white space must not add a line.
_BREAKS: Final = re.compile(f"[{_SOFT}{_HARD}\n](?:[{_SOFT}{_HARD}]|[{_SPACE_CHARS}])*")
_MARKERS: Final = re.compile(f"[{_SOFT}{_HARD}{_INDENT}]")
_DOUBLE_BREAK: Final = frozenset(
    {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table"}
)
_SINGLE_BREAK: Final = frozenset({"div", "li", "tr", "hr"})
_LISTS: Final = frozenset({"ul", "ol"})
_TEXT_NODE: Final = "-text"


@dataclass(slots=True)
class _Frame:
    """An element whose children are being read. `parts` holds what each child turned into."""

    node: LexborNode
    tag: str
    next_child: LexborNode | None
    parts: list[tuple[str, str]] = field(default_factory=list)


type _Render = Callable[[_Frame, str, Sequence[_Frame]], str]


def _squash(text: str) -> str:
    return _SPACES.sub(" ", text).strip(_SPACE_CHARS)


def _image_text(frame: _Frame, _inner: str, _ancestors: Sequence[_Frame]) -> str:
    alt = _squash(frame.node.attributes.get("alt") or "")
    return f"[image: {alt}]" if alt else "[image]"


def _link_text(frame: _Frame, inner: str, _ancestors: Sequence[_Frame]) -> str:
    target = frame.node.attributes.get("href")
    shows_target = (
        target is not None
        and target.lower().startswith("http")
        and inner.strip(_SPACE_CHARS) != ""
        and target not in inner
    )
    return f"{inner} ({target})" if shows_target else inner


def _list_block(_frame: _Frame, inner: str, ancestors: Sequence[_Frame]) -> str:
    """A list sits between blank lines, unless it is inside another list's item."""
    edge = _SOFT if any(frame.tag in _LISTS for frame in ancestors) else _HARD
    return f"{edge}{inner}{edge}"


def _first_number(numbered: _Frame) -> int:
    return int(numbered.node.attributes.get("start") or 1)


def _list_item(_frame: _Frame, inner: str, ancestors: Sequence[_Frame]) -> str:
    """A bullet, or a number in a numbered list, indented two spaces for each list around it."""
    marker = "- "
    if ancestors and ancestors[-1].tag == "ol":
        earlier = sum(1 for tag, _ in ancestors[-1].parts if tag == "li")
        marker = f"{_first_number(ancestors[-1]) + earlier}. "
    around = sum(1 for frame in ancestors if frame.tag in _LISTS)
    return f"{_SOFT}{_INDENT * max(around - 1, 0)}{marker}{inner.strip(_SPACE_CHARS)}{_SOFT}"


def _table_row(frame: _Frame, _inner: str, _ancestors: Sequence[_Frame]) -> str:
    """One line per row, so a paragraph break inside a cell becomes a space."""
    cells = [_squash(_MARKERS.sub(" ", text)) for tag, text in frame.parts if tag in {"td", "th"}]
    return f"{_SOFT}{' | '.join(cells)}{_SOFT}"


def _line_break(_frame: _Frame, _inner: str, _ancestors: Sequence[_Frame]) -> str:
    return "\n"


_SPECIAL: Final[dict[str, _Render]] = {
    "br": _line_break,
    "img": _image_text,
    "a": _link_text,
    "ul": _list_block,
    "ol": _list_block,
    "li": _list_item,
    "tr": _table_row,
}


def _finish(frame: _Frame, ancestors: Sequence[_Frame]) -> str:
    inner = "".join(text for _, text in frame.parts)
    special = _SPECIAL.get(frame.tag)
    if special is not None:
        return special(frame, inner, ancestors)
    if frame.tag in _DOUBLE_BREAK:
        return f"{_HARD}{inner}{_HARD}"
    if frame.tag in _SINGLE_BREAK:
        return f"{_SOFT}{inner}{_SOFT}"
    return inner


def _flatten(body: LexborNode) -> str:
    """Read the tree from its leaves up without recursion, so no input can exhaust the stack."""
    stack = [_Frame(body, "body", body.child)]
    while True:
        top = stack[-1]
        child = top.next_child
        if child is not None:
            top.next_child = child.next
            tag = child.tag or "-"  # The stubs allow no name. Read such a node as an unknown tag.
            if tag == _TEXT_NODE:
                words = _MARKERS.sub("", child.text_content or "")
                top.parts.append((tag, _SPACES.sub(" ", words)))
            else:
                stack.append(_Frame(child, tag, child.child))
            continue
        stack.pop()
        finished = _finish(top, stack)
        if not stack:
            return finished
        stack[-1].parts.append((top.tag, finished))


def _collapse_breaks(run: re.Match[str]) -> str:
    text = run.group()
    wanted = 2 if _HARD in text else 1 if _SOFT in text else 0
    return "\n" * min(2, max(text.count("\n"), wanted))


def _layout(body: LexborNode) -> str:
    """The text of a document, laid out the way a reader would see the paragraphs."""
    spaced = _BREAKS.sub(_collapse_breaks, _flatten(body))
    lines = "\n".join(line.strip(_SPACE_CHARS) for line in spaced.split("\n"))
    return lines.strip(_SPACE_CHARS).replace(_INDENT, "  ")


_URL_IN_TEXT: Final = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_EMAIL_IN_TEXT: Final = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.ASCII)
_TRAILING_PUNCTUATION: Final = re.compile(r"[.,;:!?)\]]+$")
_DOCUMENT_FILE: Final = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|odt|ods|odp)$", re.IGNORECASE)
_VIDEO_CALL_HOSTS: Final = frozenset(
    {"meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com", "whereby.com",
     "webex.com"}
)  # fmt: skip
_FORM_HOSTS: Final = frozenset(
    {"forms.gle", "forms.office.com", "typeform.com", "surveymonkey.com", "jotform.com"}
)
_VIDEO_HOSTS: Final = frozenset({"youtube.com", "youtu.be", "vimeo.com"})
_DOCUMENT_HOSTS: Final = frozenset(
    {"drive.google.com", "docs.google.com", "dropbox.com", "onedrive.live.com", "1drv.ms",
     "sharepoint.com", "canva.com"}
)  # fmt: skip


def _on(host: str, domains: frozenset[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _kind_of(host: str, path: str) -> LinkKind:
    if _on(host, _VIDEO_CALL_HOSTS):
        return "video_call"
    if _on(host, _FORM_HOSTS) or (host == "docs.google.com" and path.startswith("/forms")):
        return "form"
    if _on(host, _VIDEO_HOSTS):
        return "video"
    if _on(host, _DOCUMENT_HOSTS) or _DOCUMENT_FILE.search(path):
        return "document"
    return "other"


def _link_of(address: str) -> Link | None:
    try:
        parts = urlsplit(address)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme == "mailto":
        pieces = parts.path.split("@")
        return Link(url=address, host=pieces[1].lower() if len(pieces) > 1 else "", kind="email")
    if scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.removeprefix("www.")
    return Link(url=address, host=host, kind=_kind_of(host, parts.path))


def _links(hrefs: Iterable[str | None], text: str) -> tuple[Link, ...]:
    """The addresses in anchors first, then the ones written in the words, each once."""
    seen: set[str] = set()
    found: list[Link] = []

    def add(address: str | None) -> None:
        if not address or address in seen:
            return
        link = _link_of(address)
        if link is not None:
            seen.add(address)
            found.append(link)

    for href in hrefs:
        add(href)
    for written in _URL_IN_TEXT.finditer(text):
        add(_TRAILING_PUNCTUATION.sub("", written.group()))
    for mailbox in _EMAIL_IN_TEXT.finditer(text):
        add(f"mailto:{mailbox.group().lower()}")
    return tuple(found)


def _read(html: str) -> tuple[str, tuple[Link, ...]]:
    """The plain text and the links of HTML that `safe_html` wrote, found with one parse."""
    tree = LexborHTMLParser(html)
    (body,) = tree.css("body")
    text = _layout(body)
    return text, _links([anchor.attributes.get("href") for anchor in tree.css("a")], text)


_MARKUP: Final = re.compile(r"<[^<>]*>")


def _words(raw: str) -> str:
    """Every word in the markup, without parsing it. Used for what is too deep to parse."""
    return _squash(_MARKERS.sub("", unescape(_MARKUP.sub(" ", raw))))


@dataclass(frozen=True, slots=True)
class Rendered:
    body: Body
    links: tuple[Link, ...]


def render_body(raw: str) -> Rendered:
    """Everything the API says about the text of one message."""
    if too_nested(raw):
        words = _words(raw)
        body = Body(html=f"<p>{escape(words)}</p>" if words else "", text=words, simplified=True)
        return Rendered(body, _links((), words))
    html = safe_html(raw)
    text, links = _read(html)
    return Rendered(Body(html=html, text=text, simplified=False), links)

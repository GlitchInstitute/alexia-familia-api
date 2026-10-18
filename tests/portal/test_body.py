"""Turning the HTML of a message into safe HTML, plain text, and links."""

import base64

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from selectolax.lexbor import LexborHTMLParser

from alexia_api.domain.messages import Link, LinkKind
from alexia_api.portal.body import LINK_REL, MAX_NESTING, render_body, safe_html, too_nested

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
JPEG = b"\xff\xd8\xff\xe0" + b"pixels"
GIF = b"GIF89a" + b"pixels"
OLD_GIF = b"GIF87a" + b"pixels"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "
WAVE = b"RIFF\x00\x00\x00\x00WAVEfmt "

SAFE_TAGS = frozenset(
    {
        *("a", "p", "br", "hr", "ul", "ol", "li", "strong", "em", "b", "i", "u"),
        *("h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code", "div"),
        *("table", "thead", "tbody", "tfoot", "tr", "th", "td", "img"),
    }
)
SAFE_ATTRIBUTES = {
    "a": {"href", "rel"},
    "ol": {"start"},
    "img": {"src", "alt"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
SAFE_SCHEMES = ("http://", "https://", "mailto:", "tel:")
SAFE_PICTURES = (
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/gif;base64,",
    "data:image/webp;base64,",
)


def data_url(media: str, payload: bytes) -> str:
    return f"data:{media};base64,{base64.b64encode(payload).decode()}"


def plain_text(raw: str) -> str:
    return render_body(raw).body.text


def find_links(raw: str) -> tuple[Link, ...]:
    return render_body(raw).links


def assert_only_safe_markup(html: str) -> None:
    """Read the answer with a different parser than the one that wrote it and check every node."""
    tree = LexborHTMLParser(html)
    for node in tree.css("*"):
        if node.tag in {"html", "head", "body"}:
            continue
        assert node.tag in SAFE_TAGS, node.tag
        for name, value in node.attributes.items():
            assert name in SAFE_ATTRIBUTES.get(node.tag, set()), (node.tag, name)
            if name == "href":
                assert (value or "").lower().startswith(SAFE_SCHEMES), value
            if name == "src":
                assert (value or "").startswith(SAFE_PICTURES), value[:40] if value else value
            if name == "start":
                assert (value or "").isascii()
                assert (value or "").isdigit()
                assert len(value or "") <= 4
    assert not tree.css("head *")


DIRTY = (
    '<p onclick="alert(1)" style="color:red">Hello <strong>bold</strong> <em>it</em><br>line</p>'
    '<script>alert(2)</script><iframe src="https://evil.example.test"></iframe>'
    "<ul><li>one</li></ul><ol><li>two</li></ol>"
    '<a href="javascript:alert(3)">bad</a> <a href="https://example.test/ok" onclick="x()">good</a>'
)


def test_removes_scripts_frames_handlers_and_unsafe_links_and_keeps_the_structure() -> None:
    assert safe_html(DIRTY) == (
        "<p>Hello <strong>bold</strong> <em>it</em><br>line</p>"
        "<ul><li>one</li></ul><ol><li>two</li></ol>"
        f'<a rel="{LINK_REL}">bad</a> <a href="https://example.test/ok" rel="{LINK_REL}">good</a>'
    )


@pytest.mark.parametrize(
    "href",
    [
        "https://example.test/ok",
        "http://example.test",
        "HTTPS://EXAMPLE.TEST/A",
        "mailto:office@example.test",
        "tel:+34123456789",
        "  https://example.test/ok  ",
    ],
)
def test_a_link_keeps_a_web_mail_or_phone_address(href: str) -> None:
    assert f'href="{href.strip()}"' in safe_html(f'<a href="{href}">x</a>')


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        " jav&#x09;ascript:alert(1)",
        "jav&#x0A;ascript:alert(1)",
        "&#106;avascript:alert(1)",
        "vbscript:msgbox(1)",
        "data:text/html;base64,AAAA",
        "data:image/png;base64,AAAA",
        "/relative/path",
        "//example.test/x",
        "ftp://example.test/file",
        "file:///etc/passwd",
        "https://",
        "http:///x",
        "",
    ],
)
def test_a_link_to_anything_else_loses_its_address_and_keeps_its_words(href: str) -> None:
    assert safe_html(f'<a href="{href}">words</a>') == f'<a rel="{LINK_REL}">words</a>'


def test_an_address_that_one_url_parser_accepts_and_the_other_rejects_is_dropped() -> None:
    """Ammonia reads the bracket as a user name. Python's `urlsplit` calls it a broken address."""
    html = safe_html('<a href="http://[@example.test/">words</a>')

    assert html == f'<a rel="{LINK_REL}">words</a>'


def test_escapes_what_it_writes_into_an_attribute() -> None:
    assert safe_html('<a href="https://example.test/?a=1&amp;b=&quot;2&quot;">q</a>') == (
        f'<a href="https://example.test/?a=1&amp;b=&quot;2&quot;" rel="{LINK_REL}">q</a>'
    )


def test_unwraps_the_wrappers_word_processors_add_and_keeps_their_text() -> None:
    dirty = (
        '<p class="MsoNormal"><span style="font-size:12pt">Text <o:p></o:p></span></p>'
        '<font color="red">red</font>'
    )

    assert safe_html(dirty) == "<p>Text </p>red"


def test_keeps_table_structure_and_only_the_span_attributes() -> None:
    dirty = (
        '<table border="1" style="x"><tr><td colspan="2" onclick="x()" width="9">A</td>'
        '<th rowspan="x">B</th></tr></table>'
    )

    assert safe_html(dirty) == (
        '<table><tbody><tr><td colspan="2">A</td><th>B</th></tr></tbody></table>'
    )


def test_an_attribute_that_is_not_on_the_list_is_dropped_from_every_tag() -> None:
    dirty = (
        '<p id="i" class="c" lang="es" title="t" dir="rtl" style="x" hidden data-a="1">words</p>'
        '<img alt="a" width="9" height="9" title="t" loading="lazy">'
        '<table width="9" border="1"><tr><td colspan="2" align="left">x</td></tr></table>'
    )

    assert safe_html(dirty) == (
        '<p>words</p><img alt="a"><table><tbody><tr><td colspan="2">x</td></tr></tbody></table>'
    )


@pytest.mark.parametrize("value", ["1", "12", "2 ", "123", "-1", "1.5", "x", ""])
def test_a_span_is_one_or_two_digits(value: str) -> None:
    html = safe_html(f'<table><tr><td colspan="{value}">A</td></tr></table>')

    assert (f'colspan="{value}"' in html) == (value in {"1", "12"})


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        *[(number, True) for number in ("1", "5", "0", "9999")],
        *[(number, False) for number in ("10000", "-1", "1.5", "x", "", "5 ", "\u0665")],
    ],
)
def test_a_list_keeps_its_first_number_only_when_it_is_a_small_whole_number(
    value: str, kept: bool
) -> None:
    html = safe_html(f'<ol start="{value}" type="a" class="x"><li>a</li></ol>')

    assert html == (f'<ol start="{value}"><li>a</li></ol>' if kept else "<ol><li>a</li></ol>")


def test_keeps_text_that_looks_like_markup_as_text() -> None:
    html = "<p>&lt;b&gt;not bold&lt;/b&gt; &amp; more</p>"

    assert safe_html(html) == html


def test_drops_form_controls_comments_and_style_blocks() -> None:
    dirty = (
        '<form action="x"><input value="a"><select><option>o</option></select>Ask '
        "<button>go</button></form><!-- note --><style>p{}</style>"
    )

    assert safe_html(dirty) == "Ask"


def test_trims_the_ends_of_the_html_but_not_a_space_that_is_content() -> None:
    assert safe_html("  \n<p>x</p>\t\n ") == "<p>x</p>"
    assert safe_html("<p>x</p>\u00a0") == "<p>x</p>&nbsp;"


@pytest.mark.parametrize(
    ("claimed", "payload", "kind"),
    [
        ("png", PNG, "image/png"),
        ("jpeg", JPEG, "image/jpeg"),
        ("jpg", JPEG, "image/jpeg"),
        ("gif", GIF, "image/gif"),
        ("gif", OLD_GIF, "image/gif"),
        ("webp", WEBP, "image/webp"),
        ("png", JPEG, "image/jpeg"),
        ("gif", PNG, "image/png"),
    ],
)
def test_a_picture_that_is_really_one_stays_and_is_named_by_its_bytes(
    claimed: str, payload: bytes, kind: str
) -> None:
    html = safe_html(f'<p><img src="{data_url(f"image/{claimed}", payload)}" alt="logo"></p>')

    assert html == f'<p><img src="{data_url(kind, payload)}" alt="logo"></p>'


@pytest.mark.parametrize(
    "source",
    [
        data_url("image/svg+xml", b'<svg onload="x()"/>'),
        data_url("image/png", b"not really a png"),
        data_url("image/png", b""),
        data_url("image/webp", WAVE),
        data_url("image/jpeg", b"\xff\xd8\x00\x00pixels"),
        data_url("text/html", PNG),
        data_url("image/bmp", b"BM" + b"x" * 20),
        "data:image/png;base64,@@@",
        "data:image/png;base64,iVBORw0KGgpwaXhlbHM",
        "data:image/png,iVBORw0KGgpwaXhlbHM=",
        "https://tracker.example.test/pixel.gif",
        "//tracker.example.test/pixel.gif",
        "javascript:alert(1)",
        "",
    ],
)
def test_any_other_picture_source_is_dropped_and_its_alt_text_stays(source: str) -> None:
    assert safe_html(f'<img src="{source}" alt="pixel">') == '<img alt="pixel">'


def test_a_picture_may_be_written_in_capitals_and_wrapped_over_lines() -> None:
    payload = base64.b64encode(PNG).decode()
    wrapped = payload[:8] + "\n  " + payload[8:]

    html = safe_html(f'<img src="DATA:IMAGE/PNG;BASE64,{wrapped}">')

    assert html == f'<img src="data:image/png;base64,{payload}">'


def test_a_picture_address_may_have_white_space_around_it() -> None:
    payload = base64.b64encode(PNG).decode()

    html = safe_html(f'<img src="\n  data:image/png;base64,{payload}  \n">')

    assert html == f'<img src="data:image/png;base64,{payload}">'


def test_a_picture_address_is_not_a_link_address() -> None:
    html = safe_html(f'<a href="{data_url("image/png", PNG)}">x</a>')

    assert html == f'<a rel="{LINK_REL}">x</a>'


def test_a_picture_keeps_no_handler() -> None:
    html = safe_html(f'<img src="{data_url("image/png", PNG)}" onerror="alert(1)" srcset="x">')

    assert html == f'<img src="{data_url("image/png", PNG)}">'


ATTACKS = [
    "<img src=x onerror=alert(1)>",
    "<svg/onload=alert(1)>",
    "<body onload=alert(1)>",
    "<a href=javascript:alert(1)>x</a>",
    "<a href='java\nscript:alert(1)'>x</a>",
    '<iframe srcdoc="<script>alert(1)</script>"></iframe>',
    (
        '<math><mtext><table><mglyph><style><!--</style><img title="--&gt;&lt;img src=1 '
        'onerror=alert(1)&gt;">'
    ),
    '<noscript><p title="</noscript><img src=x onerror=alert(1)>">',
    "<form action=javascript:alert(1)><input type=submit formaction=javascript:alert(1)>",
    '<object data="javascript:alert(1)"></object>',
    '<embed src="javascript:alert(1)">',
    "<link rel=stylesheet href=//evil.example.test/x.css>",
    '<meta http-equiv="refresh" content="0;url=javascript:alert(1)">',
    '<base href="javascript:alert(1)//">',
    "<video><source onerror=alert(1)></video>",
    "<details open ontoggle=alert(1)>",
    "<div style=\"background:url('javascript:alert(1)')\">x</div>",
    "<xmp><img src=x onerror=alert(1)></xmp>",
    "<plaintext><img src=x onerror=alert(1)>",
    "<textarea><img src=x onerror=alert(1)></textarea>",
    "<title><img src=x onerror=alert(1)></title>",
    "<style><img src=x onerror=alert(1)></style>",
    "<select><option><img src=x onerror=alert(1)></option></select>",
    '<img srcset="javascript:alert(1) 1x">',
    '<a href="https://example.test" target="_blank" onmouseover="alert(1)">x</a>',
    '<table><tr><td background="javascript:alert(1)">x</td></tr></table>',
    "<<script>alert(1)//<</script>",
    "<scr<script>ipt>alert(1)</scr</script>ipt>",
    '<input autofocus onfocus=alert(1)><button formaction="javascript:alert(1)">',
    "<!--[if IE]><script>alert(1)</script><![endif]-->",
    "<![CDATA[<script>alert(1)</script>]]>",
    "<?php echo 1; ?><script>alert(1)</script>",
]


@pytest.mark.parametrize("attack", ATTACKS)
def test_a_known_attack_comes_out_as_nothing_but_allowed_markup(attack: str) -> None:
    assert_only_safe_markup(safe_html(attack))
    assert_only_safe_markup(render_body(attack).body.html)


FRAGMENTS = [
    '<a href="javascript:alert(1)">',
    '<a href="https://example.test/">',
    '<a href="mailto:a@example.test">',
    "</a>",
    "<img src=x onerror=alert(1)>",
    f'<img src="{data_url("image/png", PNG)}" alt="x">',
    '<img src="data:text/html;base64,AAAA">',
    "<script>alert(1)</script>",
    "<script>",
    "</script>",
    "<style>",
    "</style>",
    "<iframe>",
    "<svg>",
    "</svg>",
    "<math>",
    "<noscript>",
    "<template>",
    "<xmp>",
    "<plaintext>",
    "<table>",
    "<tr>",
    "<td colspan=2>",
    "<td colspan=x>",
    "</table>",
    "<p>",
    "</p>",
    "<div>",
    "</div>",
    "<b>",
    "<i>",
    "<ul><li>",
    "<form>",
    "<input autofocus onfocus=alert(1)>",
    "<select><option>",
    "<textarea>",
    "<title>",
    "<body onload=alert(1)>",
    "<html>",
    "<head>",
    "<base href=javascript:1>",
    "<o:p>",
    "<!--",
    "-->",
    "<![CDATA[",
    "]]>",
    "&lt;",
    "&amp;",
    "&#0;",
    "&#x3c;script&#x3e;",
    "<",
    ">",
    '"',
    "'",
    "\x00",
    "\ufdd0",
    "\ufdd1",
    "\ufdd2",
    "<ol start=3><li>",
    "<ul><li>",
    "<p title=x lang=es class=c id=i>",
    "<img alt=a width=1 height=1 title=t>",
    "<a href=https://example.test/x title=t target=_blank>",
    "<td align=left width=1>",
    "text ",
    "https://example.test/x ",
    "a@example.test ",
]
MARKUP = st.lists(st.sampled_from(FRAGMENTS) | st.text(max_size=12), max_size=40).map("".join)


@settings(max_examples=300, deadline=None)
@given(MARKUP)
def test_whatever_the_markup_the_html_that_comes_out_is_only_allowed_markup(markup: str) -> None:
    assert_only_safe_markup(safe_html(markup))


def words_of(html: str) -> str:
    (body,) = LexborHTMLParser(html).css("body")
    return " ".join(body.text().split())


@settings(max_examples=300, deadline=None)
@given(MARKUP)
@example('<a href="javascript:alert(1)"><table><a href="javascript:alert(1)">')
@example('<a href="https://example.test/1">one<table><a href="https://example.test/2">two</a>')
def test_a_second_parse_of_the_clean_html_keeps_every_word(markup: str) -> None:
    """The string may change, because HTML cannot always be written back as it was parsed.

    A link inside a table is moved out of the table by the parser, and then it sits inside the
    outer link, which a second parse splits in two. The words never change.
    """
    once = safe_html(markup)

    assert words_of(safe_html(once)) == words_of(once)


@settings(max_examples=300, deadline=None)
@given(MARKUP)
@example("<noscript>-->")
@example("<noscript>hidden</noscript>shown")
@example("<p><noscript>hidden</p>shown")
def test_the_text_says_only_what_the_html_shows(markup: str) -> None:
    rendered = render_body(markup)

    assert render_body(rendered.body.html).body.text == rendered.body.text


@settings(max_examples=300, deadline=None)
@given(MARKUP)
def test_whatever_the_markup_it_can_be_rendered_and_its_text_holds_no_layout_marker(
    markup: str,
) -> None:
    rendered = render_body(markup)

    for marker in ("\ufdd0", "\ufdd1", "\ufdd2"):
        assert marker not in rendered.body.text
    assert rendered.body.text == rendered.body.text.strip(" \t\r\n\v\f\u00a0\ufeff")


@pytest.mark.parametrize(
    ("markup", "html", "text"),
    [
        ("<noscript>-->", "", ""),
        ("<noscript>hidden</noscript>shown", "shown", "shown"),
        ("<p><noscript>hidden</p>shown", "<p></p>", ""),
        ("<noscript><p>hidden</p></noscript>shown", "shown", "shown"),
    ],
)
def test_words_a_browser_hides_in_a_noscript_are_not_in_the_text(
    markup: str, html: str, text: str
) -> None:
    """A parser run without scripting shows a leading noscript. A browser with scripts hides it.

    Whoever reads the text, a person or a language model, must not see what the page hides.
    """
    rendered = render_body(markup)

    assert (rendered.body.html, rendered.body.text) == (html, text)


def test_lays_out_paragraphs_line_breaks_lists_and_tables_as_text() -> None:
    html = (
        "<h2>Title</h2><p>First   line<br>second line</p><ul><li>one</li><li>two</li></ul>"
        "<table><tr><td>Mon</td><td>Lentils</td></tr><tr><th>Tue</th><td>Fish</td></tr></table>"
    )

    assert plain_text(html) == (
        "Title\n\nFirst line\nsecond line\n\n- one\n- two\n\nMon | Lentils\nTue | Fish"
    )


def test_a_paragraph_inside_a_table_cell_does_not_split_the_row() -> None:
    html = "<table><tr><td><p>Mon</p><p>day</p></td><td>Fish<br>soup</td></tr></table>"

    assert plain_text(html) == "Mon day | Fish soup"


def test_a_list_inside_a_list_is_indented_and_has_no_blank_lines_around_it() -> None:
    html = "<ul><li>one<ul><li>inner</li></ul></li><li>two</li></ul><p>a</p><hr><p>b</p>"

    assert plain_text(html) == "- one\n  - inner\n- two\n\na\n\nb"


def test_a_numbered_list_counts_from_one_or_from_its_start() -> None:
    assert plain_text("<ol><li>a</li><li>b</li><li>c</li></ol>") == "1. a\n2. b\n3. c"
    assert plain_text("<ol start=5><li>a</li><li>b</li></ol>") == "5. a\n6. b"
    assert plain_text("<ol start=0><li>a</li></ol>") == "0. a"


@pytest.mark.parametrize("start", ["x", "-1", "1.5", "12345", ""])
def test_a_start_that_is_not_a_small_whole_number_counts_from_one(start: str) -> None:
    assert plain_text(f'<ol start="{start}"><li>a</li><li>b</li></ol>') == "1. a\n2. b"


def test_white_space_between_items_does_not_move_the_numbers() -> None:
    assert plain_text("<ol>\n  <li>a</li>\n  <li>b</li>\n</ol>") == "1. a\n2. b"


def test_a_newline_between_block_tags_adds_no_line() -> None:
    assert plain_text("<p>a</p>\r\n<p>b</p>\n\n  <p>c</p>") == "a\n\nb\n\nc"
    assert plain_text("<div>a</div>\n<div>b</div>") == "a\nb"
    assert plain_text("<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<p>c</p>") == "- a\n- b\n\nc"
    pretty_table = "<table>\n<tr>\n<td>a</td>\n<td>b</td>\n</tr>\n<tr><td>c</td></tr>\n</table>"
    assert plain_text(pretty_table) == "a | b\nc"


def test_white_space_inside_a_sentence_still_separates_the_words() -> None:
    assert plain_text("<p>one</p> two <p>three</p>") == "one\n\ntwo\n\nthree"
    assert plain_text("one <b>two</b> <i>three</i>") == "one two three"


def test_a_line_break_keeps_its_line_even_with_white_space_around_it() -> None:
    assert plain_text("a <br> b") == "a\nb"
    assert plain_text("a<br> <br>b") == "a\n\nb"


def test_lists_of_both_kinds_nest_with_two_spaces_for_each_level() -> None:
    html = "<ol><li>one<ul><li>sub<ol><li>deep</li></ol></li></ul></li><li>two</li></ol>"

    assert plain_text(html) == "1. one\n  - sub\n    1. deep\n2. two"


def test_an_item_outside_any_list_gets_a_bullet() -> None:
    assert plain_text("<li>alone</li>") == "- alone"


def test_a_list_keeps_its_blank_lines_from_the_paragraphs_around_it() -> None:
    assert plain_text("<p>before</p><ul><li>x</li></ul><p>after</p>") == "before\n\n- x\n\nafter"


def test_a_list_is_set_apart_from_the_words_around_it() -> None:
    assert plain_text("intro<ul><li>x</li></ul>outro") == "intro\n\n- x\n\noutro"
    assert plain_text("intro<ol><li>x</li></ol>outro") == "intro\n\n1. x\n\noutro"


def test_an_item_loses_the_white_space_around_its_words() -> None:
    assert plain_text("<ul>\n<li>\n  a\n</li>\n<li> b </li>\n</ul>") == "- a\n- b"
    assert plain_text("<ol><li>\u00a0a\u00a0</li></ol>") == "1. a"


def test_many_line_breaks_in_a_row_leave_one_blank_line() -> None:
    assert plain_text("a<br><br><br><br>b") == "a\n\nb"
    assert plain_text("<p>a</p><br><br><br><p>b</p>") == "a\n\nb"


def test_a_list_inside_a_table_cell_stays_on_the_row() -> None:
    html = "<table><tr><td><ul><li>a</li><li>b</li></ul></td><td>c</td></tr></table>"

    assert plain_text(html) == "- a - b | c"


def test_shows_where_a_link_goes_unless_the_words_already_say_so() -> None:
    assert plain_text('<p>See <a href="https://example.test/a">the page</a>.</p>') == (
        "See the page (https://example.test/a)."
    )
    assert plain_text('<a href="https://example.test/a">https://example.test/a</a>') == (
        "https://example.test/a"
    )
    assert (
        plain_text('<a href="HTTPS://EXAMPLE.TEST/A">page</a>') == "page (HTTPS://EXAMPLE.TEST/A)"
    )
    assert plain_text('<a href="mailto:a@example.test">write</a>') == "write"
    assert plain_text('<a href="https://example.test/a"> </a>') == ""
    assert plain_text('<a href="javascript:alert(1)">words</a>') == "words"


def test_decodes_entities_drops_scripts_and_names_pictures_by_their_alt_text() -> None:
    html = '<p>Caf&eacute;&nbsp;&amp;&nbsp;t&eacute;</p><script>x()</script><img alt="plan"><img>'

    assert plain_text(html) == "Café & té\n\n[image: plan][image]"


def test_an_empty_message_has_no_text() -> None:
    assert plain_text("") == ""
    assert plain_text("<p> </p><div></div>") == ""


def test_a_message_that_is_only_a_frameset_renders_as_nothing() -> None:
    rendered = render_body("<frameset><frame src=x></frameset>")

    assert plain_text("<frameset></frameset>") == ""
    assert (rendered.body.html, rendered.body.text, rendered.links) == ("", "", ())


def test_folds_every_kind_of_space_a_browser_folds() -> None:
    assert plain_text("<p>a\u00a0\u2003\ufeff\tb</p>") == "a b"


def test_the_characters_that_stand_for_breaks_in_the_text_do_not_make_breaks() -> None:
    assert plain_text("<p>a\ufdd0b\ufdd1c</p>") == "abc"


def test_the_text_of_a_message_without_a_body_element_is_still_found() -> None:
    assert plain_text("just words, no tags") == "just words, no tags"
    assert plain_text("<title>t</title><p>after</p>") == "after"


def test_collects_anchors_and_written_addresses_once_each_and_sorts_them_into_kinds() -> None:
    html = (
        '<p><a href="https://meet.google.com/abc-defg-hij">Join</a> or open https://forms.gle/xyz, '
        '<a href="https://docs.google.com/forms/d/1/viewform">form</a> '
        '<a href="https://docs.google.com/document/d/1/edit">doc</a> '
        '<a href="https://www.youtube.com/watch?v=1">video</a> '
        '<a href="https://school.example.test/files/menu.pdf">menu</a> '
        '<a href="https://school.example.test/news">news</a> '
        '<a href="https://forms.gle/xyz">again</a> '
        '<a href="javascript:alert(1)">no</a> <a href="tel:+34123456789">call</a> '
        "write to Office@Example.test.</p>"
    )

    assert [(link.url, link.host, link.kind) for link in find_links(html)] == [
        ("https://meet.google.com/abc-defg-hij", "meet.google.com", "video_call"),
        ("https://docs.google.com/forms/d/1/viewform", "docs.google.com", "form"),
        ("https://docs.google.com/document/d/1/edit", "docs.google.com", "document"),
        ("https://www.youtube.com/watch?v=1", "youtube.com", "video"),
        ("https://school.example.test/files/menu.pdf", "school.example.test", "document"),
        ("https://school.example.test/news", "school.example.test", "other"),
        ("https://forms.gle/xyz", "forms.gle", "form"),
        ("mailto:office@example.test", "example.test", "email"),
    ]


@pytest.mark.parametrize(
    ("address", "host", "kind"),
    [
        ("https://zoom.us/j/1", "zoom.us", "video_call"),
        ("https://us02web.zoom.us/j/1", "us02web.zoom.us", "video_call"),
        ("https://teams.microsoft.com/l/meetup-join/1", "teams.microsoft.com", "video_call"),
        ("https://notzoom.us/j/1", "notzoom.us", "other"),
        ("https://forms.office.com/r/1", "forms.office.com", "form"),
        ("https://school.typeform.com/to/1", "school.typeform.com", "form"),
        ("https://docs.google.com/spreadsheets/d/1", "docs.google.com", "document"),
        ("https://drive.google.com/file/d/1", "drive.google.com", "document"),
        ("https://youtu.be/1", "youtu.be", "video"),
        ("https://vimeo.com/1", "vimeo.com", "video"),
        ("https://example.test/a/plan.DOCX", "example.test", "document"),
        ("https://example.test/a/plan.pdf?download=1", "example.test", "document"),
        ("https://example.test/a/plan.pdf.html", "example.test", "other"),
        ("https://example.test:8080/news", "example.test", "other"),
        ("https://www.example.test/news", "example.test", "other"),
        ("HTTPS://WWW.EXAMPLE.TEST/news", "example.test", "other"),
    ],
)
def test_names_the_host_and_the_kind_of_an_address(address: str, host: str, kind: LinkKind) -> None:
    assert find_links(f'<a href="{address}">x</a>') == (Link(url=address, host=host, kind=kind),)


def test_a_mail_address_names_its_domain_and_may_carry_a_subject() -> None:
    links = find_links('<a href="mailto:Office@School.example.test?subject=Hi">write</a>')

    assert links == (
        Link(
            url="mailto:Office@School.example.test?subject=Hi",
            host="school.example.test",
            kind="email",
        ),
    )


def test_trims_punctuation_that_belongs_to_the_sentence_from_a_written_address() -> None:
    html = "<p>Visit https://example.test/a. Or (https://example.test/b)!</p>"

    assert [link.url for link in find_links(html)] == [
        "https://example.test/a",
        "https://example.test/b",
    ]


def test_reads_a_written_address_as_the_reader_sees_it() -> None:
    html = "<p>See https://example.test/a?x=1&amp;y=2 today</p>"

    assert [link.url for link in find_links(html)] == ["https://example.test/a?x=1&y=2"]


def test_finds_nothing_in_a_message_without_addresses() -> None:
    assert find_links("<p>Nothing to click.</p>") == ()
    assert find_links("") == ()


@pytest.mark.parametrize(
    "html",
    [
        '<a href="https://">x</a>',
        '<a href="http://[::1">x</a>',
        '<a href="/relative">x</a>',
        '<a href="tel:+34123456789">x</a>',
        "<p>https:// and http://</p>",
        "<p>see http://[oops now</p>",
        "<p>see https:///path and http://?q=1</p>",
    ],
)
def test_an_address_without_a_host_or_of_another_kind_is_not_a_link(html: str) -> None:
    assert find_links(html) == ()


def test_nesting_is_judged_by_the_elements_open_at_once() -> None:
    assert not too_nested("<div>" * MAX_NESTING + "x" + "</div>" * MAX_NESTING)
    assert too_nested("<div>" * (MAX_NESTING + 1))
    assert not too_nested("<div><div></div></div>" * 5000)


def test_a_writer_who_leaves_out_end_tags_is_not_nested() -> None:
    sloppy = "<ul>" + "<li>item" * 5000 + "</ul>" + "<p>para" * 5000
    sloppy += "<table>" + "<tr><td>cell<td>cell" * 3000 + "</table>"

    assert not too_nested(sloppy)
    assert not render_body(sloppy).body.simplified


def test_void_elements_do_not_count_as_open() -> None:
    assert not too_nested("<br>" * 5000 + "<img src=x>" * 5000 + "<hr>" * 5000)


def test_what_a_comment_holds_does_not_count_as_open() -> None:
    word_processor = "<!--[if gte mso 9]>" + "<xml><w:Word>" * 500 + "<![endif]-->"

    assert not too_nested("<!-- <div> -->" * 5000)
    assert not too_nested(word_processor + "<p>text</p>")
    assert not too_nested("<!--" + "<div>" * 1000)
    assert too_nested("<!-- x -->" + "<div>" * (MAX_NESTING + 1))
    assert too_nested("<div>" * MAX_NESTING + "<!-- x --><div>" + "<b>")


def test_an_end_tag_closes_the_nearest_open_element_of_its_name() -> None:
    assert not too_nested("<div><span>x</span></div>" * 5000)
    assert not too_nested("<div>" * 150 + "<b>" * 40 + "</div>" + "<i>" * 40)
    assert too_nested("<div>" * 150 + "</div>" + "<b>" * 100)


def test_stray_end_tags_do_not_hide_the_depth() -> None:
    assert too_nested("<div>" * (MAX_NESTING + 1) + "</span>" * 1000)
    assert too_nested("<div>" * (MAX_NESTING + 1) + "</p></li></td>" * 1000)


def test_names_and_end_tags_are_read_in_any_case() -> None:
    assert too_nested("<DIV>" * (MAX_NESTING + 1))
    assert not too_nested("<DIV>" * 150 + "</div>" * 150 + "<Div>" * 150)


def test_a_message_nested_past_the_limit_is_cut_down_to_its_words_without_parsing_it() -> None:
    depth = 100_000
    raw = "<div>" * depth + "5 &lt; 6 &amp; <b>deep</b> https://example.test/z" + "</div>" * depth

    rendered = render_body(raw)

    assert rendered.body.simplified
    assert rendered.body.text == "5 < 6 & deep https://example.test/z"
    assert rendered.body.html == "<p>5 &lt; 6 &amp; deep https://example.test/z</p>"
    assert rendered.links == (
        Link(url="https://example.test/z", host="example.test", kind="other"),
    )


def test_a_message_nested_past_the_limit_cannot_carry_markup_through_its_words() -> None:
    raw = "<div>" * 1000 + "<img src=x onerror=alert(1)>&lt;script&gt;alert(1)&lt;/script&gt;"

    html = render_body(raw).body.html

    assert_only_safe_markup(html)
    assert "<script" not in html


def test_a_message_nested_past_the_limit_folds_white_space_and_loses_marker_characters() -> None:
    rendered = render_body("<div>" * 1000 + "a\ufdd0b\ufdd1c\ufdd2d\ufeff e\n\n f")

    assert rendered.body.simplified
    assert rendered.body.text == "abcd e f"
    assert rendered.body.html == "<p>abcd e f</p>"


def test_a_message_nested_past_the_limit_with_no_words_has_no_html() -> None:
    rendered = render_body("<div>" * 1000)

    assert (rendered.body.html, rendered.body.text, rendered.links) == ("", "", ())


def test_a_message_that_is_not_too_deep_is_not_marked_simplified() -> None:
    rendered = render_body("<p>Hola <a href='https://example.test/a'>enlace</a></p>")

    assert not rendered.body.simplified
    assert rendered.body.text == "Hola enlace (https://example.test/a)"
    assert rendered.body.html == (
        f'<p>Hola <a href="https://example.test/a" rel="{LINK_REL}">enlace</a></p>'
    )
    assert rendered.links == (
        Link(url="https://example.test/a", host="example.test", kind="other"),
    )


def test_a_million_tags_in_a_row_are_judged_without_slowing_down() -> None:
    assert too_nested("<b>" * 1_000_000)
    assert not too_nested("<" * 1_000_000)
    assert not too_nested("<a " * 1_000_000)

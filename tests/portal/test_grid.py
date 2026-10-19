"""Reading the JSON of a grid page, and the HTML inside its cells."""

import json
from datetime import UTC, datetime

import pytest

from alexia_api.domain.errors import PortalError, SchemaDrift, SessionExpired
from alexia_api.domain.ids import StudentId
from alexia_api.portal.grid import (
    GridJson,
    GridRow,
    GridSpec,
    cell_text,
    grid_feed_path,
    grid_page_path,
    is_empty_cell,
    parse_grid_json,
)
from alexia_api.sim.world import synthetic_guid

STUDENT = StudentId(synthetic_guid(0x101))
ONE_CHILD = f"GuidObjeto={STUDENT}&ObjetoTipo=6&master=3&contexto_pagina=1"

ANSWER = {
    "page": 1,
    "total": 3,
    "records": 25,
    "rows": [{"id": "a", "cell": ["x", 1, None, "y"]}],
    "userdata": {},
}


def test_reads_the_shape_of_a_grid_answer_and_ignores_the_rest() -> None:
    grid = parse_grid_json(json.dumps(ANSWER), "grid")

    assert grid == GridJson(
        page=1, total=3, records=25, rows=[GridRow(id="a", cell=["x", 1, None, "y"])]
    )


def test_a_grid_without_rows_is_still_a_grid() -> None:
    grid = parse_grid_json('{"page": 1, "total": 0, "records": 0, "rows": []}', "grid")

    assert grid.rows == []


@pytest.mark.parametrize("text", ["", "not json", "{", "<html><body>Error</body></html>"])
def test_text_that_is_not_json_is_schema_drift_and_keeps_a_sample(text: str) -> None:
    with pytest.raises(PortalError) as raised:
        parse_grid_json(text, "feed page")

    assert raised.value.detail == SchemaDrift(where="feed page is not JSON", sample=text)


@pytest.mark.parametrize(
    "text",
    [
        '<html><input name="txtUsuario" type="text" id="txtUsuario" /></html>',
        '<html><a href="/ACWeb/LogOn.aspx">Entrar</a></html>',
    ],
)
def test_a_logon_page_where_json_should_be_means_the_session_ended(text: str) -> None:
    with pytest.raises(PortalError) as raised:
        parse_grid_json(text, "feed page")

    assert raised.value.detail == SessionExpired()


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        "{}",
        '{"page": 1, "total": 1, "records": 1}',
        '{"page": "1", "total": 1, "records": 1, "rows": []}',
        '{"page": true, "total": 1, "records": 1, "rows": []}',
        '{"page": 1, "total": 1.5, "records": 1, "rows": []}',
        '{"page": 1, "total": 1, "records": 1, "rows": {}}',
        '{"page": 1, "total": 1, "records": 1, "rows": [{"cell": []}]}',
        '{"page": 1, "total": 1, "records": 1, "rows": [{"id": 7, "cell": []}]}',
        '{"page": 1, "total": 1, "records": 1, "rows": [{"id": "a", "cell": "x"}]}',
    ],
)
def test_json_of_the_wrong_shape_is_schema_drift(text: str) -> None:
    with pytest.raises(PortalError) as raised:
        parse_grid_json(text, "feed page")

    assert raised.value.detail == SchemaDrift(where="feed page", sample=text)


@pytest.mark.parametrize(
    "html",
    ["", " ", "\n\t", "&nbsp", "&nbsp;", "&NBSP;", "&nbsp; &nbsp;", "\u00a0"],
)
def test_a_cell_with_only_spaces_is_empty(html: str) -> None:
    assert is_empty_cell(html)
    assert cell_text(html) == ""


@pytest.mark.parametrize("html", ["x", "&nbsp;x", "<br>", "&amp;", "0"])
def test_a_cell_with_anything_else_is_not_empty(html: str) -> None:
    assert not is_empty_cell(html)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("Ana", "Ana"),
        ("  Ana   Muestra \n ", "Ana Muestra"),
        ("<b>Ana</b> <i>Muestra</i>", "Ana Muestra"),
        ("Ana&nbsp;Muestra", "Ana Muestra"),
        ("Ana\u00a0Muestra", "Ana Muestra"),
        ("Tom &amp; Jerry", "Tom & Jerry"),
        ("Menú &eacute;", "Menú é"),
        ('<img src="x" alt="not text">', ""),
        ("<span></span>", ""),
    ],
)
def test_cell_text_is_the_decoded_words_with_single_spaces(html: str, expected: str) -> None:
    assert cell_text(html) == expected


def test_the_page_path_opens_the_grid_for_one_child() -> None:
    spec = GridSpec(name="x", page="/ACWeb/x.aspx", grid_id="g", sort="Fecha", order="desc")

    assert grid_page_path(spec, STUDENT) == f"/ACWeb/x.aspx?{ONE_CHILD}"


def test_the_feed_path_is_the_request_the_script_of_the_page_makes() -> None:
    spec = GridSpec(name="x", page="/ACWeb/x.aspx", grid_id="g", sort="Fecha", order="desc")

    path = grid_feed_path(spec, STUDENT, datetime(2026, 1, 1, tzinfo=UTC))

    assert path == (
        f"/ACWeb/x.aspx?{ONE_CHILD}&jqGridID=g&_search=false&nd=1767225600000&rows=500&page=1"
        "&sidx=Fecha&sord=desc"
    )


def test_a_sort_of_two_columns_is_written_as_the_page_writes_it() -> None:
    spec = GridSpec(
        name="x", page="/ACWeb/x.aspx", grid_id="g", sort="Unbound_Mes asc, Fecha", order="asc"
    )

    path = grid_feed_path(spec, STUDENT, datetime(2026, 1, 1, tzinfo=UTC))

    assert path.endswith("&sidx=Unbound_Mes+asc%2C+Fecha&sord=asc")

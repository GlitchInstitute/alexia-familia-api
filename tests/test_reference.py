"""The catalog describes every setting from the model, so the guides cannot drift from the code."""

import tomllib
from functools import reduce
from pathlib import Path, PureWindowsPath

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, Field

from alexia_api.config import AccountSettings, CacheTtls, Settings, load_settings, unknown_variables
from alexia_api.reference import NAME_PLACEHOLDER, SettingDoc, catalog, format_value

ACCOUNT_PATH = ("accounts", NAME_PLACEHOLDER)
TABLES = {"accounts", "cache"}


def settings_in_the_catalog() -> list[SettingDoc]:
    return [setting for section in catalog() for setting in section.settings]


def test_the_file_has_a_section_for_the_top_level_and_one_for_each_table() -> None:
    assert [section.path for section in catalog()] == [(), ACCOUNT_PATH, ("cache",)]


def test_every_setting_of_the_model_is_in_the_catalog_once() -> None:
    declared = (
        (set(Settings.model_fields) - TABLES)
        | {f"cache.{name}" for name in CacheTtls.model_fields}
        | {f"accounts.{NAME_PLACEHOLDER}.{name}" for name in AccountSettings.model_fields}
    )

    keys = [setting.key for setting in settings_in_the_catalog()]

    assert sorted(keys) == sorted(declared)


def test_every_setting_and_table_is_explained_in_plain_words() -> None:
    explained = [(f"the table {'.'.join(s.path)}", s.description) for s in catalog() if s.path]
    explained += [(f"the setting {s.key}", s.description) for s in settings_in_the_catalog()]

    for label, text in explained:
        assert text, f"{label} has no description"
        assert text == text.strip(), f"{label} has stray space around its description"
        assert text.endswith("."), f"the description of {label} does not end with a full stop"
        assert "\u2014" not in text, f"the description of {label} has a long dash"


@pytest.mark.parametrize(
    ("key", "variable"),
    [
        ("state_dir", "ALEXIA_API_STATE_DIR"),
        ("cache.tracking", "ALEXIA_API_CACHE__TRACKING"),
        ("accounts.<name>.password", "ALEXIA_API_ACCOUNTS__<NAME>__PASSWORD"),
    ],
)
def test_a_setting_names_the_variable_that_sets_it(key: str, variable: str) -> None:
    [setting] = [s for s in settings_in_the_catalog() if s.key == key]

    assert setting.variable == variable


def test_the_loader_accepts_every_variable_the_catalog_names() -> None:
    for setting in settings_in_the_catalog():
        variable = setting.variable.replace("<NAME>", "MARTA")

        assert unknown_variables({variable: "x"}) == [], variable


def as_text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, Path):
        return value.as_posix()
    return str(value)


def test_a_variable_that_holds_the_default_gives_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documented = [s for s in settings_in_the_catalog() if s.path[0] != "accounts"]
    for setting in documented:
        monkeypatch.setenv(setting.variable, as_text(setting.default))

    settings = load_settings(None)

    for setting in documented:
        assert reduce(getattr, setting.path, settings) == setting.default, setting.key


@pytest.mark.parametrize(
    ("key", "kind"),
    [
        ("state_dir", "path"),
        ("allow_writes", "true or false"),
        ("min_spacing_seconds", "number"),
        ("rate_limit_per_minute", "whole number"),
        ("cors_origins", "list of text"),
        ("log_level", "one of debug, info, warning, error"),
        ("accounts.<name>.role_id", "text"),
        ("accounts.<name>.slugs", "table of text"),
    ],
)
def test_a_setting_says_what_kind_of_value_it_takes(key: str, kind: str) -> None:
    [setting] = [s for s in settings_in_the_catalog() if s.key == key]

    assert setting.kind == kind


@pytest.mark.parametrize(
    ("key", "limits"),
    [
        ("min_spacing_seconds", "at least 0.1 and at most 60"),
        ("request_timeout_seconds", "more than 0 and at most 300"),
        ("rate_limit_per_minute", "at least 0"),
        ("cache.children", "at least 0"),
        ("accounts.<name>.label", "at least 1 character and at most 80 characters"),
        ("accounts.<name>.institution_key", "at least 1 character"),
        ("timezone", None),
        ("cors_origins", None),
        ("accounts.<name>.password", None),
    ],
)
def test_a_setting_says_what_values_it_accepts(key: str, limits: str | None) -> None:
    [setting] = [s for s in settings_in_the_catalog() if s.key == key]

    assert setting.limits == limits


def settings_of(model: type[BaseModel], monkeypatch: pytest.MonkeyPatch) -> dict[str, SettingDoc]:
    monkeypatch.setattr("alexia_api.reference.Settings", model)
    return {setting.key: setting for setting in settings_in_the_catalog()}


def test_every_kind_of_limit_reads_as_a_phrase_with_the_lower_one_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Probe(BaseModel):
        closed_below: float = Field(default=1, lt=10, ge=0, description="A.")
        open_below: float = Field(default=1, le=5, gt=0, description="B.")
        only_above: int = Field(default=1, lt=3, description="C.")
        text_length: str = Field(default="xx", max_length=40, min_length=2, description="D.")
        unlimited: int = Field(default=1, description="E.")

    found = settings_of(Probe, monkeypatch)

    assert {key: setting.limits for key, setting in found.items()} == {
        "closed_below": "at least 0 and less than 10",
        "open_below": "more than 0 and at most 5",
        "only_above": "less than 3",
        "text_length": "at least 2 characters and at most 40 characters",
        "unlimited": None,
    }


@pytest.mark.parametrize(
    ("limits", "text"),
    [
        (None, "Seconds to wait."),
        ("at least 0", "Seconds to wait. It must be at least 0."),
        ("more than 0 and at most 300", "Seconds to wait. It must be more than 0 and at most 300."),
    ],
)
def test_the_explanation_adds_the_limits_after_the_description(
    limits: str | None, text: str
) -> None:
    setting = SettingDoc(
        path=("wait",),
        kind="number",
        description="Seconds to wait.",
        required=False,
        limits=limits,
    )

    assert setting.explanation == text


def test_a_type_the_catalog_cannot_name_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class Probe(BaseModel):
        raw: bytes = Field(default=b"", description="Raw bytes.")

    monkeypatch.setattr("alexia_api.reference.Settings", Probe)

    with pytest.raises(TypeError, match="no plain name for the type"):
        catalog()


def test_a_limit_the_catalog_cannot_put_in_words_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Probe(BaseModel):
        steps: int = Field(default=5, multiple_of=5, description="Steps.")

    monkeypatch.setattr("alexia_api.reference.Settings", Probe)

    with pytest.raises(TypeError, match="no words for the constraint"):
        catalog()


def test_a_length_limit_is_described_for_text_only(monkeypatch: pytest.MonkeyPatch) -> None:
    class Probe(BaseModel):
        names: list[str] = Field(default_factory=list, min_length=1, description="Names.")

    monkeypatch.setattr("alexia_api.reference.Settings", Probe)

    with pytest.raises(TypeError, match="no words for a length limit on a setting of kind"):
        catalog()


def test_a_setting_is_required_only_when_it_has_no_default() -> None:
    required = [setting for setting in settings_in_the_catalog() if setting.required]

    assert {setting.key for setting in required} == {
        "accounts.<name>.username",
        "accounts.<name>.password",
    }
    assert [setting.default for setting in required] == [None, None]


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (120, "120"),
        (0.15, "0.15"),
        ("info", '"info"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("a\\b", '"a\\\\b"'),
        ("line\nbreak", '"line\\nbreak"'),
        ("\x00", '"\\u0000"'),
        ("\x1f", '"\\u001F"'),
        (" ~", '" ~"'),
        ("\x7f", '"\\u007F"'),
        ("\u00f1", '"\u00f1"'),
        (Path("state"), '"state"'),
        (PureWindowsPath("state\\keys"), '"state/keys"'),
        ([], "[]"),
        (["a", "b"], '["a", "b"]'),
        ({}, "{}"),
        ({"lucia": "x"}, '{lucia = "x"}'),
        ({"first-born": "x"}, '{first-born = "x"}'),
        ({"two words": "y"}, '{"two words" = "y"}'),
        ({"a.b": "z"}, '{"a.b" = "z"}'),
    ],
)
def test_a_value_is_written_the_way_toml_writes_it(value: object, text: str) -> None:
    assert format_value(value) == text


@pytest.mark.parametrize("value", [None, object(), (1, 2), {1, 2}])
def test_a_value_toml_cannot_hold_is_refused(value: object) -> None:
    with pytest.raises(TypeError, match="no TOML form"):
        format_value(value)


scalars = st.one_of(
    st.booleans(),
    st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(),
)
values = st.recursive(
    scalars,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4),
        st.dictionaries(st.text(min_size=1), inner, max_size=4),
    ),
    max_leaves=10,
)


@given(values)
def test_what_is_written_reads_back_the_same(value: object) -> None:
    assert tomllib.loads(f"x = {format_value(value)}")["x"] == value

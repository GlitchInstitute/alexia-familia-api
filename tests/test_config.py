"""The configuration says which accounts to serve, and it is strict about mistakes."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from alexia_api.config import (
    ConfigError,
    Settings,
    find_config_file,
    load_settings,
    read_secret,
    unknown_variables,
)
from alexia_api.domain.accounts import Capabilities

STUDENT = "5afe0000-0000-4000-8000-000000000101"
OTHER_STUDENT = "5afe0000-0000-4000-8000-000000000102"

ONE_ACCOUNT = """
[accounts.marta]
portal_url = "https://portal.example.test"
institution_key = "demo-school"
username = "marta.ejemplo"
password = "demo-password-a"
"""


def write(directory: Path, text: str, name: str = "alexia-api.toml") -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def explain(path: Path) -> str:
    with pytest.raises(ConfigError) as raised:
        load_settings(path)
    return str(raised.value)


def test_with_nothing_configured_the_server_has_no_accounts_and_only_reads() -> None:
    settings = load_settings(None)

    assert settings.accounts == {}
    assert settings.capabilities == Capabilities(writes=False, forms=False, restore_unread=False)
    assert settings.timezone == "Europe/Madrid"
    assert settings.min_spacing_seconds == 0.15
    assert settings.docs_enabled is True


def test_a_config_file_defines_accounts(tmp_path: Path) -> None:
    settings = load_settings(write(tmp_path, ONE_ACCOUNT))

    account = settings.accounts["marta"]
    assert account.base_url == "https://portal.example.test"
    assert account.key == "demo-school"
    assert account.label is None
    assert account.role_id is None


def test_one_server_can_hold_several_accounts(tmp_path: Path) -> None:
    second = ONE_ACCOUNT.replace("marta", "pablo")

    settings = load_settings(write(tmp_path, ONE_ACCOUNT + second))

    assert sorted(settings.accounts) == ["marta", "pablo"]


def test_a_pasted_login_address_gives_the_portal_and_the_key(tmp_path: Path) -> None:
    text = """
[accounts.marta]
login_url = "https://portal.example.test:8443/ACWeb/LogOn.aspx?key=demo-school"
username = "marta.ejemplo"
password = "demo-password-a"
"""

    account = load_settings(write(tmp_path, text)).accounts["marta"]

    assert account.base_url == "https://portal.example.test:8443"
    assert account.key == "demo-school"


def test_http_is_allowed_only_for_a_portal_on_this_machine(tmp_path: Path) -> None:
    local = ONE_ACCOUNT.replace("https://portal.example.test", "http://127.0.0.1:8765")

    account = load_settings(write(tmp_path, local)).accounts["marta"]

    assert account.base_url == "http://127.0.0.1:8765"


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("http://portal.example.test", "https"),
        ("ftp://portal.example.test", "https"),
        ("https://hunter2:secret@portal.example.test", "user name or password"),
        ("not a url", "https"),
        ("https://portal.example.test:notaport", "valid web address"),
    ],
)
def test_a_wrong_portal_address_is_refused_with_a_reason(
    tmp_path: Path, address: str, expected: str
) -> None:
    broken = ONE_ACCOUNT.replace("https://portal.example.test", address)

    message = explain(write(tmp_path, broken))

    assert expected in message
    assert "accounts.marta" in message
    assert "hunter2" not in message


LOGIN = 'login_url = "https://portal.example.test/ACWeb/LogOn.aspx?key=demo-school"'
PORTAL = 'portal_url = "https://portal.example.test"'
KEY = 'institution_key = "demo-school"'


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        ((LOGIN, PORTAL, KEY), "either"),
        ((LOGIN, KEY), "either"),
        ((LOGIN.replace("?key=demo-school", ""),), "key="),
        ((PORTAL,), "needs institution_key"),
        ((KEY,), "portal_url or login_url"),
        ((), "portal_url or login_url"),
    ],
)
def test_the_portal_is_named_in_exactly_one_way(
    tmp_path: Path, lines: tuple[str, ...], expected: str
) -> None:
    text = "[accounts.marta]\n" + "\n".join(lines) + '\nusername = "u"\npassword = "p"\n'

    assert expected in explain(write(tmp_path, text))


def test_an_account_needs_a_url_friendly_name(tmp_path: Path) -> None:
    broken = ONE_ACCOUNT.replace("[accounts.marta]", '[accounts."Marta Family"]')

    assert "Marta Family" in explain(write(tmp_path, broken))


def test_a_misspelled_setting_is_an_error_and_not_ignored(tmp_path: Path) -> None:
    broken = ONE_ACCOUNT.replace("password =", "pasword =")

    message = explain(write(tmp_path, broken))

    assert "accounts.marta.pasword" in message
    assert "demo-password-a" not in message


def test_a_misspelled_top_level_setting_is_an_error(tmp_path: Path) -> None:
    assert "allow_wrties" in explain(write(tmp_path, "allow_wrties = true\n" + ONE_ACCOUNT))


def test_broken_toml_is_reported_without_a_traceback(tmp_path: Path) -> None:
    message = explain(write(tmp_path, "[accounts.marta\n"))

    assert "alexia-api.toml" in message
    assert "line 1" in message


def test_a_secret_never_appears_in_an_error_or_in_a_repr(tmp_path: Path) -> None:
    secret = "hunter2-secret"
    text = ONE_ACCOUNT.replace("demo-password-a", secret)

    assert secret not in explain(write(tmp_path, "min_spacing_seconds = -1\n" + text))
    assert secret not in repr(load_settings(write(tmp_path, text, "ok.toml")))


def test_environment_variables_override_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "allow_writes = false\n" + ONE_ACCOUNT)
    monkeypatch.setenv("ALEXIA_API_ALLOW_WRITES", "true")
    monkeypatch.setenv("ALEXIA_API_ACCOUNTS__MARTA__INSTITUTION_KEY", "other-school")

    settings = load_settings(path)

    assert settings.allow_writes is True
    assert settings.accounts["marta"].key == "other-school"
    assert settings.accounts["marta"].base_url == "https://portal.example.test"


def test_an_account_can_be_defined_by_environment_variables_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALEXIA_API_ACCOUNTS__PABLO__PORTAL_URL", "https://portal.example.test")
    monkeypatch.setenv("ALEXIA_API_ACCOUNTS__PABLO__INSTITUTION_KEY", "demo-school")
    monkeypatch.setenv("ALEXIA_API_ACCOUNTS__PABLO__USERNAME", "pablo.prueba")
    monkeypatch.setenv("ALEXIA_API_ACCOUNTS__PABLO__PASSWORD", "env:PABLO_PASSWORD")

    settings = load_settings(None)

    assert list(settings.accounts) == ["pablo"]


def test_a_list_setting_accepts_a_comma_separated_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALEXIA_API_CORS_ORIGINS", "https://a.example.test, https://b.example.test")

    assert load_settings(None).cors_origins == ["https://a.example.test", "https://b.example.test"]


def test_the_write_switches_set_the_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEXIA_API_ALLOW_WRITES", "true")
    monkeypatch.setenv("ALEXIA_API_RESTORE_UNREAD", "true")

    assert load_settings(None).capabilities == Capabilities(
        writes=True, forms=False, restore_unread=True
    )


def test_forms_cannot_be_switched_on_without_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALEXIA_API_ALLOW_FORMS", "true")

    with pytest.raises(ConfigError, match="allow_forms needs allow_writes"):
        load_settings(None)


@pytest.mark.parametrize(
    ("line", "needle"),
    [
        ('timezone = "Mars/Olympus"', "timezone"),
        ("min_spacing_seconds = 0.01", "min_spacing_seconds"),
        ("request_timeout_seconds = 0", "request_timeout_seconds"),
        ("rate_limit_per_minute = -5", "rate_limit_per_minute"),
        ('log_level = "loud"', "log_level"),
    ],
)
def test_out_of_range_values_name_the_setting(tmp_path: Path, line: str, needle: str) -> None:
    assert needle in explain(write(tmp_path, line + "\n" + ONE_ACCOUNT))


def test_slugs_can_be_pinned_to_children(tmp_path: Path) -> None:
    text = (
        ONE_ACCOUNT + f'\n[accounts.marta.slugs]\nlucia = "{STUDENT}"\nmateo = "{OTHER_STUDENT}"\n'
    )

    pinned = load_settings(write(tmp_path, text)).accounts["marta"].pinned_slugs()

    assert pinned == {STUDENT: "lucia", OTHER_STUDENT: "mateo"}


@pytest.mark.parametrize(
    "pins",
    [
        'Lucia = "5afe0000-0000-4000-8000-000000000101"',
        'lucia = "not-a-guid"',
        (
            'lucia = "5afe0000-0000-4000-8000-000000000101"\n'
            'mateo = "5afe0000-0000-4000-8000-000000000101"'
        ),
    ],
)
def test_pinned_slugs_must_be_valid_and_name_different_children(tmp_path: Path, pins: str) -> None:
    message = explain(write(tmp_path, ONE_ACCOUNT + f"\n[accounts.marta.slugs]\n{pins}\n"))

    assert "accounts.marta.slugs" in message


def test_the_config_file_is_found_by_variable_and_then_by_name(tmp_path: Path) -> None:
    named = write(tmp_path, ONE_ACCOUNT)
    elsewhere = write(tmp_path, ONE_ACCOUNT, "elsewhere.toml")

    assert find_config_file({"ALEXIA_API_CONFIG": str(elsewhere)}, cwd=tmp_path) == elsewhere
    assert find_config_file({}, cwd=tmp_path) == named
    named.unlink()
    assert find_config_file({}, cwd=tmp_path) is None


def test_a_variable_that_points_nowhere_is_an_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"

    with pytest.raises(ConfigError, match=r"missing\.toml"):
        find_config_file({"ALEXIA_API_CONFIG": str(missing)}, cwd=tmp_path)


def test_an_explicit_file_that_does_not_exist_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_settings(tmp_path / "nope.toml")


def test_a_secret_can_be_written_in_the_file() -> None:
    secret = read_secret(SecretStr("plain"), setting="accounts.marta.password", environ={})

    assert secret.get_secret_value() == "plain"


def test_a_secret_can_name_an_environment_variable() -> None:
    secret = read_secret(
        SecretStr("env:MARTA_PASSWORD"),
        setting="accounts.marta.password",
        environ={"MARTA_PASSWORD": "from-env"},
    )

    assert secret.get_secret_value() == "from-env"


def test_a_secret_can_name_a_file_and_only_the_line_ending_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "password"
    path.write_text("  two words \n", encoding="utf-8")

    secret = read_secret(SecretStr(f"file:{path}"), setting="accounts.marta.password", environ={})

    assert secret.get_secret_value() == "  two words "


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("env:NOT_SET_ANYWHERE", "NOT_SET_ANYWHERE"),
        ("env:", "environment variable"),
        ("file:/no/such/place", "/no/such/place"),
        ("file:", "file"),
        ("", "empty"),
    ],
)
def test_a_secret_that_cannot_be_read_says_where_it_looked(reference: str, expected: str) -> None:
    with pytest.raises(ConfigError) as raised:
        read_secret(SecretStr(reference), setting="accounts.marta.password", environ={})

    assert "accounts.marta.password" in str(raised.value)
    assert expected in str(raised.value)


def test_a_misspelled_variable_is_an_error_that_suggests_the_right_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALEXIA_API_DOCS_ENABLEDD", "do-not-print-this")

    with pytest.raises(ConfigError) as raised:
        load_settings(None)

    message = str(raised.value)
    assert "ALEXIA_API_DOCS_ENABLEDD names no setting" in message
    assert "did you mean ALEXIA_API_DOCS_ENABLED?" in message
    assert "do-not-print-this" not in message


def test_a_misspelled_variable_in_a_nested_name_suggests_the_top_level_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALEXIA_API_ACCOUNT__MARTA__USERNAME", "marta.ejemplo")

    with pytest.raises(ConfigError, match="did you mean ALEXIA_API_ACCOUNTS"):
        load_settings(None)


def test_a_variable_that_resembles_nothing_gets_no_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALEXIA_API_ZZZZ", "1")

    with pytest.raises(ConfigError) as raised:
        load_settings(None)

    assert "ALEXIA_API_ZZZZ names no setting" in str(raised.value)
    assert "did you mean" not in str(raised.value)


def test_every_misspelled_variable_is_reported_together_in_order() -> None:
    environ = {"ALEXIA_API_B_WRONG": "1", "ALEXIA_API_A_WRONG": "1", "ALEXIA_API_PORT_TYPO": "1"}

    assert unknown_variables(environ) == [
        "ALEXIA_API_A_WRONG",
        "ALEXIA_API_B_WRONG",
        "ALEXIA_API_PORT_TYPO",
    ]


@pytest.mark.parametrize("name", sorted(Settings.model_fields))
def test_the_variable_for_every_setting_is_accepted(name: str) -> None:
    assert unknown_variables({f"ALEXIA_API_{name.upper()}": "x"}) == []


@pytest.mark.parametrize(
    "name",
    [
        "ALEXIA_API_CONFIG",
        "ALEXIA_API_ACCOUNTS__MARTA__PASSWORD",
        "ALEXIA_API_CACHE__TRACKING",
        "alexia_api_allow_writes",
    ],
)
def test_nested_lowercase_and_file_variables_are_accepted(name: str) -> None:
    assert unknown_variables({name: "x"}) == []


@pytest.mark.parametrize(
    "name",
    [
        "ALEXIA_API_SERVICE_HOST",
        "ALEXIA_API_SERVICE_PORT",
        "ALEXIA_API_SERVICE_PORT_HTTP",
        "ALEXIA_API_PORT",
        "ALEXIA_API_PORT_8000_TCP",
        "ALEXIA_API_PORT_8000_TCP_ADDR",
        "ALEXIA_API_NAME",
        "ALEXIA_API_ENV_SOMETHING",
    ],
)
def test_variables_that_container_platforms_add_are_not_mistaken_for_typos(name: str) -> None:
    assert unknown_variables({name: "x"}) == []


def test_a_name_that_only_starts_like_a_platform_variable_is_still_a_typo() -> None:
    assert unknown_variables({"ALEXIA_API_PORTAL_URL": "x"}) == ["ALEXIA_API_PORTAL_URL"]


@pytest.mark.parametrize("name", ["ALEXIA_API", "ALEXIA_APIX_FOO", "OTHER_ALEXIA_API_FOO", "PATH"])
def test_variables_without_the_prefix_are_not_looked_at(name: str) -> None:
    assert unknown_variables({name: "x"}) == []


def test_a_misspelled_variable_is_caught_whatever_its_case() -> None:
    assert unknown_variables({"alexia_api_docs_enabledd": "x"}) == ["alexia_api_docs_enabledd"]

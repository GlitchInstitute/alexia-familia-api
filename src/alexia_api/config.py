"""What the operator can configure, where it is read from, and how secrets are read.

Settings come from a TOML file and from `ALEXIA_API_*` environment variables, and a variable wins
over the file. Unknown names are errors in the file and in the environment, so a typo cannot
quietly turn a safety switch back into its default. Error messages name the setting and never
show a value, because a value may be a password.
"""

import difflib
import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal, Self
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    TomlConfigSettingsSource,
)

from alexia_api.domain.accounts import Capabilities
from alexia_api.domain.base import Model
from alexia_api.domain.ids import (
    ChildSlug,
    InvalidIdError,
    StudentId,
    parse_account_id,
    parse_child_slug,
    parse_role_id,
    parse_student_id,
)
from alexia_api.domain.media import MEBIBYTE

ENV_PREFIX: Final = "ALEXIA_API_"
ENV_NESTED_DELIMITER: Final = "__"
CONFIG_ENV: Final = f"{ENV_PREFIX}CONFIG"
DEFAULT_CONFIG_NAME: Final = "alexia-api.toml"
_LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
_PLATFORM_VARIABLES: Final = re.compile(
    r"service_(host|port)(_.+)?|port(_\d+_(tcp|udp)(_.+)?)?|name|env_.+"
)

LogLevel = Literal["debug", "info", "warning", "error"]
LogFormat = Literal["text", "json"]
type AccountSecrets = tuple[SecretStr, SecretStr]


class ConfigError(Exception):
    """The configuration is wrong. The message names the setting and never shows a value."""


def _origin(address: str, setting: str) -> str:
    """Reduce a portal address to scheme, host, and port, after checking it is safe to use."""
    parts = urlsplit(address)
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        raise ValueError(f"{setting} is not a valid web address") from None
    if parts.scheme not in {"http", "https"} or not host:
        raise ValueError(f"{setting} must be a web address that starts with https://")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"{setting} contains a user name or password, remove it")
    if parts.scheme == "http" and host not in _LOCAL_HOSTS:
        raise ValueError(f"{setting} must start with https://, http:// is for this machine only")
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}" + (f":{port}" if port else "")


class AccountSettings(Model):
    """One set of portal credentials. A server holds one or more of these."""

    label: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        description="A name for people, shown in responses. Defaults to the account name.",
    )
    login_url: str | None = Field(
        default=None,
        description=(
            "The address of the portal's login page, pasted as is. The server takes the portal "
            "address and the school key from it. Use this or portal_url with institution_key."
        ),
    )
    portal_url: str | None = Field(
        default=None,
        description="The portal's web address without a path, for example https://portal.example.test.",
    )
    institution_key: str | None = Field(
        default=None,
        min_length=1,
        description="The school key, which is the value after key= in the login page's address.",
    )
    username: SecretStr = Field(
        description=(
            "The guardian's portal user name. Write `env:NAME` to read it from an environment "
            "variable or `file:/path` to read it from a file."
        )
    )
    password: SecretStr = Field(
        description=(
            "The guardian's portal password. Write `env:NAME` to read it from an environment "
            "variable or `file:/path` to read it from a file, so the config file holds no secret."
        )
    )
    role_id: str | None = Field(
        default=None,
        description="Which role to sign in with when the login has several. Usually not needed.",
    )
    slugs: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Pins a child's name in URLs. Each key is a slug and each value is the child's "
            "student id, so URLs stay the same when a sibling is added."
        ),
    )

    @field_validator("role_id")
    @classmethod
    def _role_id_is_a_guid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return parse_role_id(value)
        except InvalidIdError:
            raise ValueError(
                "role_id must be an identifier like the ones the portal uses"
            ) from None

    @field_validator("slugs")
    @classmethod
    def _slugs_name_different_children(cls, value: dict[str, str]) -> dict[str, str]:
        pinned: dict[str, str] = {}
        for slug, student_id in value.items():
            try:
                parse_child_slug(slug)
            except InvalidIdError:
                raise ValueError(
                    f"'{slug}' is not a valid slug, use lower case letters, digits, and hyphens"
                ) from None
            try:
                pinned[slug] = parse_student_id(student_id)
            except InvalidIdError:
                raise ValueError(f"'{slug}' is not pinned to a valid student id") from None
        if len(set(pinned.values())) != len(pinned):
            raise ValueError("two slugs name the same child")
        return pinned

    @model_validator(mode="after")
    def _the_portal_is_named_once(self) -> Self:
        pair = self.portal_url is not None or self.institution_key is not None
        if self.login_url is not None and pair:
            raise ValueError("give either login_url or portal_url with institution_key, not both")
        if self.login_url is not None:
            _origin(self.login_url, "login_url")
            if not parse_qs(urlsplit(self.login_url).query).get("key", [""])[0]:
                raise ValueError("login_url has no key= in it, use portal_url and institution_key")
        elif self.portal_url is None:
            raise ValueError("give portal_url or login_url")
        elif self.institution_key is None:
            raise ValueError("portal_url needs institution_key")
        else:
            _origin(self.portal_url, "portal_url")
        return self

    @property
    def base_url(self) -> str:
        """The portal's address without a path."""
        return _origin(self.login_url or self.portal_url or "", "the portal address")

    @property
    def portal_host(self) -> str:
        """The portal's host name, with the port when the address names one."""
        return urlsplit(self.base_url).netloc

    @property
    def key(self) -> str:
        """The school key the portal's login page needs."""
        if self.login_url is not None:
            return parse_qs(urlsplit(self.login_url).query)["key"][0]
        return self.institution_key or ""

    def pinned_slugs(self) -> dict[StudentId, ChildSlug]:
        """The pins as typed ids, ready to hand to `assign_slugs`."""
        return {
            parse_student_id(student): parse_child_slug(slug)
            for slug, student in self.slugs.items()
        }


class CacheTtls(Model):
    """How long each kind of answer is reused before the portal is asked again, in seconds."""

    children: float = Field(default=900, ge=0, description="Seconds to reuse the list of children.")
    tracking: float = Field(
        default=120, ge=0, description="Seconds to reuse the five tracking counters."
    )
    staff: float = Field(
        default=3600, ge=0, description="Seconds to reuse the staff a guardian can meet."
    )
    folders: float = Field(
        default=300, ge=0, description="Seconds to reuse the list of message folders."
    )
    messages: float = Field(
        default=120, ge=0, description="Seconds to reuse the list of messages in a folder."
    )
    message: float = Field(
        default=900,
        ge=0,
        description="Seconds to reuse one message with its words, after it was read.",
    )


def _split_list(value: object) -> object:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    """Everything the operator can configure."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter=ENV_NESTED_DELIMITER,
        extra="forbid",
        frozen=True,
    )

    accounts: dict[str, AccountSettings] = Field(
        default_factory=dict,
        description="The portal accounts to serve, keyed by a short name used in URLs.",
    )
    state_dir: Path = Field(
        default=Path("state"),
        description=(
            "Where the server keeps its few files, such as the API key hashes and the account "
            "blocks. A relative path starts at the folder of the configuration file."
        ),
    )
    timezone: str = Field(
        default="Europe/Madrid",
        description="The school's time zone name. Times in responses carry this zone's offset.",
    )
    allow_writes: bool = Field(
        default=False,
        description="Lets API keys with the write scope send messages and meeting requests.",
    )
    allow_forms: bool = Field(
        default=False,
        description="Lets the server answer forms. This needs allow_writes as well.",
    )
    restore_unread: bool = Field(
        default=False,
        description=(
            "Puts a message back to unread at the portal after the API opened it. "
            "Reading a message marks it read at the portal otherwise."
        ),
    )
    min_spacing_seconds: float = Field(
        default=0.15,
        ge=0.1,
        le=60,
        description=(
            "The least number of seconds between two requests to the same portal. "
            "A pause keeps the server gentle on the school's portal."
        ),
    )
    request_timeout_seconds: float = Field(
        default=30,
        gt=0,
        le=300,
        description="Seconds to wait for the portal to answer one request.",
    )
    rate_limit_per_minute: int = Field(
        default=120,
        ge=0,
        description="How many requests one API key may make each minute. Zero turns it off.",
    )
    max_attachment_mib: int = Field(
        default=25,
        ge=1,
        le=256,
        description=(
            "The largest file, in mebibytes, that the server fetches from the portal and hands "
            "to a client. A file is held in memory while it travels, so a higher number needs "
            "more memory for each download in progress."
        ),
    )
    docs_enabled: bool = Field(
        default=True,
        description=(
            "Serves /docs, /redoc, and /openapi.json. The /docs page loads its scripts from a "
            "public CDN in your browser. Turn this off when the server is on the internet."
        ),
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Web pages from these origins may call the API in a browser. "
            "In a variable, separate the origins with commas."
        ),
    )
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description=(
            "Answer only requests for these host names. Empty means any. "
            "In a variable, separate the names with commas."
        ),
    )
    log_level: LogLevel = Field(
        default="info", description="How much the server writes to its log."
    )
    log_format: LogFormat = Field(
        default="text", description="Plain lines for people, or one JSON object per line."
    )
    cache: CacheTtls = Field(
        default_factory=CacheTtls,
        description=(
            "How long answers are reused before the portal is asked again. "
            "Zero turns the reuse off."
        ),
    )

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _accept_a_comma_separated_list(cls, value: object) -> object:
        return _split_list(value)

    @field_validator("accounts")
    @classmethod
    def _account_names_are_url_friendly(
        cls, value: dict[str, AccountSettings]
    ) -> dict[str, AccountSettings]:
        for name in value:
            try:
                parse_account_id(name)
            except InvalidIdError:
                raise ValueError(
                    f"'{name}' is not a valid account name, "
                    "use lower case letters, digits, and hyphens"
                ) from None
        return value

    @field_validator("timezone")
    @classmethod
    def _timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError(f"'{value}' is not a known time zone name") from None
        return value

    @model_validator(mode="after")
    def _forms_need_writes(self) -> Self:
        if self.allow_forms and not self.allow_writes:
            raise ValueError("allow_forms needs allow_writes")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del dotenv_settings, file_secret_settings
        return (init_settings, env_settings, TomlConfigSettingsSource(settings_cls))

    @property
    def capabilities(self) -> Capabilities:
        """What the operator switched on, as the API reports it."""
        return Capabilities(
            writes=self.allow_writes, forms=self.allow_forms, restore_unread=self.restore_unread
        )

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def max_attachment_bytes(self) -> int:
        return self.max_attachment_mib * MEBIBYTE


class FixedSettings(Settings):
    """Settings that are exactly the values given, with no file and no variable read.

    The demo uses these, so a person's own `ALEXIA_API_` variables can never put a real account
    into a simulated school. The OpenAPI command uses them so the document does not depend on
    where it is made.
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)


def _explain(error: ValidationError) -> str:
    lines = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        where = ".".join(str(part) for part in item["loc"]) or "settings"
        lines.append(f"{where}: {item['msg'].removeprefix('Value error, ')}")
    return "the configuration has problems\n  " + "\n  ".join(lines)


def unknown_variables(environ: Mapping[str, str]) -> list[str]:
    """The `ALEXIA_API_` variables that name no setting, which is nearly always a typo.

    A typo in a file is an error, so one in a variable has to be too. Otherwise a server could
    run without the restriction its operator thought they had set. Container platforms add
    variables with this prefix when a service has the project's name, and those are skipped.
    """
    settings = set(Settings.model_fields) | {CONFIG_ENV.removeprefix(ENV_PREFIX).lower()}
    unknown = []
    for name in environ:
        if not name.upper().startswith(ENV_PREFIX):
            continue
        setting = name[len(ENV_PREFIX) :].split(ENV_NESTED_DELIMITER, 1)[0].lower()
        if setting not in settings and not _PLATFORM_VARIABLES.fullmatch(setting):
            unknown.append(name)
    return sorted(unknown)


def _suggest(name: str) -> str:
    setting = name[len(ENV_PREFIX) :].split(ENV_NESTED_DELIMITER, 1)[0].lower()
    close = difflib.get_close_matches(setting, sorted(Settings.model_fields), n=1)
    return f", did you mean {ENV_PREFIX}{close[0].upper()}?" if close else ""


def _anchor_state_dir(settings: Settings, config_file: Path | None) -> Settings:
    """Make a relative state directory mean the same thing wherever the server is started.

    A relative path means a place next to the configuration file, so `--config` works from any
    directory and the key commands and the server agree on where the keys are. A path from an
    environment variable stays relative to the working directory, as a person typing it expects.
    """
    try:
        state_dir = settings.state_dir.expanduser()
    except RuntimeError:
        raise ConfigError("state_dir starts with ~ but the home directory is not known") from None
    from_variable = any(name.upper() == f"{ENV_PREFIX}STATE_DIR" for name in os.environ)
    if not state_dir.is_absolute() and config_file is not None and not from_variable:
        state_dir = config_file.resolve().parent / state_dir
    return settings.model_copy(update={"state_dir": state_dir})


def load_settings(config_file: Path | None = None) -> Settings:
    """Read the settings from a TOML file, if given, and from the environment."""
    if config_file is not None and not config_file.is_file():
        raise ConfigError(f"the configuration file {config_file} does not exist")
    unknown = unknown_variables(os.environ)
    if unknown:
        lines = [f"{name} names no setting{_suggest(name)}" for name in unknown]
        raise ConfigError(
            "the environment has variables that are not settings\n  " + "\n  ".join(lines)
        )

    class FromFile(Settings):
        model_config = SettingsConfigDict(toml_file=config_file)

    try:
        return _anchor_state_dir(FromFile(), config_file)
    except ValidationError as error:
        raise ConfigError(_explain(error)) from None
    except tomllib.TOMLDecodeError as error:
        name = config_file.name if config_file is not None else "the configuration"
        raise ConfigError(f"{name} is not valid TOML, {error}") from None
    except SettingsError as error:
        raise ConfigError(str(error)) from None


def find_config_file(environ: Mapping[str, str], *, cwd: Path | None = None) -> Path | None:
    """Find the file to read, from ALEXIA_API_CONFIG first and then from the working directory."""
    named = environ.get(CONFIG_ENV)
    if named:
        path = Path(named).expanduser()
        if not path.is_file():
            raise ConfigError(f"{CONFIG_ENV} points to {path}, which does not exist")
        return path
    candidate = (cwd or Path.cwd()) / DEFAULT_CONFIG_NAME
    return candidate if candidate.is_file() else None


@dataclass(frozen=True, slots=True)
class FromEnvironment:
    """The setting names an environment variable that holds the secret."""

    name: str


@dataclass(frozen=True, slots=True)
class FromFile:
    """The setting names a file that holds the secret."""

    path: str


@dataclass(frozen=True, slots=True)
class WrittenHere:
    """The setting is the secret itself. It carries no text, so it cannot leak one."""


type SecretSource = FromEnvironment | FromFile | WrittenHere


def secret_source(reference: SecretStr) -> SecretSource:
    """Say where a setting keeps its secret, without reading the secret.

    A person writes `env:NAME` or `file:/path` to keep the secret out of the configuration file.
    The prefix is in lower case. Any other text is the secret itself.
    """
    text = reference.get_secret_value()
    if text.startswith("env:"):
        return FromEnvironment(text.removeprefix("env:").strip())
    if text.startswith("file:"):
        return FromFile(text.removeprefix("file:").strip())
    return WrittenHere()


def read_secret(reference: SecretStr, *, setting: str, environ: Mapping[str, str]) -> SecretStr:
    """Turn a setting into the secret it stands for.

    Only the line ending is removed from a file, because a password may start or end with a space.
    """
    match secret_source(reference):
        case FromEnvironment(name=""):
            raise ConfigError(f"{setting} says env: but names no environment variable")
        case FromEnvironment(name=name):
            found = environ.get(name)
            if found is None:
                raise ConfigError(
                    f"{setting} refers to the environment variable {name}, which is not set"
                )
            value = found
        case FromFile(path=""):
            raise ConfigError(f"{setting} says file: but names no file")
        case FromFile(path=path):
            try:
                content = Path(path).read_text(encoding="utf-8")
            except OSError:
                raise ConfigError(
                    f"{setting} refers to the file {path}, which cannot be read"
                ) from None
            value = content.removesuffix("\n").removesuffix("\r")
        case WrittenHere():
            value = reference.get_secret_value()
    if not value:
        raise ConfigError(f"{setting} is empty")
    return SecretStr(value)


def read_account_secrets(
    name: str, account: AccountSettings, environ: Mapping[str, str]
) -> AccountSecrets:
    """The user name and the password of one account.

    One error names every part that cannot be read, so a person fixes both in one go.
    """
    problems = []
    parts = []
    for part, reference in (("username", account.username), ("password", account.password)):
        try:
            parts.append(read_secret(reference, setting=f"accounts.{name}.{part}", environ=environ))
        except ConfigError as error:
            problems.append(str(error))
    if problems:
        raise ConfigError("\n".join(problems))
    return parts[0], parts[1]


def resolve_secrets(settings: Settings, environ: Mapping[str, str]) -> dict[str, AccountSecrets]:
    """Read the secrets of every account before any of them is used.

    A missing variable stops the server before it holds a connection. One error lists every
    secret that cannot be read, so a person fixes them all in one go.
    """
    secrets: dict[str, AccountSecrets] = {}
    problems = []
    for name, account in settings.accounts.items():
        try:
            secrets[name] = read_account_secrets(name, account, environ)
        except ConfigError as error:
            problems.extend(str(error).splitlines())
    if problems:
        raise ConfigError("some secrets cannot be read\n  " + "\n  ".join(problems))
    return secrets

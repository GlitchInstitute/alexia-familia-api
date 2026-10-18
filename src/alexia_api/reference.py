"""The settings, described for people.

The models in `config.py` already say what each setting is, what it defaults to, and what it does.
This module reads them, so the starter file and the configuration guide use the same words as the
code and cannot fall out of step with it. A setting without a description fails the tests, so a
new setting cannot ship unexplained.
"""

import re
import types
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Final, Literal, Union, get_args, get_origin

from pydantic import BaseModel, SecretStr
from pydantic.fields import FieldInfo
from pydantic_settings import NoDecode

from alexia_api.config import ENV_NESTED_DELIMITER, ENV_PREFIX, Settings

NAME_PLACEHOLDER: Final = "<name>"
"""Stands for the name a person gives an account, in a path such as `accounts.<name>.password`."""

_BARE_KEY: Final = re.compile(r"[A-Za-z0-9_-]+")
_SIMPLE_ESCAPES: Final = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}

_PLAIN_KINDS: Final[dict[object, str]] = {
    bool: "true or false",
    int: "whole number",
    float: "number",
    str: "text",
    SecretStr: "text",
    Path: "path",
}

_BOUNDS: Final = (
    ("ge", "at least {}"),
    ("gt", "more than {}"),
    ("min_length", "at least {}"),
    ("le", "at most {}"),
    ("lt", "less than {}"),
    ("max_length", "at most {}"),
)
"""The limits a setting can declare, lower ones first, and how each one reads."""

_LENGTH_BOUNDS: Final = frozenset({"min_length", "max_length"})


@dataclass(frozen=True, slots=True)
class SettingDoc:
    """One setting, as a person reads about it."""

    path: tuple[str, ...]
    kind: str
    description: str
    required: bool
    default: object = None
    limits: str | None = None

    @property
    def explanation(self) -> str:
        """The description, then what the value must be when the setting has limits."""
        if self.limits is None:
            return self.description
        return f"{self.description} It must be {self.limits}."

    @property
    def key(self) -> str:
        """The name in the file, with a dot between a table and its setting."""
        return ".".join(self.path)

    @property
    def variable(self) -> str:
        """The environment variable that sets it."""
        return ENV_PREFIX + ENV_NESTED_DELIMITER.join(part.upper() for part in self.path)


@dataclass(frozen=True, slots=True)
class Section:
    """The settings that live in one table of the file. The top level has an empty path."""

    path: tuple[str, ...]
    description: str
    settings: tuple[SettingDoc, ...]


def catalog() -> tuple[Section, ...]:
    """Every setting, grouped by the table it lives in, in the order the model declares them."""
    sections: list[Section] = []
    _collect(Settings, (), "", sections)
    return tuple(sections)


def format_value(value: object) -> str:
    """Write a value the way a TOML file does."""
    match value:
        case bool():
            return "true" if value else "false"
        case int() | float():
            return repr(value)
        case PurePath():
            return _quote(value.as_posix())
        case str():
            return _quote(value)
        case list():
            return "[" + ", ".join(format_value(item) for item in value) + "]"
        case dict():
            pairs = (f"{_key(str(name))} = {format_value(item)}" for name, item in value.items())
            return "{" + ", ".join(pairs) + "}"
        case _:
            raise TypeError(f"no TOML form for {type(value).__name__}")


def _key(name: str) -> str:
    return name if _BARE_KEY.fullmatch(name) else _quote(name)


def _quote(text: str) -> str:
    """A TOML basic string. It escapes what TOML forbids raw and keeps every other character."""
    return '"' + "".join(_escape(character) for character in text) + '"'


def _escape(character: str) -> str:
    if character in _SIMPLE_ESCAPES:
        return _SIMPLE_ESCAPES[character]
    if ord(character) < 0x20 or ord(character) == 0x7F:
        return f"\\u{ord(character):04X}"
    return character


def _collect(
    model: type[BaseModel], path: tuple[str, ...], description: str, into: list[Section]
) -> None:
    leaves: list[SettingDoc] = []
    tables: list[tuple[type[BaseModel], tuple[str, ...], str]] = []
    for name, field in model.model_fields.items():
        here = (*path, name)
        table = _table_of(field.annotation)
        if table is None:
            leaves.append(_describe(here, field))
        else:
            inner, named = table
            inner_path = (*here, NAME_PLACEHOLDER) if named else here
            tables.append((inner, inner_path, field.description or ""))
    into.append(Section(path, description, tuple(leaves)))
    for inner, inner_path, inner_description in tables:
        _collect(inner, inner_path, inner_description, into)


def _table_of(annotation: object) -> tuple[type[BaseModel], bool] | None:
    """The model behind a setting that is a table, and whether each entry has a name."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation, False
    if get_origin(annotation) is dict:
        _, value = get_args(annotation)
        if isinstance(value, type) and issubclass(value, BaseModel):
            return value, True
    return None


def _describe(path: tuple[str, ...], field: FieldInfo) -> SettingDoc:
    required = field.is_required()
    kind = _kind(field.annotation)
    return SettingDoc(
        path=path,
        kind=kind,
        description=field.description or "",
        required=required,
        default=None if required else field.get_default(call_default_factory=True),
        limits=_limits(field, kind),
    )


def _limits(field: FieldInfo, kind: str) -> str | None:
    """What a setting must be besides its kind, such as `at least 0.1 and at most 60`."""
    found = _bounds(field)
    phrases = [
        template.format(_amount(name, found[name], kind))
        for name, template in _BOUNDS
        if name in found
    ]
    return " and ".join(phrases) or None


def _bounds(field: FieldInfo) -> dict[str, object]:
    found: dict[str, object] = {}
    for item in field.metadata:
        if item is NoDecode:
            continue
        named = {
            name: value for name, _ in _BOUNDS if (value := getattr(item, name, None)) is not None
        }
        if not named:
            raise TypeError(f"no words for the constraint {item!r}")
        found.update(named)
    return found


def _amount(name: str, value: object, kind: str) -> str:
    if name not in _LENGTH_BOUNDS:
        return str(value)
    if kind != "text":
        raise TypeError(f"no words for a length limit on a setting of kind {kind!r}")
    return f"{value} character" if value == 1 else f"{value} characters"


def _kind(annotation: object) -> str:
    origin = get_origin(annotation)
    if origin is Literal:
        return "one of " + ", ".join(str(choice) for choice in get_args(annotation))
    if origin is list:
        (item,) = get_args(annotation)
        return f"list of {_kind(item)}"
    if origin is dict:
        _, value = get_args(annotation)
        return f"table of {_kind(value)}"
    if origin in {Union, types.UnionType}:
        options = [option for option in get_args(annotation) if option is not type(None)]
        return " or ".join(_kind(option) for option in options)
    if annotation in _PLAIN_KINDS:
        return _PLAIN_KINDS[annotation]
    raise TypeError(f"no plain name for the type {annotation!r}")

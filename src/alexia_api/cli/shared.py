"""What more than one command needs, so that each command stays short."""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from alexia_api.config import ConfigError, Settings, find_config_file, load_settings

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        resolve_path=True,
        help=(
            "The configuration file. Without this option the command reads the file that "
            "ALEXIA_API_CONFIG names, or alexia-api.toml in the current folder."
        ),
    ),
]


HostOption = Annotated[
    str,
    typer.Option(
        help="Address to listen on. Use 0.0.0.0 to accept other machines, as in a container."
    ),
]

PortOption = Annotated[int, typer.Option(help="Port to listen on.")]


def make_app(name: str, summary: str) -> typer.Typer:
    """A command group with the choices that every group of this command line shares."""
    return typer.Typer(
        name=name,
        help=summary,
        no_args_is_help=True,
        add_completion=False,
        rich_markup_mode=None,
    )


def fail(message: str) -> NoReturn:
    """Say what went wrong on standard error and stop with status 1."""
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(1)


def load(config: Path | None) -> Settings:
    """The settings, or an error that says what to fix. No secret is read."""
    try:
        return load_settings(config or find_config_file(os.environ))
    except ConfigError as error:
        fail(str(error))


def table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Columns of text, each as wide as its longest cell and separated by two spaces."""
    lines = (header, *rows)
    widths = [max(len(line[column]) for line in lines) for column in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in lines
    )


def words(items: Sequence[str]) -> str:
    """Items in a sentence, as in `a`, `a and b`, and `a, b and c`."""
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"

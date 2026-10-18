"""What more than one command needs, so that each command stays short."""

from pathlib import Path
from typing import Annotated

import typer

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

import asyncio
import os
from dataclasses import replace
from typing import Annotated

import typer
import uvicorn

from alexia_api import __version__
from alexia_api.cli.report import render, verdict
from alexia_api.cli.shared import ConfigOption
from alexia_api.doctor import diagnose, probe_portals

app = typer.Typer(
    name="alexia-api",
    help="Run and manage the alexia-familia-api server.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(show: bool) -> None:
    if show:
        typer.echo(f"alexia-api {__version__}")
        raise typer.Exit


@app.callback()
def main(
    _version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Run and manage the alexia-familia-api server."""


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Address to listen on."),
    port: int = typer.Option(8000, help="Port to listen on."),
    reload: bool = typer.Option(False, help="Reload on code changes. For development."),
) -> None:
    """Start the REST API."""
    uvicorn.run(
        "alexia_api.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@app.command()
def doctor(
    config: ConfigOption = None,
    online: Annotated[
        bool,
        typer.Option(
            "--online",
            help=(
                "Also open the login page of each portal. No password is sent, so this "
                "cannot lock an account."
            ),
        ),
    ] = False,
) -> None:
    """Check the setup and say what to fix.

    Without --online nothing leaves this machine. The exit status is 1 when a line is marked
    fail or stop, so a script can use this command as a check.
    """
    diagnosis = diagnose(config, os.environ)
    if online and diagnosis.settings is not None:
        probes = asyncio.run(probe_portals(diagnosis.settings))
        diagnosis = replace(diagnosis, findings=(*diagnosis.findings, *probes))
    typer.echo(render(diagnosis.findings))
    typer.echo()
    typer.echo(verdict(diagnosis.findings))
    if diagnosis.failed:
        raise typer.Exit(1)

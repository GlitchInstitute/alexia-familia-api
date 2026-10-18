import asyncio
import os
from dataclasses import replace
from typing import Annotated

import typer
import uvicorn

from alexia_api import __version__
from alexia_api.cli.report import render, verdict
from alexia_api.cli.shared import ConfigOption
from alexia_api.config import CONFIG_ENV
from alexia_api.doctor import diagnose, probe_portals
from alexia_api.logs import log_config

app = typer.Typer(
    name="alexia-api",
    help="Run and manage the alexia-familia-api server.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
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
        help="Show the version and exit.",
    ),
) -> None:
    """Run and manage the alexia-familia-api server."""


@app.command()
def serve(
    config: ConfigOption = None,
    host: Annotated[
        str,
        typer.Option(
            help="Address to listen on. Use 0.0.0.0 to accept other machines, as in a container."
        ),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8000,
    reload: Annotated[bool, typer.Option(help="Reload on code changes. For development.")] = False,
) -> None:
    """Check the setup, then start the REST API.

    The checks are the ones `doctor` runs. The server does not start while a line is marked
    stop. A line marked fail or warn is shown and the server starts anyway, so that you can
    make a key from inside a running container.
    """
    diagnosis = diagnose(config, os.environ)
    notices = [finding for finding in diagnosis.findings if finding.level != "ok"]
    if notices:
        typer.echo(render(notices), err=True)
        typer.echo(err=True)
        typer.echo(verdict(diagnosis.findings), err=True)
    settings = diagnosis.startable_settings
    if settings is None:
        raise typer.Exit(1)
    if config is not None:
        os.environ[CONFIG_ENV] = str(config)
    uvicorn.run(
        "alexia_api.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=log_config(settings.log_level, settings.log_format),
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

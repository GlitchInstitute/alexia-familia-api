import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from alexia_api import __version__
from alexia_api.cli.accounts import app as accounts_app
from alexia_api.cli.keys import app as keys_app
from alexia_api.cli.report import render, verdict
from alexia_api.cli.shared import ConfigOption, HostOption, PortOption, fail, make_app
from alexia_api.config import CONFIG_ENV, DEFAULT_CONFIG_NAME
from alexia_api.demo import address, banner, build_demo, demo_state
from alexia_api.doctor import diagnose, probe_portals
from alexia_api.logs import log_config
from alexia_api.scaffold import (
    DEFAULT_ACCOUNT,
    ScaffoldError,
    next_steps,
    render_starter,
    write_starter,
)

app = make_app("alexia-api", "Run and manage the alexia-familia-api server.")
app.add_typer(keys_app)
app.add_typer(accounts_app)


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
def init(
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            envvar=CONFIG_ENV,
            help=(
                "Where to write the file. Without this option the command writes the file that "
                f"{CONFIG_ENV} names, or {DEFAULT_CONFIG_NAME} in the current folder."
            ),
        ),
    ] = None,
    account: Annotated[
        str,
        typer.Option(
            help=(
                "The name of the first account. It goes into URLs, so use lower case letters, "
                "digits, and hyphens."
            )
        ),
    ] = DEFAULT_ACCOUNT,
    login_url: Annotated[
        str | None,
        typer.Option(
            help=(
                "The address of your school's login page. Without it the file holds an example "
                "address that you replace."
            )
        ),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Replace the file if it exists.")] = False,
    print_only: Annotated[
        bool, typer.Option("--print", help="Show the file on screen and write nothing.")
    ] = False,
) -> None:
    """Write a starter configuration file and say what to do next.

    The file lists every setting with its default and a short explanation. It holds no
    password, only the names of the environment variables that do.
    """
    path = (config or Path(DEFAULT_CONFIG_NAME)).expanduser()
    try:
        text = render_starter(account, login_url)
        if print_only:
            typer.echo(text, nl=False)
            return
        write_starter(path, text, replace=force)
    except ScaffoldError as error:
        fail(str(error))
    typer.echo(
        next_steps(
            path, account, has_login_url=login_url is not None, windows=sys.platform == "win32"
        )
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


@app.command()
def serve(
    config: ConfigOption = None,
    host: HostOption = "127.0.0.1",
    port: PortOption = 8000,
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
def demo(host: HostOption = "127.0.0.1", port: PortOption = 8000) -> None:
    """Start the REST API against a simulated school. No account or password is needed.

    The families and children are made up, and nothing the demo changes outlives it. Your
    configuration file and your ALEXIA_API_ variables are not read. The command shows a key and
    some requests to try.
    """
    with demo_state() as state_dir:
        demonstration = build_demo(state_dir)
        base = address(host, port)
        typer.echo(banner(base, demonstration.key, windows=sys.platform == "win32"), err=True)
        typer.echo(err=True)
        uvicorn.run(
            demonstration.app,
            host=host,
            port=port,
            log_config=log_config(
                demonstration.settings.log_level, demonstration.settings.log_format
            ),
        )

import typer
import uvicorn

from alexia_api import __version__

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

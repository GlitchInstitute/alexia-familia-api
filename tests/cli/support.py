"""Run the command line the way a person does, and read what it printed."""

from collections.abc import Mapping

from typer.testing import CliRunner, Result

from alexia_api import cli


def run(*arguments: str, env: Mapping[str, str | None] | None = None) -> Result:
    """Run `alexia-api` with these arguments and this environment on top of the real one.

    A value of None removes a variable for the run and puts it back afterwards, which is how a
    test lets a command change a variable without leaving the change behind.
    """
    return CliRunner().invoke(cli.app, list(arguments), env=env)

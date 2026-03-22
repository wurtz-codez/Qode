"""Qode CLI — entry point using Typer."""

from __future__ import annotations

import typer
from rich.console import Console

from qode.cli.commands.analyze import analyze
from qode.cli.commands.status import status

app = typer.Typer(
    name="qode",
    help="Local-first, multi-agent code archaeology and intelligence system.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)

console = Console()


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
    ),
) -> None:
    """Qode — code archaeology and intelligence, entirely on your machine."""
    if version:
        from qode import __version__

        console.print(f"qode {__version__}")
        raise typer.Exit()


app.command("analyze")(analyze)
app.command("status")(status)


if __name__ == "__main__":
    app()

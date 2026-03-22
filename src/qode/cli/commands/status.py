"""`qode status` command implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from qode.cli.commands.state import read_status
from qode.cli.display.progress import format_status_stats, print_status_panel

console = Console()
REPO_PATH_ARGUMENT = typer.Argument(
    Path("."),
    exists=True,
    file_okay=False,
    dir_okay=True,
    resolve_path=True,
    help="Repository path used for analysis status.",
)


def _stats_from_payload(payload: dict[str, Any]) -> tuple[Any, Any, Any]:
    stats = payload.get("stats")
    if isinstance(stats, dict):
        return (
            stats.get("files_processed"),
            stats.get("total_files"),
            stats.get("nodes_created"),
        )
    return (None, None, None)


def status(
    path: Path = REPO_PATH_ARGUMENT,
) -> None:
    """Show current/last analysis status for a repository."""
    repo_path = path.resolve()
    payload = read_status(repo_path)

    if payload is None:
        console.print(
            "No analysis status found for this repository. "
            "Run `qode analyze <path>` first."
        )
        return

    files_processed, total_files, nodes_created = _stats_from_payload(payload)

    body = (
        f"Repository: {payload.get('repo_path', str(repo_path))}\n"
        f"Run ID: {payload.get('run_id', 'n/a')}\n"
        f"Status: {payload.get('status', 'unknown')}\n"
        f"Phase: {payload.get('phase', 'unknown')}\n"
        f"Progress: {payload.get('percent', 0)}%\n"
        f"Message: {payload.get('message', '')}\n"
        f"Updated: {payload.get('updated_at', 'n/a')}\n"
        f"Started: {payload.get('started_at', 'n/a')}\n"
        f"Finished: {payload.get('finished_at', 'n/a')}\n"
        f"{format_status_stats(files_processed, total_files, nodes_created)}"
    )

    error = payload.get("error")
    if error:
        body = f"{body}\nError: {error}"

    print_status_panel(console, "Analysis Status", body)

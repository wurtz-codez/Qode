"""Rich helpers for CLI progress and status output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from qode.data.schemas import PipelineProgress


def print_progress_update(console: Console, progress: PipelineProgress) -> None:
    """Print a compact progress line."""
    phase = progress.phase.upper()
    line = f"[{phase}] {progress.percent:>3}% - {progress.message}"
    if progress.detail:
        line = f"{line} ({progress.detail})"
    console.print(line)


def print_status_panel(console: Console, title: str, body: str) -> None:
    """Print a small panel used by status command."""
    console.print(Panel.fit(body, title=title))


def format_status_stats(
    files_processed: int | None,
    total_files: int | None,
    nodes_created: int | None,
) -> str:
    """Format status counters for display."""
    files_display = files_processed if files_processed is not None else "n/a"
    total_display = total_files if total_files is not None else "n/a"
    nodes_display = nodes_created if nodes_created is not None else "n/a"
    return (
        f"Files processed: {files_display}\n"
        f"Total files: {total_display}\n"
        f"Nodes created: {nodes_display}"
    )

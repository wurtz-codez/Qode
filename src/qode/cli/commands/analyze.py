"""`qode analyze` command implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from qode.cli.commands.state import write_status
from qode.cli.display.progress import print_progress_update, print_status_panel
from qode.core.pipeline import run_pipeline
from qode.data.schemas import PipelineProgress

console = Console()
REPO_PATH_ARGUMENT = typer.Argument(
    Path("."),
    exists=True,
    file_okay=False,
    dir_okay=True,
    resolve_path=True,
    help="Repository path to analyze.",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload(
    *,
    run_id: str,
    repo_path: Path,
    status: str,
    phase: str,
    percent: int,
    message: str,
    error: str | None = None,
    stats: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "repo_path": str(repo_path),
        "status": status,
        "phase": phase,
        "percent": percent,
        "message": message,
        "updated_at": _utc_now_iso(),
    }
    if started_at is not None:
        payload["started_at"] = started_at
    if finished_at is not None:
        payload["finished_at"] = finished_at
    if error is not None:
        payload["error"] = error
    if stats is not None:
        payload["stats"] = stats
    return payload


def analyze(
    path: Path = REPO_PATH_ARGUMENT,
) -> None:
    """Run the ingestion pipeline for a repository."""
    repo_path = path.resolve()
    run_id = _utc_now_iso()
    started_at = _utc_now_iso()
    last_progress: PipelineProgress | None = None

    write_status(
        repo_path,
        _status_payload(
            run_id=run_id,
            repo_path=repo_path,
            status="running",
            phase="idle",
            percent=0,
            message="Analysis started",
            started_at=started_at,
        ),
    )

    def _on_progress(progress: PipelineProgress) -> None:
        nonlocal last_progress
        last_progress = progress
        print_progress_update(console, progress)

        stats: dict[str, Any] | None = None
        if progress.stats is not None:
            stats = {
                "files_processed": progress.stats.files_processed,
                "total_files": progress.stats.total_files,
                "nodes_created": progress.stats.nodes_created,
            }

        write_status(
            repo_path,
            _status_payload(
                run_id=run_id,
                repo_path=repo_path,
                status="running",
                phase=progress.phase,
                percent=progress.percent,
                message=progress.message,
                stats=stats,
                started_at=started_at,
            ),
        )

    try:
        result = run_pipeline(repo_path, on_progress=_on_progress)
        summary = (
            f"Repository: {repo_path}\n"
            f"Files discovered: {result.total_file_count}\n"
            f"Files parsed: {result.parse_result.file_count}\n"
            f"Entities extracted: {len(result.parse_result.nodes)}"
        )
        print_status_panel(console, "Analysis Completed", summary)

        final_stats = None
        if last_progress is not None and last_progress.stats is not None:
            final_stats = {
                "files_processed": last_progress.stats.files_processed,
                "total_files": last_progress.stats.total_files,
                "nodes_created": last_progress.stats.nodes_created,
            }

        write_status(
            repo_path,
            _status_payload(
                run_id=run_id,
                repo_path=repo_path,
                status="success",
                phase="complete",
                percent=100,
                message="Analysis completed",
                stats=final_stats,
                started_at=started_at,
                finished_at=_utc_now_iso(),
            ),
        )
    except Exception as exc:
        error_message = f"Analysis failed: {exc}"
        console.print(f"[red]{error_message}[/red]")

        failed_stats = None
        if last_progress is not None and last_progress.stats is not None:
            failed_stats = {
                "files_processed": last_progress.stats.files_processed,
                "total_files": last_progress.stats.total_files,
                "nodes_created": last_progress.stats.nodes_created,
            }

        write_status(
            repo_path,
            _status_payload(
                run_id=run_id,
                repo_path=repo_path,
                status="failed",
                phase=last_progress.phase if last_progress is not None else "error",
                percent=last_progress.percent if last_progress is not None else 0,
                message=error_message,
                error=str(exc),
                stats=failed_stats,
                started_at=started_at,
                finished_at=_utc_now_iso(),
            ),
        )
        raise typer.Exit(code=1) from exc

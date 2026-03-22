"""CLI tests for analyze and status commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from qode.cli.main import app
from qode.data.schemas import (
    ParseResult,
    PipelineProgress,
    PipelineResult,
    PipelineStats,
)

runner = CliRunner()


def _status_file(repo_path: Path) -> Path:
    return repo_path / ".qode" / "analysis_status.json"


def test_analyze_success_writes_status(monkeypatch, tmp_path) -> None:
    """Analyze command should complete and persist success status."""

    def _fake_run_pipeline(repo_path, on_progress=None, **kwargs):
        if on_progress is not None:
            on_progress(
                PipelineProgress(
                    phase="scanning",
                    percent=10,
                    message="Scanning repository...",
                    stats=PipelineStats(
                        files_processed=1,
                        total_files=5,
                        nodes_created=0,
                    ),
                )
            )
            on_progress(
                PipelineProgress(
                    phase="complete",
                    percent=100,
                    message="Pipeline complete",
                    stats=PipelineStats(
                        files_processed=5,
                        total_files=5,
                        nodes_created=9,
                    ),
                )
            )
        return PipelineResult(
            parse_result=ParseResult(file_count=3),
            repo_path=str(Path(repo_path)),
            total_file_count=5,
        )

    monkeypatch.setattr("qode.cli.commands.analyze.run_pipeline", _fake_run_pipeline)

    result = runner.invoke(app, ["analyze", str(tmp_path)])

    assert result.exit_code == 0
    assert "Analysis Completed" in result.output

    payload = json.loads(_status_file(tmp_path).read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["phase"] == "complete"
    assert payload["percent"] == 100


def test_analyze_failure_writes_failed_status(monkeypatch, tmp_path) -> None:
    """Analyze command should report failure and persist failed status."""

    def _fake_run_pipeline(repo_path, on_progress=None, **kwargs):
        if on_progress is not None:
            on_progress(
                PipelineProgress(
                    phase="parsing",
                    percent=42,
                    message="Parsing chunk",
                    stats=PipelineStats(
                        files_processed=2,
                        total_files=5,
                        nodes_created=3,
                    ),
                )
            )
        raise RuntimeError("boom")

    monkeypatch.setattr("qode.cli.commands.analyze.run_pipeline", _fake_run_pipeline)

    result = runner.invoke(app, ["analyze", str(tmp_path)])

    assert result.exit_code == 1
    assert "Analysis failed: boom" in result.output

    payload = json.loads(_status_file(tmp_path).read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["phase"] == "parsing"
    assert payload["percent"] == 42
    assert payload["error"] == "boom"


def test_status_no_run_message(tmp_path) -> None:
    """Status command should explain when no run exists."""
    result = runner.invoke(app, ["status", str(tmp_path)])

    assert result.exit_code == 0
    assert "No analysis status found" in result.output


def test_status_with_existing_run(tmp_path) -> None:
    """Status command should display persisted run details."""
    payload = {
        "run_id": "run-123",
        "repo_path": str(tmp_path),
        "status": "success",
        "phase": "complete",
        "percent": 100,
        "message": "Analysis completed",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:01:00+00:00",
        "stats": {
            "files_processed": 10,
            "total_files": 10,
            "nodes_created": 15,
        },
    }
    status_file = _status_file(tmp_path)
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text(json.dumps(payload), encoding="utf-8")

    result = runner.invoke(app, ["status", str(tmp_path)])

    assert result.exit_code == 0
    assert "Analysis Status" in result.output
    assert "run-123" in result.output
    assert "success" in result.output
    assert "100%" in result.output

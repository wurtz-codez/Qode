"""Persistence helpers for CLI analysis status."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def status_file_for_repo(repo_path: Path) -> Path:
    """Return status file path for a repository."""
    return repo_path / ".qode" / "analysis_status.json"


def read_status(repo_path: Path) -> dict[str, Any] | None:
    """Read status payload from disk.

    Returns None if no status file exists or data is invalid.
    """
    file_path = status_file_for_repo(repo_path)
    if not file_path.exists():
        return None

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(raw, dict):
        return raw
    return None


def write_status(repo_path: Path, payload: dict[str, Any]) -> None:
    """Persist status payload to disk."""
    file_path = status_file_for_repo(repo_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True)
    file_path.write_text(data, encoding="utf-8")

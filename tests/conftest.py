"""Shared pytest fixtures for Qode tests.

Provides:
- Temporary KuzuDB database (in-memory/tmp dir)
- Mock LLM client
- Sample parsed entity fixtures
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def tmp_db_path(tmp_path: object) -> object:
    """Return a temporary path for a test KuzuDB database."""
    return tmp_path / "test_kuzu.db"  # type: ignore[operator]


@pytest.fixture()
def mock_llm() -> None:
    """Return a mock LLM client that echoes prompts."""
    # TODO(phase-2): implement mock LLM fixture
    return None

"""Tests for agent logic unit tests."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qode.agents.base import AgentResult, AgentState, AgentStatus
from qode.agents.explorer import ExplorerAgent, ExplorerResult
from qode.data.schemas import ParseResult, PipelineResult


class TestAgentBase:
    """Tests for base agent classes and protocols."""

    def test_agent_status_enum(self) -> None:
        """Test AgentStatus enum values."""
        assert AgentStatus.PENDING == "pending"
        assert AgentStatus.RUNNING == "running"
        assert AgentStatus.COMPLETED == "completed"
        assert AgentStatus.FAILED == "failed"

    def test_agent_result_creation(self) -> None:
        """Test AgentResult dataclass creation."""
        result = AgentResult(
            agent_name="test_agent",
            status=AgentStatus.COMPLETED,
            duration_seconds=1.5,
            metadata={"key": "value"},
        )

        assert result.agent_name == "test_agent"
        assert result.status == AgentStatus.COMPLETED
        assert result.duration_seconds == 1.5
        assert result.error is None
        assert result.metadata == {"key": "value"}

    def test_agent_result_with_error(self) -> None:
        """Test AgentResult with error message."""
        result = AgentResult(
            agent_name="failed_agent",
            status=AgentStatus.FAILED,
            duration_seconds=0.5,
            error="Something went wrong",
        )

        assert result.status == AgentStatus.FAILED
        assert result.error == "Something went wrong"

    def test_agent_state_creation(self) -> None:
        """Test AgentState dataclass creation."""
        state = AgentState(
            project_root="/path/to/project",
            db_path="/path/to/db",
            results={},
            config={"key": "value"},
        )

        assert state.project_root == "/path/to/project"
        assert state.db_path == "/path/to/db"
        assert state.results == {}
        assert state.config == {"key": "value"}

    def test_agent_state_default_fields(self) -> None:
        """Test AgentState with default factory fields."""
        state = AgentState(
            project_root="/path/to/project",
            db_path="/path/to/db",
        )

        assert state.results == {}
        assert state.config == {}


class TestExplorerResult:
    """Tests for ExplorerResult dataclass."""

    def test_explorer_result_creation(self) -> None:
        """Test ExplorerResult dataclass creation."""
        result = ExplorerResult(
            total_files=100,
            total_entities=500,
            db_path="/path/to/db",
            duration_seconds=5.5,
        )

        assert result.total_files == 100
        assert result.total_entities == 500
        assert result.db_path == "/path/to/db"
        assert result.duration_seconds == 5.5


class TestExplorerAgent:
    """Tests for Explorer Agent."""

    def test_explorer_agent_initialization(self) -> None:
        """Test ExplorerAgent initialization."""
        agent = ExplorerAgent()
        assert agent.progress_callback is None

    def test_explorer_agent_with_callback(self) -> None:
        """Test ExplorerAgent initialization with progress callback."""

        def callback(progress: object) -> None:
            pass

        agent = ExplorerAgent(progress_callback=callback)
        assert agent.progress_callback is callback

    @pytest.mark.asyncio()
    async def test_execute_invalid_project_root(self) -> None:
        """Test execute with invalid project root."""
        agent = ExplorerAgent()
        state = AgentState(
            project_root="/nonexistent/path",
            db_path="/tmp/test.db",
        )

        result_state = await agent.execute(state)

        assert "explorer" in result_state.results
        assert result_state.results["explorer"].status == AgentStatus.FAILED
        assert result_state.results["explorer"].error is not None
        assert "Invalid project root" in str(result_state.results["explorer"].error)

    @pytest.mark.asyncio()
    async def test_execute_not_a_directory(self) -> None:
        """Test execute with a file path instead of directory."""
        with tempfile.NamedTemporaryFile() as tmp_file:
            agent = ExplorerAgent()
            state = AgentState(
                project_root=tmp_file.name,
                db_path="/tmp/test.db",
            )

            result_state = await agent.execute(state)

            assert "explorer" in result_state.results
            assert result_state.results["explorer"].status == AgentStatus.FAILED
            assert result_state.results["explorer"].error is not None
            assert "must be a directory" in str(result_state.results["explorer"].error)

    @pytest.mark.asyncio()
    @patch("qode.agents.explorer.run_pipeline")
    @patch("qode.agents.explorer.init_kuzu")
    @patch("qode.agents.explorer.load_graph_to_kuzu")
    async def test_execute_success(
        self,
        mock_load_graph: AsyncMock,
        mock_init_kuzu: AsyncMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test successful execution of Explorer Agent."""
        # Create a temporary project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        (project_dir / "test.py").write_text("print('hello')")

        # Mock parse result with nodes
        parse_result = MagicMock(spec=ParseResult)
        parse_result.nodes = [MagicMock()] * 5  # 5 mock nodes

        # Mock pipeline result
        pipeline_result = MagicMock(spec=PipelineResult)
        pipeline_result.parse_result = parse_result
        pipeline_result.total_file_count = 1
        pipeline_result.repo_path = str(project_dir)

        mock_run_pipeline.return_value = pipeline_result

        # Execute agent
        agent = ExplorerAgent()
        state = AgentState(
            project_root=str(project_dir),
            db_path=str(tmp_path / "test.db"),
        )

        result_state = await agent.execute(state)

        # Verify result
        assert "explorer" in result_state.results
        explorer_result = result_state.results["explorer"]
        assert explorer_result.status == AgentStatus.COMPLETED
        assert explorer_result.duration_seconds > 0
        assert explorer_result.error is None

        # Verify metadata
        metadata = explorer_result.metadata
        assert metadata["total_files"] == 1
        assert metadata["total_entities"] == 5

        # Verify mocks were called
        mock_run_pipeline.assert_called_once()
        mock_init_kuzu.assert_called_once_with(str(tmp_path / "test.db"))
        mock_load_graph.assert_called_once()

    @pytest.mark.asyncio()
    @patch("qode.agents.explorer.run_pipeline")
    async def test_execute_pipeline_exception(
        self,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test execution when pipeline raises an exception."""
        # Create a temporary project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Mock pipeline raising exception
        mock_run_pipeline.side_effect = RuntimeError("Parse error in file.py")

        # Execute agent
        agent = ExplorerAgent()
        state = AgentState(
            project_root=str(project_dir),
            db_path=str(tmp_path / "test.db"),
        )

        result_state = await agent.execute(state)

        # Verify failure
        assert "explorer" in result_state.results
        explorer_result = result_state.results["explorer"]
        assert explorer_result.status == AgentStatus.FAILED
        assert explorer_result.error is not None
        assert "Parse error" in explorer_result.error

    @pytest.mark.asyncio()
    @patch("qode.agents.explorer.run_pipeline")
    @patch("qode.agents.explorer.init_kuzu")
    async def test_execute_kuzu_init_failure(
        self,
        mock_init_kuzu: AsyncMock,
        mock_run_pipeline: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Test execution when KuzuDB initialization fails."""
        # Create a temporary project directory
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        # Mock successful pipeline
        parse_result = MagicMock(spec=ParseResult)
        parse_result.nodes = []

        pipeline_result = MagicMock(spec=PipelineResult)
        pipeline_result.parse_result = parse_result
        pipeline_result.total_file_count = 1
        pipeline_result.repo_path = str(project_dir)

        mock_run_pipeline.return_value = pipeline_result

        # Mock Kuzu init failure
        mock_init_kuzu.side_effect = RuntimeError("Database connection failed")

        # Execute agent
        agent = ExplorerAgent()
        state = AgentState(
            project_root=str(project_dir),
            db_path=str(tmp_path / "test.db"),
        )

        result_state = await agent.execute(state)

        # Verify failure
        assert "explorer" in result_state.results
        explorer_result = result_state.results["explorer"]
        assert explorer_result.status == AgentStatus.FAILED
        assert explorer_result.error is not None
        assert "Database connection failed" in explorer_result.error

    @pytest.mark.asyncio()
    async def test_progress_callback_invocation(self, tmp_path: Path) -> None:
        """Test that progress callback can be set and retrieved."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()

        callback_calls: list[object] = []

        def callback(progress: object) -> None:
            callback_calls.append(progress)

        # Verify callback is stored
        agent = ExplorerAgent(progress_callback=callback)
        assert agent.progress_callback is callback


class TestAgentIntegration:
    """Integration tests for agent system."""

    @pytest.mark.asyncio()
    async def test_agent_state_accumulates_results(self) -> None:
        """Test that AgentState accumulates results from multiple agents."""
        state = AgentState(
            project_root="/test",
            db_path="/test.db",
        )

        # Simulate first agent result
        state.results["explorer"] = AgentResult(
            agent_name="explorer",
            status=AgentStatus.COMPLETED,
            duration_seconds=1.0,
            metadata={"entities": 100},
        )

        # Simulate second agent result
        state.results["analyst"] = AgentResult(
            agent_name="analyst",
            status=AgentStatus.COMPLETED,
            duration_seconds=2.0,
            metadata={"debt_score": 65},
        )

        assert len(state.results) == 2
        assert "explorer" in state.results
        assert "analyst" in state.results
        assert state.results["explorer"].metadata["entities"] == 100
        assert state.results["analyst"].metadata["debt_score"] == 65

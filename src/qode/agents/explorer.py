"""Explorer Agent — Deterministic structural discovery and entity extraction.

The Explorer Agent is the first agent in the pipeline and is entirely deterministic
(no LLM usage). It wraps the core ingestion pipeline to:
  1. Discover and parse all source files (Tree-sitter)
  2. Extract entities (functions, classes, imports, etc.) and relationships
  3. Build the initial knowledge graph in KuzuDB
  4. Generate embeddings for all code entities

All subsequent agents (Analyst, Security, Test, Documenter) depend on the
Explorer's output.

Per Qode documentation Section 10.2:
  - Role: Structural discovery and entity extraction
  - Input: Raw source files from local filesystem
  - Tools: Tree-sitter parser, file system walker, language detector
  - Process: Parse files into CST, extract entities, build knowledge graph
  - Output: Populated KuzuDB with nodes, edges, and metadata
  - LLM Usage: None (entirely deterministic)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from qode.agents.base import AgentResult, AgentState, AgentStatus
from qode.core.pipeline import run_pipeline
from qode.data.kuzu_adapter import init_kuzu, load_graph_to_kuzu
from qode.data.schemas import PipelineProgress, PipelineResult

logger = logging.getLogger(__name__)


@dataclass
class ExplorerResult:
    """Result from Explorer Agent execution.

    Attributes:
        total_files: Total number of files discovered.
        total_entities: Total number of entities extracted (functions, classes, etc.).
        db_path: Path to the populated KuzuDB database.
        duration_seconds: Total execution time.
    """

    total_files: int
    total_entities: int
    db_path: str
    duration_seconds: float


class ExplorerAgent:
    """Explorer Agent — deterministic structural analysis (no LLM).

    This is the foundational agent that all others depend on. It orchestrates:
      1. File discovery (walker + ignore)
      2. Structure processing (directory tree)
      3. Parsing (Tree-sitter, chunked by byte budget)
      4. Symbol resolution (imports, calls, heritage)
      5. Community detection (Leiden algorithm)
      6. Execution flow tracing (BFS from entry points)
      7. KuzuDB bulk load via CSV streaming
      8. Embedding generation

    The agent is a thin wrapper around the existing pipeline infrastructure.
    """

    def __init__(
        self,
        progress_callback: Callable[[PipelineProgress], None] | None = None,
    ) -> None:
        """Initialize the Explorer Agent.

        Args:
            progress_callback: Optional callback for progress updates.
                Signature: callback(progress: PipelineProgress)
        """
        self.progress_callback = progress_callback

    async def execute(self, state: AgentState) -> AgentState:
        """Execute the Explorer Agent pipeline.

        Args:
            state: Shared agent state containing project_root and db_path.

        Returns:
            Updated state with Explorer results added.

        Raises:
            ValueError: If project_root is invalid.
            RuntimeError: If pipeline execution fails.
        """
        start_time = time.time()
        logger.info("Explorer Agent starting for %s", state.project_root)

        try:
            # Validate inputs
            project_path = Path(state.project_root)
            if not project_path.exists() or not project_path.is_dir():
                raise ValueError(
                    f"Invalid project root: {state.project_root} (must be a directory)"
                )

            # Phase 1-6: Run the core pipeline (synchronous)
            logger.info("Running 6-phase ingestion pipeline...")
            pipeline_result: PipelineResult = run_pipeline(
                repo_path=state.project_root,
                on_progress=self.progress_callback,
            )

            # Phase 7: Initialize KuzuDB
            logger.info("Initializing KuzuDB at %s", state.db_path)
            await init_kuzu(state.db_path)

            # Phase 8: Load the graph into KuzuDB
            # (this handles CSV generation internally)
            logger.info("Loading graph into KuzuDB...")
            await load_graph_to_kuzu(
                graph=pipeline_result.parse_result,
                repo_path=state.project_root,
                storage_path=state.db_path,
                on_progress=None,
            )

            duration = time.time() - start_time
            logger.info("Explorer Agent completed in %.2fs", duration)

            # Count total entities from parse result
            total_entities = len(pipeline_result.parse_result.nodes)

            # Build ExplorerResult
            explorer_result = ExplorerResult(
                total_files=pipeline_result.total_file_count,
                total_entities=total_entities,
                db_path=state.db_path,
                duration_seconds=duration,
            )

            # Update agent state
            state.results["explorer"] = AgentResult(
                agent_name="explorer",
                status=AgentStatus.COMPLETED,
                duration_seconds=duration,
                metadata={
                    "total_files": explorer_result.total_files,
                    "total_entities": explorer_result.total_entities,
                },
            )

            return state

        except Exception as e:
            duration = time.time() - start_time
            logger.exception("Explorer Agent failed after %.2fs", duration)

            state.results["explorer"] = AgentResult(
                agent_name="explorer",
                status=AgentStatus.FAILED,
                duration_seconds=duration,
                error=str(e),
            )

            return state

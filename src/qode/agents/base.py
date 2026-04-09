"""Base agent class and shared state.

Defines the common interface and state management for all Qode agents.
Each agent (Explorer, Analyst, Security, Test, Documenter) implements
the AgentProtocol and operates on a shared AgentState.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class AgentStatus(str, Enum):
    """Agent execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentResult:
    """Base result from an agent execution.

    Attributes:
        agent_name: Name of the agent that produced this result.
        status: Execution status.
        duration_seconds: How long the agent took to run.
        error: Error message if status is FAILED.
        metadata: Additional agent-specific data.
    """

    agent_name: str
    status: AgentStatus
    duration_seconds: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """Shared state object passed between agents in the LangGraph workflow.

    Attributes:
        project_root: Path to the codebase being analyzed.
        db_path: Path to the KuzuDB database.
        results: Results from each agent, keyed by agent name.
        config: Configuration options (LLM provider, thresholds, etc.).
    """

    project_root: str
    db_path: str
    results: dict[str, AgentResult] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


class AgentProtocol(Protocol):
    """Protocol that all Qode agents must implement.

    Each agent receives the shared AgentState, performs its analysis,
    and returns an updated AgentState with its results.
    """

    async def execute(self, state: AgentState) -> AgentState:
        """Execute the agent's analysis.

        Args:
            state: The current shared state.

        Returns:
            Updated state with this agent's results added.
        """
        ...

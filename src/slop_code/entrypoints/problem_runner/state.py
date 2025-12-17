"""Problem state tracking for multi-problem execution.

This module provides the ProblemStateTracker class for managing execution
state across multiple concurrent problems.
"""

from __future__ import annotations

from collections.abc import Generator
from collections.abc import Sequence

from slop_code.agent_runner import AgentStateEnum
from slop_code.agent_runner import MetricsTracker
from slop_code.agent_runner import UsageTracker
from slop_code.entrypoints.problem_runner.models import ProblemState

_TERMINAL_STATES = frozenset({
    AgentStateEnum.COMPLETED,
    AgentStateEnum.FAILED,
    AgentStateEnum.ERROR,
})

_ACTIVE_STATES = frozenset({
    AgentStateEnum.RUNNING,
    AgentStateEnum.EVALUATING,
    AgentStateEnum.PENDING,
    AgentStateEnum.INITIALIZED,
})


class ProblemStateTracker:
    """Tracks execution state for multiple problems."""

    def __init__(
        self,
        problem_names: Sequence[str],
        checkpoint_map: dict[str, Sequence[str]] | None = None,
    ) -> None:
        """Initialize tracker with problem names and checkpoint mappings.

        Args:
            problem_names: Names of problems to track
            checkpoint_map: Optional mapping of problem names to checkpoint
                names for progress tracking
        """
        checkpoint_map = checkpoint_map or {}
        self._states: dict[str, ProblemState] = {}
        for problem in problem_names:
            state = ProblemState()
            state.set_checkpoints(checkpoint_map.get(problem, []))
            self._states[problem] = state

    def handle_update(
        self,
        problem_name: str,
        agent_usage: UsageTracker,
        metrics_tracker: MetricsTracker,
    ) -> None:
        """Update state for a specific problem.

        Args:
            problem_name: Name of the problem to update
            agent_usage: Current checkpoint's usage tracker
            metrics_tracker: Overall metrics tracker with state info
        """
        self._states[problem_name].update(
            checkpoint=metrics_tracker.current_checkpoint,
            agent_usage=agent_usage,
            metrics_tracker=metrics_tracker,
        )

    def completed_count(self) -> int:
        """Count of problems in a terminal state."""
        return sum(
            state.state in _TERMINAL_STATES for state in self._states.values()
        )

    def problems(self) -> Generator[tuple[str, ProblemState], None, None]:
        """Iterate over (problem_name, state) pairs."""
        yield from self._states.items()

    def __getitem__(self, problem_name: str) -> ProblemState:
        """Get state for a specific problem."""
        return self._states[problem_name]

    def is_alive(self) -> bool:
        """Check if any problems are still running."""
        return any(
            state.state in _ACTIVE_STATES for state in self._states.values()
        )

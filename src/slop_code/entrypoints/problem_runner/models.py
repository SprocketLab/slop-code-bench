"""Data models for problem execution.

This module defines the core data structures used for tracking problem
execution state and results.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from pydantic import Field

from slop_code.agent_runner import AgentStateEnum
from slop_code.agent_runner import MetricsTracker
from slop_code.agent_runner import UsageTracker
from slop_code.entrypoints.config.run_config import OneShotConfig

_TERMINAL_STATES = frozenset(
    {
        AgentStateEnum.COMPLETED,
        AgentStateEnum.FAILED,
        AgentStateEnum.ERROR,
        AgentStateEnum.HIT_RATE_LIMITED,
    }
)

if TYPE_CHECKING:
    from slop_code.agent_runner import AgentConfigType
    from slop_code.agent_runner.credentials import ProviderCredential
    from slop_code.common.llms import ModelDefinition
    from slop_code.common.llms import ThinkingPreset
    from slop_code.evaluation import PassPolicy
    from slop_code.execution import EnvironmentSpecType


class TaskResult:
    """Result of running a single problem."""

    def __init__(
        self,
        problem_name: str,
        *,
        success: bool,
        error_message: str | None = None,
        error_type: str | None = None,
        error_traceback: str | None = None,
    ):
        self.problem_name = problem_name
        self.success = success
        self.error_message = error_message
        self.error_type = error_type
        self.error_traceback = error_traceback

    def __repr__(self) -> str:
        status = "success" if self.success else "failed"
        if self.error_type:
            status = f"{status}, {self.error_type}"
        return f"TaskResult({self.problem_name}, {status})"


@dataclass
class RunTaskConfig:
    """Configuration shared by all problem execution verifiers."""

    problem_base_path: Path
    run_dir: Path
    image: str
    env_spec: EnvironmentSpecType
    agent_config: AgentConfigType
    model_def: ModelDefinition
    credential: ProviderCredential
    prompt_template: str
    pass_policy: PassPolicy
    seed: int
    verbosity: int
    thinking_preset: ThinkingPreset | None = None
    thinking_max_tokens: int | None = None
    debug: bool = False
    live_progress: bool = False
    disable_evaluation: bool = False
    resume: bool = False
    dry_run: bool = False
    one_shot: OneShotConfig = field(default_factory=OneShotConfig)


class ProblemState(BaseModel):
    """Execution state for a single problem.

    Tracks checkpoint progress, usage metrics, timing, and error information.
    """

    checkpoint: str = Field(default="—", description="Current checkpoint name")
    state: AgentStateEnum = Field(
        default=AgentStateEnum.PENDING,
        description="Current execution state",
    )
    started: datetime | None = Field(
        default=None,
        description="When execution started",
    )
    checkpoint_started: datetime | None = Field(
        default=None,
        description="When current checkpoint started",
    )
    checkpoint_ended: datetime | None = Field(
        default=None,
        description="When current checkpoint ended (for terminal states)",
    )
    agent_usage: UsageTracker | None = Field(
        default=None,
        description="Usage for current checkpoint",
    )
    overall_usage: UsageTracker | None = Field(
        default=None,
        description="Cumulative usage across checkpoints",
    )
    checkpoint_order: list[str] = Field(
        default_factory=list,
        description="Ordered list of checkpoint names",
    )
    checkpoint_index_map: dict[str, int] = Field(
        default_factory=dict,
        description="Mapping from checkpoint name to index",
    )
    error_type: str | None = Field(default=None, description="Exception type")
    error_message: str | None = Field(default=None, description="Error message")
    error_traceback: str | None = Field(default=None, description="Traceback")
    # Checkpoint evaluation stats for progress tracking
    checkpoints_passed: int = Field(
        default=0, description="Checkpoints with pass_rate == 1.0"
    )
    checkpoints_iso_passed: int = Field(
        default=0, description="Checkpoints with checkpoint_pass_rate == 1.0"
    )
    total_checkpoints_evaluated: int = Field(
        default=0, description="Number of checkpoints evaluated so far"
    )

    def set_checkpoints(self, checkpoints: Sequence[str]) -> None:
        """Initialize checkpoint ordering."""
        self.checkpoint_order = list(checkpoints)
        self.checkpoint_index_map = {
            name: idx for idx, name in enumerate(self.checkpoint_order)
        }

    def update(
        self,
        checkpoint: str,
        agent_usage: UsageTracker,
        metrics_tracker: MetricsTracker,
    ) -> None:
        """Update state from a progress update."""
        self.checkpoint = checkpoint
        self.state = metrics_tracker.state
        self.agent_usage = agent_usage
        if self.started is None:
            self.started = metrics_tracker.started
        self.checkpoint_started = metrics_tracker.checkpoint_started
        self.overall_usage = metrics_tracker.usage
        self.error_type = metrics_tracker.error_type
        self.error_message = metrics_tracker.error_message
        self.error_traceback = metrics_tracker.error_traceback
        # Record when the checkpoint ended for terminal states
        if self.state in _TERMINAL_STATES and self.checkpoint_ended is None:
            self.checkpoint_ended = datetime.now()
        # Update checkpoint evaluation stats from metrics tracker
        if metrics_tracker.checkpoint_results:
            self.total_checkpoints_evaluated = len(
                metrics_tracker.checkpoint_results
            )
            self.checkpoints_passed = sum(
                1 for r in metrics_tracker.checkpoint_results if r.passed
            )
            self.checkpoints_iso_passed = sum(
                1 for r in metrics_tracker.checkpoint_results if r.iso_passed
            )

    def get_elapsed_time(self) -> float:
        """Get elapsed time since execution started."""
        if self.started is None:
            return 0.0
        return (datetime.now() - self.started).total_seconds()

    def get_checkpoint_elapsed_time(self) -> float:
        """Get elapsed time since current checkpoint started."""
        if self.checkpoint_started is None:
            return 0.0
        # Use the end time for terminal states, otherwise use current time
        end_time = self.checkpoint_ended or datetime.now()
        return (end_time - self.checkpoint_started).total_seconds()

    def get_checkpoint_progress(self) -> tuple[int, int]:
        """Get (completed, total) checkpoint counts."""
        total = len(self.checkpoint_order)
        if total == 0:
            return 0, 0

        if self.state == AgentStateEnum.COMPLETED:
            return total, total

        current_index = self.checkpoint_index_map.get(self.checkpoint, -1)
        completed = max(current_index, 0)

        if self.state in {AgentStateEnum.FAILED, AgentStateEnum.ERROR}:
            return completed, total

        if current_index == -1:
            return 0, total

        return completed, total

    @property
    def checkpoint_cost(self) -> float:
        """Cost for current checkpoint."""
        return self.agent_usage.cost if self.agent_usage else 0.0

    @property
    def prior_cost(self) -> float:
        """Cost from prior checkpoints."""
        return self.overall_usage.cost if self.overall_usage else 0.0

    @property
    def net_cost(self) -> float:
        """Total cost including current checkpoint."""
        return self.prior_cost + self.checkpoint_cost

    def _get_token_metrics(self) -> dict[str, int]:
        """Extract token metrics from agent usage."""
        if self.agent_usage is None:
            return {
                "generated_tokens": 0,
                "reasoning_tokens": 0,
                "input_tokens": 0,
                "total_tokens": 0,
            }
        return {
            "generated_tokens": self.agent_usage.net_tokens.output,
            "reasoning_tokens": self.agent_usage.net_tokens.reasoning,
            "input_tokens": self.agent_usage.net_tokens.input,
            "total_tokens": self.agent_usage.net_tokens.total,
        }

    def _get_step_metrics(self) -> dict[str, Any]:
        """Extract step metrics from usage trackers."""
        return {
            "steps": self.agent_usage.steps if self.agent_usage else 0,
            "total_steps": (
                self.overall_usage.steps if self.overall_usage else 0
            ),
            "total_cost": (
                self.overall_usage.cost if self.overall_usage else 0.0
            ),
        }

    def _get_error_info(self) -> dict[str, str | None]:
        """Extract error information."""
        return {
            "error_type": self.error_type,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
        }

    def get_simple_state(self) -> dict[str, Any]:
        """Get simplified state dictionary for logging and display."""
        state_value = (
            self.state.value
            if isinstance(self.state, AgentStateEnum)
            else self.state
        )
        return {
            "checkpoint": self.checkpoint,
            "state": state_value,
            "started": self.started,
            "elapsed": self.get_elapsed_time(),
            "checkpoint_cost": self.checkpoint_cost,
            "prior_cost": self.prior_cost,
            "net_cost": self.net_cost,
            **self._get_token_metrics(),
            **self._get_step_metrics(),
            **self._get_error_info(),
        }

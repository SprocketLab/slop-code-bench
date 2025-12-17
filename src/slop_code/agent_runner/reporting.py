from __future__ import annotations

import json
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_validator

from slop_code import common
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import CheckpointInferenceResult
from slop_code.agent_runner.models import AgentRunSpec
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.state import AgentStateEnum
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import CorrectnessResults
from slop_code.evaluation import PassPolicy
from slop_code.execution import SnapshotDiff
from slop_code.logging import get_logger

logger = get_logger(__name__)


class AgentCheckpointSummary(BaseModel):
    """Result of running an agent on a single checkpoint.

    Attributes:
        checkpoint_name: Name of the checkpoint.
        path: Path to the checkpoint directory.
        snapshot_dir: Relative path to the snapshot directory.
        artifacts: Relative path to the agent artifacts directory.
        usage: Usage tracker with cost and token counts.
        passed_policy: Whether checkpoint passed the configured pass policy.
        had_error: Whether an error occurred during execution.
        error_message: Error message if one occurred.
    """

    checkpoint_name: str
    path: Path
    snapshot_dir: Path
    artifacts: Path
    usage: UsageTracker
    passed_policy: bool | None = None
    error_message: str | None = None
    had_error: bool

    @classmethod
    def from_results(
        cls,
        checkpoint_name: str,
        path: Path,
        snapshot_dir: Path,
        artifacts: Path,
        usage: UsageTracker,
        had_error: bool,
        pass_policy: PassPolicy,
        evaluation_result: CorrectnessResults | None = None,
    ) -> AgentCheckpointSummary:
        if isinstance(pass_policy, str):
            pass_policy = PassPolicy(pass_policy)

        if evaluation_result is not None:
            passed_policy = pass_policy.check(
                evaluation_result.pass_counts,
                evaluation_result.total_counts,
            )
        else:
            # No evaluation - pass if policy allows any case
            passed_policy = pass_policy == PassPolicy.ANY_CASE

        return cls(
            checkpoint_name=checkpoint_name,
            path=path,
            snapshot_dir=snapshot_dir,
            artifacts=artifacts,
            usage=usage.model_copy(deep=True),
            had_error=had_error,
            passed_policy=passed_policy,
        )


class CheckpointState:
    """Valid states for checkpoint execution."""

    RAN = "ran"
    SKIPPED = "skipped"
    ERROR = "error"


class RunSummary(BaseModel):
    """Execution summary for an agent problem run.

    This contains only aggregated/summary information. Detailed per-checkpoint
    data should be read from individual inference_result.json and
    evaluation.json files in each checkpoint directory.

    Attributes:
        started: Timestamp when execution started
        ended: Timestamp when execution ended
        duration_seconds: Total duration in seconds
        total_cost: Total cost across all checkpoints
        total_steps: Total steps across all checkpoints
        total_usage: Aggregated usage tracker
        checkpoints: Dict mapping checkpoint name to state (ran/skipped/error)
        state: Final execution state
        error_type: Type of error if one occurred
        error_message: Error message if one occurred
        error_traceback: Error traceback if one occurred
        passed_policy: Whether all checkpoints passed the policy
    """

    model_config = ConfigDict(use_enum_values=True)

    # Timing
    started: datetime
    ended: datetime
    duration_seconds: float

    # Aggregated usage
    total_cost: float
    total_steps: int
    total_usage: UsageTracker

    # Checkpoint tracking: checkpoint_name -> state (ran/skipped/error)
    checkpoints: dict[str, str]

    # State/error
    state: AgentStateEnum
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None

    # Aggregated evaluation
    passed_policy: bool | None = None

    @field_validator("ended")
    @classmethod
    def validate_ended(cls, v: str | datetime) -> datetime:
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v

    @field_validator("started")
    @classmethod
    def validate_started(cls, v: str | datetime) -> datetime:
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v


class MetricsTracker(BaseModel):
    """Tracks metrics and state during agent execution.

    Attributes:
        state: Current execution state of the agent
        current_checkpoint: Name of the checkpoint being processed
        usage: Usage tracker for cost and tokens
        started: Timestamp when execution started
        checkpoint_started: Timestamp when current checkpoint started
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    state: AgentStateEnum = AgentStateEnum.INITIALIZED
    current_checkpoint: str
    usage: UsageTracker
    started: datetime
    checkpoint_started: datetime
    error_type: str | None = None
    error_message: str | None = None
    error_traceback: str | None = None

    def finish_checkpoint(self, usage: UsageTracker) -> None:
        """Update usage metrics after checkpoint completion.

        Args:
            usage: UsageTracker with usage data to incorporate
        """
        self.usage.cost += usage.cost
        self.usage.steps += usage.steps
        self.usage.net_tokens += usage.net_tokens
        self.usage.current_tokens += usage.current_tokens

    def had_error(self) -> bool:
        """Check if the agent is in an error state.

        Returns:
            True if agent state is ERROR, False otherwise
        """
        return self.state in {
            AgentStateEnum.ERROR,
        }

    def record_error(
        self,
        error: BaseException,
        *,
        traceback_text: str | None = None,
    ) -> None:
        """Capture error details for downstream reporting."""
        self.error_type = type(error).__name__
        self.error_message = str(error)
        self.error_traceback = traceback_text


def setup_run_output_directory(
    run_spec: AgentRunSpec, output_path: Path
) -> None:
    """Set up the output directory for an agent run.

    Creates the output directory and saves the problem configuration as YAML.
    The run specification and execution summary are saved together in
    run_info.yaml by save_results() at the end of the run.

    Args:
        run_spec: Specification for the agent run
        output_path: Directory path where output should be saved
    """
    logger.debug(
        "Setting up output directory",
        output_path=output_path,
        problem=run_spec.problem.name,
    )

    problem = common.serialize_path_dict(
        run_spec.problem.model_dump(mode="json")
    )
    with (output_path / common.PROBLEM_CONFIG_NAME).open("w") as f:
        yaml.dump(
            problem,
            f,
            indent=2,
            sort_keys=True,
        )


def setup_checkpoint_output_directory(
    checkpoint: CheckpointConfig, output_path: Path
) -> Path:
    """Set up output directory for a specific checkpoint.

    Creates a subdirectory for the checkpoint and saves its configuration.

    Args:
        checkpoint: Checkpoint configuration
        output_path: Base output directory path

    Returns:
        Path to the created checkpoint output directory
    """
    logger.debug(
        "Setting up checkpoint output directory",
        output_path=output_path,
        checkpoint=checkpoint.name,
    )

    checkpoint_save_dir = output_path / checkpoint.name
    checkpoint_save_dir.mkdir(parents=True, exist_ok=True)
    with (checkpoint_save_dir / common.CHECKPOINT_CONFIG_NAME).open("w") as f:
        yaml.dump(
            common.serialize_path_dict(checkpoint.model_dump(mode="json")),
            f,
            indent=2,
            sort_keys=True,
        )
    return checkpoint_save_dir


def save_results(
    results: list[AgentCheckpointSummary],
    metrics_tracker: MetricsTracker,
    run_spec: AgentRunSpec,
    output_path: Path,
) -> dict[str, Any]:
    """Save agent run info to YAML file.

    Saves a combined run_info.yaml with run specification and execution summary.
    Per-checkpoint details are stored in individual inference_result.json
    and evaluation.json files.

    Args:
        results: List of checkpoint results
        metrics_tracker: Metrics tracker with aggregated usage
        run_spec: Original run specification
        output_path: Directory to save results

    Returns:
        Dictionary containing the complete run info data
    """
    logger.info(
        "Saving run info",
        problem=run_spec.problem.name,
        checkpoints=len(results),
        output_path=output_path,
    )

    # Build checkpoint state dict: name -> state (ran/skipped/error)
    all_checkpoint_names = list(run_spec.problem.checkpoints.keys())
    results_by_name = {r.checkpoint_name: r for r in results}
    checkpoints_state: dict[str, str] = {}
    for name in all_checkpoint_names:
        if name in results_by_name:
            result = results_by_name[name]
            if result.had_error:
                checkpoints_state[name] = CheckpointState.ERROR
            else:
                checkpoints_state[name] = CheckpointState.RAN
        else:
            checkpoints_state[name] = CheckpointState.SKIPPED

    ended = datetime.now()
    summary = RunSummary(
        started=metrics_tracker.started,
        ended=ended,
        duration_seconds=(ended - metrics_tracker.started).total_seconds(),
        total_cost=metrics_tracker.usage.cost,
        total_steps=metrics_tracker.usage.steps,
        total_usage=metrics_tracker.usage,
        checkpoints=checkpoints_state,
        state=metrics_tracker.state,
        error_type=metrics_tracker.error_type,
        error_message=metrics_tracker.error_message,
        error_traceback=metrics_tracker.error_traceback,
        passed_policy=all(
            r.passed_policy or run_spec.skip_evaluation for r in results
        ),
    )

    # Build combined run_info structure
    spec_dump = common.serialize_path_dict(run_spec.model_dump(mode="json"))
    spec_dump.pop("environment")
    spec_dump.pop("problem")
    spec_dump.update(common.get_save_spec_dump())

    run_info: dict[str, Any] = {
        **spec_dump,
        "summary": common.serialize_path_dict(summary.model_dump(mode="json")),
    }

    with (output_path / common.RUN_INFO_FILENAME).open("w") as f:
        yaml.dump(run_info, f, indent=2, sort_keys=True)

    logger.info(
        "Run info saved successfully",
        problem=run_spec.problem.name,
        passed_policy=summary.passed_policy,
        total_cost=summary.total_cost,
    )
    return run_info


def save_agent_checkpoint_info(
    output_path: Path,
    diff: SnapshotDiff,
    checkpoint_result: CheckpointInferenceResult,
    agent: Agent,
    *,
    compress_artifacts: bool = True,
) -> None:
    logger.info(
        "Saving agent checkpoint info",
        output_path=output_path,
        compress_artifacts=compress_artifacts,
    )
    with (output_path / common.DIFF_FILENAME).open("w") as f:
        f.write(diff.model_dump_json())

    if compress_artifacts:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            agent.save_artifacts(temp_path)
            tar_path = output_path / common.AGENT_TAR_FILENAME
            with tarfile.open(tar_path, "w:gz") as tar:
                for item in temp_path.iterdir():
                    tar.add(item, arcname=item.name)
        artifacts_name = common.AGENT_TAR_FILENAME
    else:
        agent_dir = output_path / common.AGENT_DIR_NAME
        agent_dir.mkdir(parents=True, exist_ok=True)
        agent.save_artifacts(agent_dir)
        artifacts_name = common.AGENT_DIR_NAME

    # Add path fields to checkpoint result before saving
    result_with_paths = checkpoint_result.model_copy(
        update={
            "checkpoint_path": common.to_relative_path(output_path),
            "snapshot_dir": common.SNAPSHOT_DIR_NAME,
            "artifacts_dir": artifacts_name,
        }
    )

    with (output_path / common.INFERENCE_RESULT_FILENAME).open("w") as f:
        f.write(
            json.dumps(
                common.serialize_path_dict(
                    result_with_paths.model_dump(mode="json")
                ),
                indent=2,
                sort_keys=True,
            )
        )

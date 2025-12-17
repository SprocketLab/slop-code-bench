"""Tests for agent runner reporting module."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import yaml

from slop_code.agent_runner.agent import CheckpointInferenceResult
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.reporting import CheckpointState
from slop_code.agent_runner.reporting import RunSummary
from slop_code.agent_runner.reporting import save_agent_checkpoint_info
from slop_code.agent_runner.reporting import save_results
from slop_code.agent_runner.state import AgentStateEnum
from slop_code.common.llms import TokenUsage
from slop_code.evaluation import PassPolicy


def _make_usage_tracker(
    cost: float = 0.5, steps: int = 10
) -> UsageTracker:
    """Create a UsageTracker for testing."""
    return UsageTracker(
        cost=cost,
        steps=steps,
        current_tokens=TokenUsage(input=100, output=50),
        net_tokens=TokenUsage(input=100, output=50),
    )


class TestRunSummary:
    """Tests for RunSummary model."""

    def test_serialization_contains_checkpoints_dict(self) -> None:
        """Test that RunSummary serializes checkpoints as dict."""
        now = datetime.now()
        summary = RunSummary(
            started=now,
            ended=now,
            duration_seconds=60.0,
            total_cost=1.5,
            total_steps=10,
            total_usage=_make_usage_tracker(),
            checkpoints={
                "checkpoint_1": CheckpointState.RAN,
                "checkpoint_2": CheckpointState.SKIPPED,
                "checkpoint_3": CheckpointState.ERROR,
            },
            state=AgentStateEnum.COMPLETED,
        )
        data = summary.model_dump(mode="json")

        # Checkpoints should be a dict with state values
        assert "checkpoints" in data
        assert data["checkpoints"]["checkpoint_1"] == "ran"
        assert data["checkpoints"]["checkpoint_2"] == "skipped"
        assert data["checkpoints"]["checkpoint_3"] == "error"

        # Old format fields should NOT exist
        assert "checkpoints_inferred" not in data
        assert "checkpoints_skipped" not in data

    def test_datetime_validators(self) -> None:
        """Test that datetime fields accept ISO format strings."""
        now = datetime.now()
        iso_now = now.isoformat()

        summary = RunSummary(
            started=iso_now,  # string input
            ended=iso_now,  # string input
            duration_seconds=60.0,
            total_cost=1.5,
            total_steps=10,
            total_usage=_make_usage_tracker(),
            checkpoints={},
            state=AgentStateEnum.COMPLETED,
        )

        assert isinstance(summary.started, datetime)
        assert isinstance(summary.ended, datetime)


class TestCheckpointInferenceResultPaths:
    """Tests for CheckpointInferenceResult path fields."""

    def test_path_fields_serialize_correctly(self) -> None:
        """Test that path fields serialize to strings."""
        now = datetime.now()
        result = CheckpointInferenceResult(
            started=now,
            completed=now,
            elapsed=60.0,
            usage=_make_usage_tracker(),
            had_error=False,
            checkpoint_path=Path("/output/checkpoint_1"),
            snapshot_dir=Path("snapshot"),
            artifacts_dir=Path("agent"),
        )
        data = result.model_dump(mode="json")

        assert data["checkpoint_path"] == "/output/checkpoint_1"
        assert data["snapshot_dir"] == "snapshot"
        assert data["artifacts_dir"] == "agent"

    def test_path_fields_optional(self) -> None:
        """Test that path fields default to None."""
        now = datetime.now()
        result = CheckpointInferenceResult(
            started=now,
            completed=now,
            elapsed=60.0,
            usage=_make_usage_tracker(),
            had_error=False,
        )

        assert result.checkpoint_path is None
        assert result.snapshot_dir is None
        assert result.artifacts_dir is None


class TestSaveAgentCheckpointInfo:
    """Tests for save_agent_checkpoint_info function."""

    def test_populates_path_fields(self, tmp_path: Path) -> None:
        """Test that path fields are populated in inference_result.json."""
        now = datetime.now()
        checkpoint_result = CheckpointInferenceResult(
            started=now,
            completed=now,
            elapsed=60.0,
            usage=_make_usage_tracker(),
            had_error=False,
        )

        # Mock the diff and agent
        diff = Mock()
        diff.model_dump_json.return_value = "{}"

        agent = Mock()
        agent.save_artifacts = Mock()

        save_agent_checkpoint_info(
            tmp_path, diff, checkpoint_result, agent, compress_artifacts=False
        )

        # Read the saved inference_result.json
        inference_file = tmp_path / "inference_result.json"
        assert inference_file.exists()

        with inference_file.open("r") as f:
            saved_data = json.load(f)

        # Verify path fields are populated
        assert saved_data["checkpoint_path"] == str(tmp_path)
        assert saved_data["snapshot_dir"] == "snapshot"
        assert saved_data["artifacts_dir"] == "agent"


class TestSaveResults:
    """Tests for save_results function."""

    def test_creates_run_info_yaml(self, tmp_path: Path) -> None:
        """Test that save_results creates run_info.yaml with summary section."""
        # Create mock checkpoint summary
        checkpoint_summary = Mock()
        checkpoint_summary.checkpoint_name = "checkpoint_1"
        checkpoint_summary.passed_policy = True
        checkpoint_summary.had_error = False

        # Create mock metrics tracker
        metrics_tracker = Mock()
        metrics_tracker.state = AgentStateEnum.COMPLETED
        metrics_tracker.usage = _make_usage_tracker(cost=1.5, steps=10)
        metrics_tracker.started = datetime.now()
        metrics_tracker.error_type = None
        metrics_tracker.error_message = None
        metrics_tracker.error_traceback = None

        # Create mock run spec
        run_spec = Mock()
        run_spec.problem.name = "test_problem"
        run_spec.problem.version = 1
        run_spec.problem.entry_file = "main.py"
        run_spec.problem.checkpoints = {
            "checkpoint_1": Mock(),
            "checkpoint_2": Mock(),
        }
        run_spec.problem.model_dump.return_value = {
            "name": "test_problem",
            "version": 1,
            "entry_file": "main.py",
        }
        run_spec.model_dump.return_value = {
            "seed": 42,
            "pass_policy": "any-case",
            "skip_evaluation": False,
            "template": "test.jinja",
            "environment": {},
            "problem": {},
        }
        run_spec.seed = 42
        run_spec.pass_policy = PassPolicy.ANY
        run_spec.skip_evaluation = False
        run_spec.environment.get_command.return_value = "python main.py"

        save_results(
            results=[checkpoint_summary],
            metrics_tracker=metrics_tracker,
            run_spec=run_spec,
            output_path=tmp_path,
        )

        # Verify run_info.yaml was written
        run_info_file = tmp_path / "run_info.yaml"
        assert run_info_file.exists()

        with run_info_file.open("r") as f:
            saved_data = yaml.safe_load(f)

        # Verify structure: top-level has run spec fields, summary is nested
        # Note: problem and environment are explicitly removed by save_results()
        assert "summary" in saved_data
        assert "seed" in saved_data

        # Verify summary contains checkpoint states
        summary = saved_data["summary"]
        assert "checkpoints" in summary
        assert summary["checkpoints"]["checkpoint_1"] == "ran"
        assert summary["checkpoints"]["checkpoint_2"] == "skipped"

        # Verify summary fields
        assert "duration_seconds" in summary
        assert "total_cost" in summary
        assert "total_steps" in summary
        assert "state" in summary

    def test_checkpoint_error_state(self, tmp_path: Path) -> None:
        """Test that checkpoint with error gets 'error' state."""
        # Create mock checkpoint summary with error
        checkpoint_summary = Mock()
        checkpoint_summary.checkpoint_name = "checkpoint_1"
        checkpoint_summary.passed_policy = False
        checkpoint_summary.had_error = True

        # Create mock metrics tracker
        metrics_tracker = Mock()
        metrics_tracker.state = AgentStateEnum.ERROR
        metrics_tracker.usage = _make_usage_tracker(cost=0.5, steps=5)
        metrics_tracker.started = datetime.now()
        metrics_tracker.error_type = "RuntimeError"
        metrics_tracker.error_message = "Something went wrong"
        metrics_tracker.error_traceback = "..."

        # Create mock run spec
        run_spec = Mock()
        run_spec.problem.name = "test_problem"
        run_spec.problem.version = 1
        run_spec.problem.entry_file = "main.py"
        run_spec.problem.checkpoints = {"checkpoint_1": Mock()}
        run_spec.problem.model_dump.return_value = {"name": "test_problem"}
        run_spec.model_dump.return_value = {
            "seed": 42,
            "pass_policy": "any-case",
            "skip_evaluation": False,
            "environment": {},
            "problem": {},
        }
        run_spec.seed = 42
        run_spec.pass_policy = PassPolicy.ANY
        run_spec.skip_evaluation = False
        run_spec.environment.get_command.return_value = "python main.py"

        result = save_results(
            results=[checkpoint_summary],
            metrics_tracker=metrics_tracker,
            run_spec=run_spec,
            output_path=tmp_path,
        )

        # Verify checkpoint has error state
        assert result["summary"]["checkpoints"]["checkpoint_1"] == "error"
        assert result["summary"]["error_type"] == "RuntimeError"

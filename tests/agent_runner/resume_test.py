"""Tests for checkpoint resume functionality."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.reporting import CheckpointState
from slop_code.agent_runner.reporting import MetricsTracker
from slop_code.agent_runner.resume import ResumeInfo
from slop_code.agent_runner.resume import _aggregate_prior_usage
from slop_code.agent_runner.resume import _detect_resume_from_artifacts
from slop_code.agent_runner.resume import detect_resume_point
from slop_code.common import INFERENCE_RESULT_FILENAME
from slop_code.common import RUN_INFO_FILENAME
from slop_code.common import SNAPSHOT_DIR_NAME
from slop_code.common.llms import TokenUsage
from slop_code.execution.models import SetupConfig


class TestSetupConfigResumeCommands:
    """Tests for resume_commands in SetupConfig."""

    def test_resume_commands_default_empty(self) -> None:
        """Resume commands default to empty list."""
        config = SetupConfig()
        assert config.resume_commands == []

    def test_resume_commands_can_be_set(self) -> None:
        """Resume commands can be set explicitly."""
        config = SetupConfig(
            resume_commands=["pip install -r requirements.txt"]
        )
        assert config.resume_commands == ["pip install -r requirements.txt"]

    def test_resume_commands_multiple(self) -> None:
        """Multiple resume commands can be set."""
        config = SetupConfig(
            resume_commands=[
                "pip install -r requirements.txt",
                "python -m pip install --upgrade pip",
            ]
        )
        assert len(config.resume_commands) == 2


class TestResumeInfo:
    """Tests for ResumeInfo dataclass."""

    def test_resume_info_creation(self, tmp_path: Path) -> None:
        """Test basic ResumeInfo creation."""
        snapshot_dir = tmp_path / "checkpoint_1" / "snapshot"
        snapshot_dir.mkdir(parents=True)

        info = ResumeInfo(
            resume_from_checkpoint="checkpoint_2",
            completed_checkpoints=["checkpoint_1"],
            last_snapshot_dir=snapshot_dir,
            prior_usage=UsageTracker(cost=1.5, steps=10),
        )

        assert info.resume_from_checkpoint == "checkpoint_2"
        assert info.completed_checkpoints == ["checkpoint_1"]
        assert info.last_snapshot_dir == snapshot_dir
        assert info.prior_usage.cost == 1.5
        assert info.prior_usage.steps == 10


class TestDetectResumePoint:
    """Tests for detect_resume_point function."""

    def test_returns_resume_info_when_no_run_info_and_no_artifacts(
        self, tmp_path: Path
    ) -> None:
        """Returns ResumeInfo to start from first checkpoint when no prior state exists."""
        result = detect_resume_point(tmp_path, ["checkpoint_1", "checkpoint_2"])
        # When no run_info.yaml and no checkpoint directories exist,
        # returns ResumeInfo with all checkpoints invalidated (need to run from start)
        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_1"
        assert result.completed_checkpoints == []
        assert result.invalidated_checkpoints == [
            "checkpoint_1",
            "checkpoint_2",
        ]

    def test_returns_resume_info_when_all_checkpoints_completed(
        self, tmp_path: Path
    ) -> None:
        """Returns ResumeInfo with empty resume_from when all checkpoints completed."""
        # Create run_info.yaml with all checkpoints completed
        run_info = {
            "summary": {
                "checkpoints": {
                    "checkpoint_1": CheckpointState.RAN,
                    "checkpoint_2": CheckpointState.RAN,
                }
            }
        }
        with (tmp_path / RUN_INFO_FILENAME).open("w") as f:
            yaml.dump(run_info, f)

        # Create snapshot directories
        (tmp_path / "checkpoint_1" / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        (tmp_path / "checkpoint_2" / SNAPSHOT_DIR_NAME).mkdir(parents=True)

        result = detect_resume_point(tmp_path, ["checkpoint_1", "checkpoint_2"])
        assert result is not None
        assert result.resume_from_checkpoint == ""  # Empty = nothing to resume
        assert result.completed_checkpoints == ["checkpoint_1", "checkpoint_2"]
        assert result.invalidated_checkpoints == []

    def test_returns_resume_info_when_no_checkpoints_completed(
        self, tmp_path: Path
    ) -> None:
        """Returns ResumeInfo to resume from first checkpoint when none completed."""
        run_info = {
            "summary": {
                "checkpoints": {
                    "checkpoint_1": CheckpointState.SKIPPED,
                    "checkpoint_2": CheckpointState.SKIPPED,
                }
            }
        }
        with (tmp_path / RUN_INFO_FILENAME).open("w") as f:
            yaml.dump(run_info, f)

        result = detect_resume_point(tmp_path, ["checkpoint_1", "checkpoint_2"])
        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_1"
        assert result.completed_checkpoints == []
        assert result.invalidated_checkpoints == [
            "checkpoint_1",
            "checkpoint_2",
        ]

    def test_detects_resume_point_after_first_checkpoint(
        self, tmp_path: Path
    ) -> None:
        """Detects correct resume point when first checkpoint completed."""
        # Create run_info.yaml
        run_info = {
            "summary": {
                "checkpoints": {
                    "checkpoint_1": CheckpointState.RAN,
                    "checkpoint_2": CheckpointState.ERROR,
                }
            }
        }
        with (tmp_path / RUN_INFO_FILENAME).open("w") as f:
            yaml.dump(run_info, f)

        # Create checkpoint_1 snapshot and inference result
        checkpoint_1_dir = tmp_path / "checkpoint_1"
        (checkpoint_1_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        inference_result = {
            "usage": {"cost": 0.5, "steps": 5, "net_tokens": {"input": 100}}
        }
        with (checkpoint_1_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(inference_result, f)

        result = detect_resume_point(
            tmp_path, ["checkpoint_1", "checkpoint_2", "checkpoint_3"]
        )

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_2"
        assert result.completed_checkpoints == ["checkpoint_1"]
        assert result.last_snapshot_dir == checkpoint_1_dir / SNAPSHOT_DIR_NAME
        assert result.prior_usage.cost == 0.5
        assert result.prior_usage.steps == 5

    def test_detects_resume_point_after_multiple_checkpoints(
        self, tmp_path: Path
    ) -> None:
        """Detects correct resume point when multiple checkpoints completed."""
        run_info = {
            "summary": {
                "checkpoints": {
                    "checkpoint_1": CheckpointState.RAN,
                    "checkpoint_2": CheckpointState.RAN,
                    "checkpoint_3": CheckpointState.ERROR,
                }
            }
        }
        with (tmp_path / RUN_INFO_FILENAME).open("w") as f:
            yaml.dump(run_info, f)

        # Create snapshots and inference results
        for i, cost in [(1, 0.5), (2, 0.8)]:
            checkpoint_dir = tmp_path / f"checkpoint_{i}"
            (checkpoint_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
            inference_result = {"usage": {"cost": cost, "steps": i * 5}}
            with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
                json.dump(inference_result, f)

        result = detect_resume_point(
            tmp_path, ["checkpoint_1", "checkpoint_2", "checkpoint_3"]
        )

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_3"
        assert result.completed_checkpoints == ["checkpoint_1", "checkpoint_2"]
        assert (
            result.last_snapshot_dir
            == tmp_path / "checkpoint_2" / SNAPSHOT_DIR_NAME
        )
        # Aggregated cost from both checkpoints
        assert result.prior_usage.cost == 1.3
        assert result.prior_usage.steps == 15

    def test_handles_missing_snapshot_directory(self, tmp_path: Path) -> None:
        """Checkpoint with missing snapshot is not considered complete."""
        run_info = {
            "summary": {
                "checkpoints": {
                    "checkpoint_1": CheckpointState.RAN,
                    "checkpoint_2": CheckpointState.RAN,
                }
            }
        }
        with (tmp_path / RUN_INFO_FILENAME).open("w") as f:
            yaml.dump(run_info, f)

        # Only create snapshot for checkpoint_1, not checkpoint_2
        (tmp_path / "checkpoint_1" / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        inference_result = {"usage": {"cost": 0.5, "steps": 5}}
        with (tmp_path / "checkpoint_1" / INFERENCE_RESULT_FILENAME).open(
            "w"
        ) as f:
            json.dump(inference_result, f)

        result = detect_resume_point(tmp_path, ["checkpoint_1", "checkpoint_2"])

        assert result is not None
        # Should resume from checkpoint_2 since it has no snapshot
        assert result.resume_from_checkpoint == "checkpoint_2"
        assert result.completed_checkpoints == ["checkpoint_1"]

    def test_handles_invalid_yaml(self, tmp_path: Path) -> None:
        """Returns None when run_info.yaml is invalid."""
        with (tmp_path / RUN_INFO_FILENAME).open("w") as f:
            f.write("invalid: yaml: content: {{{{")

        result = detect_resume_point(tmp_path, ["checkpoint_1"])
        assert result is None

    def test_handles_malformed_run_info(self, tmp_path: Path) -> None:
        """Returns ResumeInfo with invalidated checkpoints when run_info structure is unexpected."""
        with (tmp_path / RUN_INFO_FILENAME).open("w") as f:
            yaml.dump({"not_summary": {}}, f)

        result = detect_resume_point(tmp_path, ["checkpoint_1"])
        # When run_info.yaml has unexpected structure but is valid YAML,
        # checkpoints are treated as missing/invalid
        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_1"
        assert result.completed_checkpoints == []


class TestDetectResumeFromArtifacts:
    """Tests for _detect_resume_from_artifacts fallback function."""

    def test_returns_resume_info_when_no_snapshots(
        self, tmp_path: Path
    ) -> None:
        """Returns ResumeInfo to resume from first checkpoint when no snapshots exist."""
        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2"]
        )
        # When no checkpoint directories exist, returns ResumeInfo with all invalidated
        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_1"
        assert result.completed_checkpoints == []
        assert result.invalidated_checkpoints == [
            "checkpoint_1",
            "checkpoint_2",
        ]

    def test_resumes_from_checkpoint_with_error(self, tmp_path: Path) -> None:
        """Resumes from checkpoint that has snapshot + error."""
        # checkpoint_1: snapshot + no error (completed)
        checkpoint_1_dir = tmp_path / "checkpoint_1"
        (checkpoint_1_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_1_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(
                {"had_error": False, "usage": {"cost": 0.5, "steps": 5}}, f
            )

        # checkpoint_2: snapshot + error (resume from here)
        checkpoint_2_dir = tmp_path / "checkpoint_2"
        (checkpoint_2_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_2_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(
                {"had_error": True, "usage": {"cost": 0.3, "steps": 3}}, f
            )

        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2", "checkpoint_3"]
        )

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_2"
        assert result.completed_checkpoints == ["checkpoint_1"]
        assert result.prior_usage.cost == 0.5
        assert result.prior_usage.steps == 5

    def test_resumes_from_first_checkpoint_with_error(
        self, tmp_path: Path
    ) -> None:
        """Resumes from first checkpoint if it has error."""
        # checkpoint_1: snapshot + error (resume from here)
        checkpoint_1_dir = tmp_path / "checkpoint_1"
        (checkpoint_1_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_1_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(
                {"had_error": True, "usage": {"cost": 0.5, "steps": 5}}, f
            )

        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2"]
        )

        # No completed checkpoints, returns ResumeInfo to resume from first
        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_1"
        assert result.completed_checkpoints == []
        assert result.invalidated_checkpoints == [
            "checkpoint_1",
            "checkpoint_2",
        ]

    def test_resumes_from_next_checkpoint_after_completed(
        self, tmp_path: Path
    ) -> None:
        """Resumes from checkpoint after last completed one."""
        # checkpoint_1: snapshot + no error (completed)
        checkpoint_1_dir = tmp_path / "checkpoint_1"
        (checkpoint_1_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_1_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(
                {"had_error": False, "usage": {"cost": 1.0, "steps": 10}}, f
            )

        # checkpoint_2: no snapshot (resume from here)
        # (directory doesn't exist)

        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2", "checkpoint_3"]
        )

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_2"
        assert result.completed_checkpoints == ["checkpoint_1"]
        assert result.last_snapshot_dir == checkpoint_1_dir / SNAPSHOT_DIR_NAME
        assert result.prior_usage.cost == 1.0

    def test_returns_resume_info_when_all_completed(
        self, tmp_path: Path
    ) -> None:
        """Returns ResumeInfo with empty resume_from when all checkpoints completed."""
        for i in range(1, 3):
            checkpoint_dir = tmp_path / f"checkpoint_{i}"
            (checkpoint_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
            with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
                json.dump({"had_error": False, "usage": {"cost": 0.5}}, f)

        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2"]
        )
        assert result is not None
        assert result.resume_from_checkpoint == ""  # Empty = nothing to resume
        assert result.completed_checkpoints == ["checkpoint_1", "checkpoint_2"]
        assert result.invalidated_checkpoints == []

    def test_resumes_when_snapshot_but_no_inference_result(
        self, tmp_path: Path
    ) -> None:
        """Resumes from checkpoint with snapshot but missing inference result."""
        # checkpoint_1: snapshot + no error (completed)
        checkpoint_1_dir = tmp_path / "checkpoint_1"
        (checkpoint_1_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_1_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(
                {"had_error": False, "usage": {"cost": 0.5, "steps": 5}}, f
            )

        # checkpoint_2: snapshot but no inference result (resume from here)
        checkpoint_2_dir = tmp_path / "checkpoint_2"
        (checkpoint_2_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)

        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2", "checkpoint_3"]
        )

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_2"
        assert result.completed_checkpoints == ["checkpoint_1"]

    def test_resumes_when_inference_result_is_invalid_json(
        self, tmp_path: Path
    ) -> None:
        """Resumes from checkpoint with invalid inference result JSON."""
        # checkpoint_1: snapshot + no error (completed)
        checkpoint_1_dir = tmp_path / "checkpoint_1"
        (checkpoint_1_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_1_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(
                {"had_error": False, "usage": {"cost": 0.5, "steps": 5}}, f
            )

        # checkpoint_2: snapshot + invalid JSON (resume from here)
        checkpoint_2_dir = tmp_path / "checkpoint_2"
        (checkpoint_2_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_2_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            f.write("not valid json")

        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2", "checkpoint_3"]
        )

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_2"
        assert result.completed_checkpoints == ["checkpoint_1"]

    def test_aggregates_usage_from_completed_checkpoints(
        self, tmp_path: Path
    ) -> None:
        """Aggregates usage from all completed checkpoints."""
        # Create multiple completed checkpoints
        for i in range(1, 3):
            checkpoint_dir = tmp_path / f"checkpoint_{i}"
            (checkpoint_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
            with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
                json.dump(
                    {
                        "had_error": False,
                        "usage": {
                            "cost": float(i),
                            "steps": i * 10,
                            "net_tokens": {"input": i * 100, "output": i * 50},
                        },
                    },
                    f,
                )

        # checkpoint_3: no snapshot (resume from here)

        result = _detect_resume_from_artifacts(
            tmp_path, ["checkpoint_1", "checkpoint_2", "checkpoint_3"]
        )

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_3"
        assert result.completed_checkpoints == ["checkpoint_1", "checkpoint_2"]
        assert result.prior_usage.cost == 3.0  # 1 + 2
        assert result.prior_usage.steps == 30  # 10 + 20
        assert result.prior_usage.net_tokens.input == 300  # 100 + 200

    def test_detect_resume_point_uses_artifact_fallback(
        self, tmp_path: Path
    ) -> None:
        """detect_resume_point uses artifact fallback when no run_info.yaml."""
        # No run_info.yaml, but checkpoint_1 completed
        checkpoint_1_dir = tmp_path / "checkpoint_1"
        (checkpoint_1_dir / SNAPSHOT_DIR_NAME).mkdir(parents=True)
        with (checkpoint_1_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(
                {"had_error": False, "usage": {"cost": 1.0, "steps": 5}}, f
            )

        result = detect_resume_point(tmp_path, ["checkpoint_1", "checkpoint_2"])

        assert result is not None
        assert result.resume_from_checkpoint == "checkpoint_2"
        assert result.completed_checkpoints == ["checkpoint_1"]


class TestAggregatePriorUsage:
    """Tests for _aggregate_prior_usage function."""

    def test_aggregates_usage_from_multiple_checkpoints(
        self, tmp_path: Path
    ) -> None:
        """Correctly sums usage from multiple checkpoint results."""
        # Create inference results for two checkpoints
        for i in range(1, 3):
            checkpoint_dir = tmp_path / f"checkpoint_{i}"
            checkpoint_dir.mkdir()
            result = {
                "usage": {
                    "cost": float(i),
                    "steps": i * 10,
                    "net_tokens": {
                        "input": i * 100,
                        "output": i * 50,
                    },
                }
            }
            with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
                json.dump(result, f)

        usage = _aggregate_prior_usage(
            tmp_path, ["checkpoint_1", "checkpoint_2"]
        )

        assert usage.cost == 3.0  # 1 + 2
        assert usage.steps == 30  # 10 + 20
        assert usage.net_tokens.input == 300  # 100 + 200
        assert usage.net_tokens.output == 150  # 50 + 100

    def test_handles_missing_inference_result(self, tmp_path: Path) -> None:
        """Skips checkpoints without inference results."""
        # Only create result for checkpoint_2
        checkpoint_dir = tmp_path / "checkpoint_2"
        checkpoint_dir.mkdir()
        result = {"usage": {"cost": 1.5, "steps": 15}}
        with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(result, f)

        usage = _aggregate_prior_usage(
            tmp_path, ["checkpoint_1", "checkpoint_2"]
        )

        assert usage.cost == 1.5
        assert usage.steps == 15

    def test_handles_invalid_json(self, tmp_path: Path) -> None:
        """Skips checkpoints with invalid JSON."""
        checkpoint_dir = tmp_path / "checkpoint_1"
        checkpoint_dir.mkdir()
        with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            f.write("not valid json")

        usage = _aggregate_prior_usage(tmp_path, ["checkpoint_1"])

        assert usage.cost == 0.0
        assert usage.steps == 0

    def test_handles_missing_usage_fields(self, tmp_path: Path) -> None:
        """Handles inference results with missing usage fields."""
        checkpoint_dir = tmp_path / "checkpoint_1"
        checkpoint_dir.mkdir()
        result = {"usage": {"cost": 1.0}}  # missing steps and tokens
        with (checkpoint_dir / INFERENCE_RESULT_FILENAME).open("w") as f:
            json.dump(result, f)

        usage = _aggregate_prior_usage(tmp_path, ["checkpoint_1"])

        assert usage.cost == 1.0
        assert usage.steps == 0
        assert usage.net_tokens.input == 0


class TestMetricsTrackerOnResume:
    """Tests for MetricsTracker behavior during resume.

    When resuming a run, completed checkpoints are skipped but their usage
    should still be accumulated in the MetricsTracker via finish_checkpoint().
    """

    def test_finish_checkpoint_accumulates_usage(self) -> None:
        """Verify finish_checkpoint correctly accumulates usage from summaries.

        This tests the component used when loading existing checkpoint summaries
        during resume - the metrics tracker should accumulate usage from each
        skipped checkpoint's saved summary.
        """
        now = datetime.now()
        tracker = MetricsTracker(
            current_checkpoint="checkpoint_1",
            usage=UsageTracker(cost=0.0, steps=0),
            started=now,
            checkpoint_started=now,
        )

        # Simulate loading a completed checkpoint's usage
        checkpoint_1_usage = UsageTracker(
            cost=1.5,
            steps=10,
            net_tokens=TokenUsage(input=100, output=50),
        )
        tracker.finish_checkpoint(checkpoint_1_usage)

        assert tracker.usage.cost == 1.5
        assert tracker.usage.steps == 10
        assert tracker.usage.net_tokens.input == 100
        assert tracker.usage.net_tokens.output == 50

    def test_finish_checkpoint_accumulates_multiple_checkpoints(self) -> None:
        """Verify multiple finish_checkpoint calls accumulate correctly.

        When resuming after multiple completed checkpoints, each checkpoint's
        usage should be added to the running total.
        """
        now = datetime.now()
        tracker = MetricsTracker(
            current_checkpoint="resuming",
            usage=UsageTracker(cost=0.0, steps=0),
            started=now,
            checkpoint_started=now,
        )

        # Simulate loading multiple completed checkpoints
        tracker.finish_checkpoint(
            UsageTracker(
                cost=1.0,
                steps=5,
                net_tokens=TokenUsage(input=100, output=50),
            )
        )
        tracker.finish_checkpoint(
            UsageTracker(
                cost=2.0,
                steps=15,
                net_tokens=TokenUsage(input=200, output=100),
            )
        )

        assert tracker.usage.cost == 3.0
        assert tracker.usage.steps == 20
        assert tracker.usage.net_tokens.input == 300
        assert tracker.usage.net_tokens.output == 150

    def test_finish_checkpoint_with_prior_usage(self) -> None:
        """Verify finish_checkpoint works when tracker has prior usage.

        When resuming, the MetricsTracker may be initialized with prior_usage.
        Calling finish_checkpoint should add to existing values.
        """
        now = datetime.now()
        # Initialize with prior usage (as happens during resume)
        tracker = MetricsTracker(
            current_checkpoint="checkpoint_2",
            usage=UsageTracker(
                cost=5.0,
                steps=50,
                net_tokens=TokenUsage(input=500, output=250),
            ),
            started=now,
            checkpoint_started=now,
        )

        # Add usage from a newly completed checkpoint
        tracker.finish_checkpoint(
            UsageTracker(
                cost=1.0,
                steps=10,
                net_tokens=TokenUsage(input=100, output=50),
            )
        )

        assert tracker.usage.cost == 6.0
        assert tracker.usage.steps == 60
        assert tracker.usage.net_tokens.input == 600
        assert tracker.usage.net_tokens.output == 300

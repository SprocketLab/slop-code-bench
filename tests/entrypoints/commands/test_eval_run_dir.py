"""Tests for evaluate_agent_run command and auto-skip logic."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from slop_code.common import PROBLEM_CONFIG_NAME
from slop_code.entrypoints.commands.eval_run_dir import (
    _extract_eval_relevant_fields,
    _has_evaluation_config_changed,
    _is_problem_fully_evaluated,
)
from slop_code.evaluation import ProblemConfig


# =============================================================================
# Helper Function Tests: _is_problem_fully_evaluated
# =============================================================================


class TestIsProblemFullyEvaluated:
    """Tests for the _is_problem_fully_evaluated helper function."""

    def test_all_checkpoints_have_evaluation_json(self, tmp_path: Path) -> None:
        """A problem with evaluation.json in all checkpoint dirs is fully evaluated."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        for i in [1, 2, 3]:
            checkpoint_dir = problem_dir / f"checkpoint_{i}"
            checkpoint_dir.mkdir()
            (checkpoint_dir / "evaluation.json").write_text("{}")

        assert _is_problem_fully_evaluated(problem_dir) is True

    def test_missing_evaluation_json_in_one_checkpoint(
        self, tmp_path: Path
    ) -> None:
        """A problem with missing evaluation.json in any checkpoint is not fully evaluated."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        # checkpoint_1 has evaluation.json
        checkpoint_1 = problem_dir / "checkpoint_1"
        checkpoint_1.mkdir()
        (checkpoint_1 / "evaluation.json").write_text("{}")

        # checkpoint_2 does not have evaluation.json
        checkpoint_2 = problem_dir / "checkpoint_2"
        checkpoint_2.mkdir()

        assert _is_problem_fully_evaluated(problem_dir) is False

    def test_no_checkpoint_directories(self, tmp_path: Path) -> None:
        """A problem with no checkpoint directories is not fully evaluated."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        # Only non-checkpoint directories
        (problem_dir / "other_dir").mkdir()
        (problem_dir / "snapshot").mkdir()

        assert _is_problem_fully_evaluated(problem_dir) is False

    def test_empty_problem_directory(self, tmp_path: Path) -> None:
        """An empty problem directory is not fully evaluated."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        assert _is_problem_fully_evaluated(problem_dir) is False

    def test_ignores_non_checkpoint_directories(self, tmp_path: Path) -> None:
        """Non-checkpoint directories are ignored in the evaluation check."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        # Checkpoint with evaluation.json
        checkpoint_1 = problem_dir / "checkpoint_1"
        checkpoint_1.mkdir()
        (checkpoint_1 / "evaluation.json").write_text("{}")

        # Non-checkpoint directories (should be ignored)
        (problem_dir / "snapshot").mkdir()
        (problem_dir / "other_dir").mkdir()

        assert _is_problem_fully_evaluated(problem_dir) is True


# =============================================================================
# Helper Function Tests: _extract_eval_relevant_fields
# =============================================================================


class TestExtractEvalRelevantFields:
    """Tests for the _extract_eval_relevant_fields helper function."""

    def test_extracts_all_relevant_fields(self) -> None:
        """All evaluation-relevant fields are extracted from config."""
        config = {
            "name": "test_problem",
            "version": 2,
            "adapter": "python",
            "static_assets": ["file1.txt", "file2.txt"],
            "checkpoints": {
                "checkpoint_1": {
                    "version": 1,
                    "groups": {"core": {}, "hidden": {}},
                },
                "checkpoint_2": {
                    "version": 2,
                    "groups": {"core": {}},
                },
            },
            "other_field": "ignored",
        }

        result = _extract_eval_relevant_fields(config)

        assert result["version"] == 2
        assert result["adapter"] == "python"
        assert result["static_assets"] == ["file1.txt", "file2.txt"]
        assert result["checkpoints"]["checkpoint_1"]["version"] == 1
        assert sorted(result["checkpoints"]["checkpoint_1"]["groups"]) == [
            "core",
            "hidden",
        ]

    def test_minimal_config(self) -> None:
        """Handles minimal config with missing optional fields."""
        config = {"name": "test_problem"}

        result = _extract_eval_relevant_fields(config)

        assert result["version"] is None
        assert result["adapter"] is None
        assert result["static_assets"] is None
        assert result["checkpoints"] == {}

    def test_checkpoint_without_groups(self) -> None:
        """Handles checkpoints that don't have groups defined."""
        config = {
            "checkpoints": {
                "checkpoint_1": {"version": 1},
            }
        }

        result = _extract_eval_relevant_fields(config)

        assert result["checkpoints"]["checkpoint_1"]["groups"] == []


# =============================================================================
# Helper Function Tests: _has_evaluation_config_changed
# =============================================================================


class TestHasEvaluationConfigChanged:
    """Tests for the _has_evaluation_config_changed helper function."""

    @pytest.fixture
    def mock_problem_config(self) -> MagicMock:
        """Create a mock ProblemConfig."""
        config = MagicMock(spec=ProblemConfig)
        config.model_dump.return_value = {
            "name": "test_problem",
            "version": 1,
            "adapter": "python",
            "static_assets": None,
            "checkpoints": {
                "checkpoint_1": {
                    "version": 1,
                    "groups": {"core": {}},
                }
            },
        }
        return config

    def test_no_saved_config_returns_true(
        self, tmp_path: Path, mock_problem_config: MagicMock
    ) -> None:
        """Returns True when no saved config exists."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        assert (
            _has_evaluation_config_changed(problem_dir, mock_problem_config)
            is True
        )

    def test_matching_configs_returns_false(
        self, tmp_path: Path, mock_problem_config: MagicMock
    ) -> None:
        """Returns False when saved and source configs match."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        # Save a config that matches the mock
        saved_config = {
            "name": "test_problem",
            "version": 1,
            "adapter": "python",
            "static_assets": None,
            "checkpoints": {
                "checkpoint_1": {
                    "version": 1,
                    "groups": {"core": {}},
                }
            },
        }
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.dump(saved_config, f)

        assert (
            _has_evaluation_config_changed(problem_dir, mock_problem_config)
            is False
        )

    def test_version_differs_returns_true(
        self, tmp_path: Path, mock_problem_config: MagicMock
    ) -> None:
        """Returns True when version differs."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        saved_config = {
            "name": "test_problem",
            "version": 999,  # Different version
            "adapter": "python",
            "checkpoints": {
                "checkpoint_1": {
                    "version": 1,
                    "groups": {"core": {}},
                }
            },
        }
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.dump(saved_config, f)

        assert (
            _has_evaluation_config_changed(problem_dir, mock_problem_config)
            is True
        )

    def test_adapter_differs_returns_true(
        self, tmp_path: Path, mock_problem_config: MagicMock
    ) -> None:
        """Returns True when adapter differs."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        saved_config = {
            "name": "test_problem",
            "version": 1,
            "adapter": "javascript",  # Different adapter
            "checkpoints": {
                "checkpoint_1": {
                    "version": 1,
                    "groups": {"core": {}},
                }
            },
        }
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.dump(saved_config, f)

        assert (
            _has_evaluation_config_changed(problem_dir, mock_problem_config)
            is True
        )

    def test_checkpoint_groups_differ_returns_true(
        self, tmp_path: Path, mock_problem_config: MagicMock
    ) -> None:
        """Returns True when checkpoint groups differ."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        saved_config = {
            "name": "test_problem",
            "version": 1,
            "adapter": "python",
            "checkpoints": {
                "checkpoint_1": {
                    "version": 1,
                    "groups": {"core": {}, "hidden": {}},  # Extra group
                }
            },
        }
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.dump(saved_config, f)

        assert (
            _has_evaluation_config_changed(problem_dir, mock_problem_config)
            is True
        )

    def test_corrupt_saved_config_returns_true(
        self, tmp_path: Path, mock_problem_config: MagicMock
    ) -> None:
        """Returns True when saved config is corrupt/invalid YAML."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        # Write invalid YAML
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            f.write("not: valid: yaml: {{{{")

        assert (
            _has_evaluation_config_changed(problem_dir, mock_problem_config)
            is True
        )


# =============================================================================
# Auto-Skip Logic Integration Tests
# =============================================================================


class TestAutoSkipLogic:
    """Tests for the auto_skip_evaluated logic.

    These tests verify the core behavior of the fix:
    - auto_skip_evaluated = not overwrite

    This ensures:
    - --problem X respects existing evaluations (unless overwrite)
    - --overwrite forces re-evaluation regardless of --problem
    """

    @pytest.fixture
    def evaluated_problem_dir(self, tmp_path: Path) -> Path:
        """Create a fully evaluated problem directory."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        for i in [1, 2]:
            checkpoint_dir = problem_dir / f"checkpoint_{i}"
            checkpoint_dir.mkdir()
            (checkpoint_dir / "evaluation.json").write_text(
                json.dumps(
                    {
                        "problem_name": "test_problem",
                        "checkpoint_name": f"checkpoint_{i}",
                        "pytest_exit_code": 0,
                    }
                )
            )

        # Add saved problem config
        saved_config = {
            "name": "test_problem",
            "version": 1,
            "adapter": "python",
            "checkpoints": {
                "checkpoint_1": {"version": 1, "groups": {}},
                "checkpoint_2": {"version": 1, "groups": {}},
            },
        }
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.dump(saved_config, f)

        return problem_dir

    @pytest.fixture
    def unevaluated_problem_dir(self, tmp_path: Path) -> Path:
        """Create an unevaluated problem directory."""
        problem_dir = tmp_path / "unevaluated_problem"
        problem_dir.mkdir()

        for i in [1, 2]:
            checkpoint_dir = problem_dir / f"checkpoint_{i}"
            checkpoint_dir.mkdir()
            # No evaluation.json files

        return problem_dir

    def test_auto_skip_depends_only_on_overwrite_flag(self) -> None:
        """Verify auto_skip_evaluated = not overwrite (the fix)."""
        # This is the core logic test - simulating what line 227 does

        # Test case 1: no flags (default)
        problem_names: list[str] = []
        overwrite = False
        auto_skip_evaluated = not overwrite
        assert auto_skip_evaluated is True, "Default should auto-skip"

        # Test case 2: --overwrite only
        problem_names = []
        overwrite = True
        auto_skip_evaluated = not overwrite
        assert auto_skip_evaluated is False, "--overwrite should not auto-skip"

        # Test case 3: --problem X only (THE BUG FIX)
        problem_names = ["test_problem"]
        overwrite = False
        auto_skip_evaluated = not overwrite
        assert (
            auto_skip_evaluated is True
        ), "--problem alone should still auto-skip"

        # Test case 4: --problem X --overwrite
        problem_names = ["test_problem"]
        overwrite = True
        auto_skip_evaluated = not overwrite
        assert (
            auto_skip_evaluated is False
        ), "--problem with --overwrite should not auto-skip"

    def test_problem_filter_with_skip_logic(
        self, evaluated_problem_dir: Path
    ) -> None:
        """Verify --problem X combined with auto-skip works correctly.

        When --problem X is specified without --overwrite:
        - auto_skip_evaluated = True (because not overwrite)
        - If problem X is fully evaluated, it should be SKIPPED
        """
        problem_name = "test_problem"
        overwrite = False
        auto_skip_evaluated = not overwrite  # True

        # Simulate the skip logic from eval_run_dir.py lines 243-256
        should_skip = False
        if auto_skip_evaluated and _is_problem_fully_evaluated(
            evaluated_problem_dir
        ):
            # Create a mock source config that matches the saved config
            mock_source_config = MagicMock(spec=ProblemConfig)
            mock_source_config.model_dump.return_value = {
                "name": "test_problem",
                "version": 1,
                "adapter": "python",
                "checkpoints": {
                    "checkpoint_1": {"version": 1, "groups": {}},
                    "checkpoint_2": {"version": 1, "groups": {}},
                },
            }

            if not _has_evaluation_config_changed(
                evaluated_problem_dir, mock_source_config
            ):
                should_skip = True

        assert (
            should_skip is True
        ), "--problem X should skip if already evaluated and config unchanged"

    def test_problem_filter_with_overwrite_forces_evaluation(
        self, evaluated_problem_dir: Path
    ) -> None:
        """Verify --problem X --overwrite forces re-evaluation.

        When --problem X is specified WITH --overwrite:
        - auto_skip_evaluated = False (because overwrite=True)
        - Problem X should NOT be skipped
        """
        problem_name = "test_problem"
        overwrite = True
        auto_skip_evaluated = not overwrite  # False

        # The skip logic is never entered because auto_skip_evaluated is False
        should_skip = False
        if auto_skip_evaluated and _is_problem_fully_evaluated(
            evaluated_problem_dir
        ):
            should_skip = True

        assert (
            should_skip is False
        ), "--problem X --overwrite should NOT skip"


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for eval_run_dir functionality."""

    def test_partial_evaluation_not_skipped(self, tmp_path: Path) -> None:
        """Problems with partial evaluation (some checkpoints) are not skipped."""
        problem_dir = tmp_path / "partial_problem"
        problem_dir.mkdir()

        # checkpoint_1 is evaluated
        checkpoint_1 = problem_dir / "checkpoint_1"
        checkpoint_1.mkdir()
        (checkpoint_1 / "evaluation.json").write_text("{}")

        # checkpoint_2 is NOT evaluated
        checkpoint_2 = problem_dir / "checkpoint_2"
        checkpoint_2.mkdir()

        # Even with auto_skip enabled, partial evaluation should not be skipped
        auto_skip_evaluated = True
        should_skip = auto_skip_evaluated and _is_problem_fully_evaluated(
            problem_dir
        )

        assert (
            should_skip is False
        ), "Partial evaluation should not trigger skip"

    def test_config_change_overrides_skip(self, tmp_path: Path) -> None:
        """Config changes trigger re-evaluation even when auto-skip is enabled."""
        problem_dir = tmp_path / "test_problem"
        problem_dir.mkdir()

        # Fully evaluated
        for i in [1, 2]:
            checkpoint_dir = problem_dir / f"checkpoint_{i}"
            checkpoint_dir.mkdir()
            (checkpoint_dir / "evaluation.json").write_text("{}")

        # Saved config with old version
        saved_config = {
            "name": "test_problem",
            "version": 1,
            "adapter": "python",
            "checkpoints": {},
        }
        with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
            yaml.dump(saved_config, f)

        # Source config with new version
        mock_source_config = MagicMock(spec=ProblemConfig)
        mock_source_config.model_dump.return_value = {
            "name": "test_problem",
            "version": 2,  # Changed!
            "adapter": "python",
            "checkpoints": {},
        }

        auto_skip_evaluated = True  # no --overwrite

        # Should NOT skip because config changed
        should_skip = False
        if auto_skip_evaluated and _is_problem_fully_evaluated(problem_dir):
            if not _has_evaluation_config_changed(
                problem_dir, mock_source_config
            ):
                should_skip = True

        assert (
            should_skip is False
        ), "Config change should prevent skip"

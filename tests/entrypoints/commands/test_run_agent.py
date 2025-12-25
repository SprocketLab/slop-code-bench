"""Tests for run_agent command helper functions."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
import yaml

from slop_code.entrypoints.commands.run_agent import (
    _build_cli_flags,
    _create_task_config,
    _discover_problems,
    _get_nested,
    _handle_early_completion,
    _handle_resume_validation,
    _load_and_validate_run_config,
    _resolve_output_directory,
    _resolve_problem_names,
    _validate_problem_paths,
    _validate_resume_config,
)


class TestGetNested:
    """Tests for _get_nested helper function."""

    def test_simple_key(self):
        """Test getting a simple top-level key."""
        data = {"name": "value"}
        assert _get_nested(data, "name") == "value"

    def test_nested_key(self):
        """Test getting a nested key with dot notation."""
        data = {"model": {"provider": "anthropic", "name": "opus-4"}}
        assert _get_nested(data, "model.provider") == "anthropic"
        assert _get_nested(data, "model.name") == "opus-4"

    def test_deeply_nested_key(self):
        """Test getting a deeply nested key."""
        data = {"level1": {"level2": {"level3": "deep_value"}}}
        assert _get_nested(data, "level1.level2.level3") == "deep_value"

    def test_missing_key(self):
        """Test that missing keys return None."""
        data = {"name": "value"}
        assert _get_nested(data, "missing") is None
        assert _get_nested(data, "missing.nested") is None

    def test_missing_nested_key(self):
        """Test that missing nested keys return None."""
        data = {"model": {"provider": "anthropic"}}
        assert _get_nested(data, "model.name") is None

    def test_non_dict_intermediate(self):
        """Test that non-dict intermediate values return None."""
        data = {"model": "string_value"}
        assert _get_nested(data, "model.provider") is None

    def test_empty_dict(self):
        """Test with empty dictionary."""
        assert _get_nested({}, "any.key") is None


class TestBuildCliFlags:
    """Tests for _build_cli_flags helper function."""

    def test_no_overrides(self):
        """Test with no overrides provided."""
        result = _build_cli_flags(None, None, None, None)
        assert result == {}

    def test_agent_override(self):
        """Test agent path override."""
        result = _build_cli_flags("my_agent", None, None, None)
        assert result == {"agent": "my_agent"}

    def test_environment_override(self):
        """Test environment path override."""
        result = _build_cli_flags(None, "my_env.yaml", None, None)
        assert result == {"environment": "my_env.yaml"}

    def test_prompt_override(self):
        """Test prompt path override."""
        result = _build_cli_flags(None, None, "my_prompt.jinja", None)
        assert result == {"prompt": "my_prompt.jinja"}

    def test_model_override(self):
        """Test model override parsing."""
        # Use a model that exists in the catalog
        result = _build_cli_flags(None, None, None, "anthropic/sonnet-4.5")
        assert "model" in result
        model = result["model"]
        assert model["provider"] == "anthropic"
        assert model["name"] == "sonnet-4.5"

    def test_all_overrides(self):
        """Test all overrides provided."""
        result = _build_cli_flags(
            "agent.yaml", "env.yaml", "prompt.jinja", "anthropic/sonnet-4.5"
        )
        assert result["agent"] == "agent.yaml"
        assert result["environment"] == "env.yaml"
        assert result["prompt"] == "prompt.jinja"
        assert "model" in result
        model = result["model"]
        assert model["provider"] == "anthropic"
        assert model["name"] == "sonnet-4.5"

    def test_invalid_model_format_raises(self):
        """Test error on invalid model format."""
        with pytest.raises(ValueError):
            _build_cli_flags(None, None, None, "invalid-model-format")


class TestLoadAndValidateRunConfig:
    """Tests for _load_and_validate_run_config helper function."""

    def test_defaults_only(self):
        """Test loading with all defaults."""
        result = _load_and_validate_run_config(None, {}, None)
        assert result.model.provider == "anthropic"
        assert result.model.name == "sonnet-4.5"

    def test_config_file_not_found(self, tmp_path):
        """Test error when config file doesn't exist."""
        with pytest.raises(typer.Exit) as excinfo:
            _load_and_validate_run_config(tmp_path / "missing.yaml", {}, None)
        assert excinfo.value.exit_code == 1

    def test_cli_flags_override(self):
        """Test CLI flags override defaults."""
        cli_flags = {
            "model": {"provider": "openai", "name": "gpt-4"},
        }
        result = _load_and_validate_run_config(None, cli_flags, None)
        assert result.model.provider == "openai"
        assert result.model.name == "gpt-4"

    def test_config_file_loading(self, tmp_path):
        """Test loading from config file."""
        config_file = tmp_path / "run_config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "model": {"provider": "google", "name": "gemini-pro"},
                }
            )
        )
        result = _load_and_validate_run_config(config_file, {}, None)
        assert result.model.provider == "google"
        assert result.model.name == "gemini-pro"


class TestResolveProblemNames:
    """Tests for _resolve_problem_names helper function."""

    def test_cli_takes_precedence(self):
        """Test CLI problems override config."""
        result = _resolve_problem_names(["cli_prob"], ["config_prob"])
        assert result == ["cli_prob"]

    def test_config_used_when_no_cli(self):
        """Test config problems used when no CLI."""
        result = _resolve_problem_names([], ["config_prob"])
        assert result == ["config_prob"]

    def test_empty_returns_empty(self):
        """Test empty inputs return empty list."""
        result = _resolve_problem_names([], [])
        assert result == []

    def test_multiple_cli_problems(self):
        """Test multiple CLI problems."""
        result = _resolve_problem_names(["prob1", "prob2"], ["config_prob"])
        assert result == ["prob1", "prob2"]

    def test_multiple_config_problems(self):
        """Test multiple config problems."""
        result = _resolve_problem_names([], ["prob1", "prob2", "prob3"])
        assert result == ["prob1", "prob2", "prob3"]


class TestResolveOutputDirectory:
    """Tests for _resolve_output_directory helper function."""

    def test_cli_override_takes_precedence(self, tmp_path):
        """Test CLI output path overrides config."""
        cli_path = str(tmp_path / "cli_out")
        result, existed = _resolve_output_directory(cli_path, "config_out", debug=False)
        assert result == Path(cli_path)

    def test_config_used_when_no_cli(self, tmp_path):
        """Test config output path used when no CLI override."""
        config_path = str(tmp_path / "config_out")
        result, existed = _resolve_output_directory(None, config_path, debug=False)
        assert result == Path(config_path)

    def test_debug_prefix_added(self, tmp_path):
        """Test DEBUG_ prefix in debug mode."""
        result, existed = _resolve_output_directory(
            None, str(tmp_path / "run_123"), debug=True
        )
        assert "DEBUG_" in str(result)

    def test_debug_prefix_with_nested_path(self):
        """Test DEBUG_ prefix with nested path."""
        result, existed = _resolve_output_directory(
            None, "outputs/run_123", debug=True
        )
        assert "outputs/DEBUG_run_123" in str(result)

    def test_debug_prefix_with_simple_path(self):
        """Test DEBUG_ prefix with simple path."""
        result, existed = _resolve_output_directory(None, "run_123", debug=True)
        assert str(result) == "DEBUG_run_123"

    def test_preexisted_flag_true(self, tmp_path):
        """Test preexisted flag correctly set when directory exists."""
        existing_dir = tmp_path / "exists"
        existing_dir.mkdir()
        result, existed = _resolve_output_directory(
            str(existing_dir), "default", debug=False
        )
        assert existed is True

    def test_preexisted_flag_false(self, tmp_path):
        """Test preexisted flag correctly set when directory doesn't exist."""
        result, existed = _resolve_output_directory(
            str(tmp_path / "new"), "default", debug=False
        )
        assert existed is False

    def test_directory_created(self, tmp_path):
        """Test that directory is created."""
        new_path = tmp_path / "new_dir"
        result, existed = _resolve_output_directory(
            str(new_path), "default", debug=False
        )
        assert result.exists()


class TestValidateResumeConfig:
    """Tests for _validate_resume_config function."""

    @pytest.fixture
    def mock_run_cfg(self):
        """Create a mock ResolvedRunConfig."""
        cfg = MagicMock()
        cfg.model_dump.return_value = {
            "model": {"provider": "anthropic", "name": "opus-4"},
            "agent": {"type": "claude_code"},
            "thinking": "low",
            "prompt_path": "/path/to/prompt.jinja",
        }
        return cfg

    @pytest.fixture
    def mock_env_spec(self):
        """Create a mock environment spec."""
        spec = MagicMock()
        spec.model_dump.return_value = {
            "type": "docker",
            "name": "python3.12",
            "docker": {"image": "python:3.12"},
        }
        return spec

    def test_no_saved_config(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test that missing config.yaml allows resume."""
        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert result == []

    def test_matching_config(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test that matching config returns no mismatches."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "anthropic", "name": "opus-4"},
                    "agent": {"type": "claude_code"},
                    "thinking": "low",
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )
        (tmp_path / "environment.yaml").write_text(
            yaml.dump(
                {
                    "type": "docker",
                    "name": "python3.12",
                    "docker": {"image": "python:3.12"},
                }
            )
        )
        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert result == []

    def test_model_provider_mismatch(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test detection of model provider mismatch."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "openai", "name": "opus-4"},
                    "agent": {"type": "claude_code"},
                    "thinking": "low",
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )
        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 1
        assert result[0][0] == "model.provider"
        assert result[0][1] == "openai"
        assert result[0][2] == "anthropic"


class TestHandleResumeValidation:
    """Tests for _handle_resume_validation helper function."""

    @pytest.fixture
    def mock_run_cfg(self):
        """Create a mock ResolvedRunConfig."""
        cfg = MagicMock()
        cfg.model_dump.return_value = {
            "model": {"provider": "anthropic", "name": "opus-4"},
            "agent": {"type": "claude_code"},
            "thinking": "low",
            "prompt_path": "/path/to/prompt.jinja",
        }
        return cfg

    @pytest.fixture
    def mock_env_spec(self):
        """Create a mock environment spec."""
        spec = MagicMock()
        spec.model_dump.return_value = {
            "type": "docker",
            "name": "python3.12",
            "docker": {"image": "python:3.12"},
        }
        return spec

    def test_no_exit_when_not_resuming(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test no exit when resume=False."""
        # Should not raise
        _handle_resume_validation(
            tmp_path, mock_run_cfg, mock_env_spec, resume=False, overwrite=False
        )

    def test_no_exit_when_overwrite(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test no exit when overwrite=True."""
        # Write mismatched config
        (tmp_path / "config.yaml").write_text(
            yaml.dump({"model": {"provider": "openai", "name": "gpt-4"}})
        )
        # Should not raise because overwrite=True
        _handle_resume_validation(
            tmp_path, mock_run_cfg, mock_env_spec, resume=True, overwrite=True
        )

    def test_exits_on_mismatch(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test exits when config mismatches detected."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "openai", "name": "gpt-4"},
                    "agent": {"type": "claude_code"},
                    "thinking": "low",
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )
        with pytest.raises(typer.Exit) as excinfo:
            _handle_resume_validation(
                tmp_path, mock_run_cfg, mock_env_spec, resume=True, overwrite=False
            )
        assert excinfo.value.exit_code == 1

    def test_no_exit_when_config_matches(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test no exit when config matches."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "anthropic", "name": "opus-4"},
                    "agent": {"type": "claude_code"},
                    "thinking": "low",
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )
        (tmp_path / "environment.yaml").write_text(
            yaml.dump(
                {
                    "type": "docker",
                    "name": "python3.12",
                    "docker": {"image": "python:3.12"},
                }
            )
        )
        # Should not raise
        _handle_resume_validation(
            tmp_path, mock_run_cfg, mock_env_spec, resume=True, overwrite=False
        )


class TestHandleEarlyCompletion:
    """Tests for _handle_early_completion helper function."""

    def test_returns_true_when_nothing_to_do(self, tmp_path):
        """Test returns True when no problems to run."""
        console = MagicMock()
        result = _handle_early_completion(
            problem_names=[],  # Empty - nothing to do
            run_dir=tmp_path,
            problems_base_path=tmp_path,
            console=console,
            evaluate=False,
            requested=["prob1"],
        )
        assert result is True

    def test_returns_false_when_work_remains(self, tmp_path):
        """Test returns False when problems need running."""
        console = MagicMock()
        result = _handle_early_completion(
            problem_names=["prob1"],
            run_dir=tmp_path,
            problems_base_path=tmp_path,
            console=console,
            evaluate=False,
            requested=["prob1"],
        )
        assert result is False

    @patch("slop_code.entrypoints.commands.run_agent._create_checkpoint_results_and_summary")
    def test_calls_summary_when_evaluate_true(self, mock_summary, tmp_path):
        """Test summary is generated when evaluate=True and nothing to do."""
        console = MagicMock()
        result = _handle_early_completion(
            problem_names=[],
            run_dir=tmp_path,
            problems_base_path=tmp_path,
            console=console,
            evaluate=True,
            requested=["prob1"],
        )
        assert result is True
        mock_summary.assert_called_once()

    @patch("slop_code.entrypoints.commands.run_agent._create_checkpoint_results_and_summary")
    def test_no_summary_when_evaluate_false(self, mock_summary, tmp_path):
        """Test no summary when evaluate=False."""
        console = MagicMock()
        result = _handle_early_completion(
            problem_names=[],
            run_dir=tmp_path,
            problems_base_path=tmp_path,
            console=console,
            evaluate=False,
            requested=["prob1"],
        )
        assert result is True
        mock_summary.assert_not_called()


class TestCreateTaskConfig:
    """Tests for _create_task_config helper function."""

    def test_creates_valid_config(self):
        """Test task config creation with all parameters."""
        from slop_code.entrypoints import problem_runner

        mock_run_cfg = MagicMock()
        mock_run_cfg.thinking = "low"
        mock_run_cfg.thinking_max_tokens = None
        mock_run_cfg.prompt_content = "template content"
        mock_run_cfg.pass_policy = MagicMock()
        mock_run_cfg.one_shot = MagicMock()

        result = _create_task_config(
            problem_base_path=Path("/problems"),
            run_dir=Path("/output"),
            env_spec=MagicMock(),
            agent_config=MagicMock(),
            model_def=MagicMock(),
            credential=MagicMock(),
            run_cfg=mock_run_cfg,
            seed=42,
            verbosity=1,
            debug=False,
            evaluate=True,
            live_progress=True,
            image_name="test:image",
            resume=False,
        )

        assert isinstance(result, problem_runner.RunTaskConfig)
        assert result.run_dir == Path("/output")
        assert result.image == "test:image"
        assert result.seed == 42
        assert result.debug is False
        assert result.disable_evaluation is False
        assert result.resume is False

    def test_disable_evaluation_flag(self):
        """Test disable_evaluation is inverse of evaluate."""
        mock_run_cfg = MagicMock()
        mock_run_cfg.thinking = "low"
        mock_run_cfg.thinking_max_tokens = None
        mock_run_cfg.prompt_content = "template"
        mock_run_cfg.pass_policy = MagicMock()
        mock_run_cfg.one_shot = MagicMock()

        result = _create_task_config(
            problem_base_path=Path("/problems"),
            run_dir=Path("/output"),
            env_spec=MagicMock(),
            agent_config=MagicMock(),
            model_def=MagicMock(),
            credential=MagicMock(),
            run_cfg=mock_run_cfg,
            seed=None,
            verbosity=0,
            debug=True,
            evaluate=False,  # evaluate=False
            live_progress=False,
            image_name="",
            resume=True,
        )

        assert result.disable_evaluation is True  # Should be inverse
        assert result.debug is True
        assert result.resume is True


class TestDiscoverProblems:
    """Tests for _discover_problems helper function."""

    def test_discovers_valid_problems(self, tmp_path):
        """Test discovery of valid problems."""
        prob_dir = tmp_path / "test_problem"
        prob_dir.mkdir()
        (prob_dir / "config.yaml").write_text(
            yaml.dump(
                {
                    "name": "test_problem",
                    "version": 1,
                    "description": "Test problem",
                    "category": "test",
                    "entry_file": "main.py",
                    "checkpoints": {"checkpoint_1": {"version": 1, "order": 1}},
                }
            )
        )
        result = _discover_problems(tmp_path)
        assert "test_problem" in result

    def test_skips_not_set_category(self, tmp_path):
        """Test problems with NOT_SET category are skipped."""
        prob_dir = tmp_path / "not_set_prob"
        prob_dir.mkdir()
        (prob_dir / "config.yaml").write_text(
            yaml.dump(
                {
                    "name": "not_set_prob",
                    "category": "NOT_SET",
                    "checkpoints": {"checkpoint_1": {"order": 1}},
                }
            )
        )
        result = _discover_problems(tmp_path)
        assert "not_set_prob" not in result

    def test_skips_invalid_config(self, tmp_path):
        """Test problems with invalid config are skipped."""
        prob_dir = tmp_path / "invalid_prob"
        prob_dir.mkdir()
        (prob_dir / "config.yaml").write_text("invalid: yaml: [")
        result = _discover_problems(tmp_path)
        assert "invalid_prob" not in result

    def test_skips_no_checkpoints(self, tmp_path):
        """Test problems with no checkpoints are skipped."""
        prob_dir = tmp_path / "no_checkpoints"
        prob_dir.mkdir()
        (prob_dir / "config.yaml").write_text(
            yaml.dump(
                {
                    "name": "no_checkpoints",
                    "category": "test",
                    "checkpoints": {},
                }
            )
        )
        result = _discover_problems(tmp_path)
        assert "no_checkpoints" not in result

    def test_multiple_problems(self, tmp_path):
        """Test discovering multiple valid problems."""
        for name in ["prob_a", "prob_b", "prob_c"]:
            prob_dir = tmp_path / name
            prob_dir.mkdir()
            (prob_dir / "config.yaml").write_text(
                yaml.dump(
                    {
                        "name": name,
                        "version": 1,
                        "description": f"Test problem {name}",
                        "category": "test",
                        "entry_file": "main.py",
                        "checkpoints": {"checkpoint_1": {"version": 1, "order": 1}},
                    }
                )
            )
        result = _discover_problems(tmp_path)
        assert len(result) == 3
        assert set(result) == {"prob_a", "prob_b", "prob_c"}

    def test_returns_sorted(self, tmp_path):
        """Test that problems are returned sorted."""
        for name in ["zebra", "apple", "mango"]:
            prob_dir = tmp_path / name
            prob_dir.mkdir()
            (prob_dir / "config.yaml").write_text(
                yaml.dump(
                    {
                        "name": name,
                        "version": 1,
                        "description": f"Test problem {name}",
                        "category": "test",
                        "entry_file": "main.py",
                        "checkpoints": {"checkpoint_1": {"version": 1, "order": 1}},
                    }
                )
            )
        result = _discover_problems(tmp_path)
        assert result == ["apple", "mango", "zebra"]


class TestValidateProblemPaths:
    """Tests for _validate_problem_paths helper function."""

    def test_passes_for_existing_paths(self, tmp_path):
        """Test validation passes when paths exist."""
        prob_dir = tmp_path / "exists"
        prob_dir.mkdir()
        # Should not raise
        _validate_problem_paths(["exists"], tmp_path)

    def test_exits_for_missing_path(self, tmp_path):
        """Test exits when path doesn't exist."""
        with pytest.raises(typer.Exit) as excinfo:
            _validate_problem_paths(["missing"], tmp_path)
        assert excinfo.value.exit_code == 1

    def test_multiple_existing_paths(self, tmp_path):
        """Test validation with multiple existing paths."""
        for name in ["prob1", "prob2", "prob3"]:
            (tmp_path / name).mkdir()
        # Should not raise
        _validate_problem_paths(["prob1", "prob2", "prob3"], tmp_path)

    def test_fails_on_first_missing(self, tmp_path):
        """Test validation fails on first missing path."""
        (tmp_path / "exists1").mkdir()
        (tmp_path / "exists2").mkdir()
        with pytest.raises(typer.Exit):
            _validate_problem_paths(["exists1", "missing", "exists2"], tmp_path)

    def test_empty_list_passes(self, tmp_path):
        """Test validation passes with empty list."""
        # Should not raise
        _validate_problem_paths([], tmp_path)

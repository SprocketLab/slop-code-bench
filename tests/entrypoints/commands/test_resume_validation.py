"""Tests for resume configuration validation in run_agent."""

from unittest.mock import MagicMock

import pytest
import yaml

from slop_code.entrypoints.commands.run_agent import _get_nested
from slop_code.entrypoints.commands.run_agent import _validate_resume_config


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
        # Write saved config that matches current
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

    def test_model_provider_mismatch(
        self, tmp_path, mock_run_cfg, mock_env_spec
    ):
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

    def test_model_name_mismatch(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test detection of model name mismatch."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "anthropic", "name": "sonnet-4"},
                    "agent": {"type": "claude_code"},
                    "thinking": "low",
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 1
        assert result[0][0] == "model.name"
        assert result[0][1] == "sonnet-4"
        assert result[0][2] == "opus-4"

    def test_agent_type_mismatch(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test detection of agent type mismatch."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "anthropic", "name": "opus-4"},
                    "agent": {"type": "codex"},
                    "thinking": "low",
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 1
        assert result[0][0] == "agent.type"
        assert result[0][1] == "codex"
        assert result[0][2] == "claude_code"

    def test_thinking_mismatch(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test detection of thinking preset mismatch."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "anthropic", "name": "opus-4"},
                    "agent": {"type": "claude_code"},
                    "thinking": "high",
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 1
        assert result[0][0] == "thinking"
        assert result[0][1] == "high"
        assert result[0][2] == "low"

    def test_prompt_path_mismatch(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test detection of prompt path mismatch."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "anthropic", "name": "opus-4"},
                    "agent": {"type": "claude_code"},
                    "thinking": "low",
                    "prompt_path": "/different/prompt.jinja",
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 1
        assert result[0][0] == "prompt_path"
        assert result[0][1] == "/different/prompt.jinja"
        assert result[0][2] == "/path/to/prompt.jinja"

    def test_environment_type_mismatch(
        self, tmp_path, mock_run_cfg, mock_env_spec
    ):
        """Test detection of environment type mismatch."""
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
            yaml.dump({"type": "local", "name": "local-env"})
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 2
        # Check for type mismatch
        type_mismatch = next(m for m in result if m[0] == "environment.type")
        assert type_mismatch[1] == "local"
        assert type_mismatch[2] == "docker"

    def test_environment_name_mismatch(
        self, tmp_path, mock_run_cfg, mock_env_spec
    ):
        """Test detection of environment name mismatch."""
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
                    "name": "python3.11",
                    "docker": {"image": "python:3.12"},
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 1
        assert result[0][0] == "environment.name"
        assert result[0][1] == "python3.11"
        assert result[0][2] == "python3.12"

    def test_docker_image_mismatch(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test detection of Docker image mismatch."""
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
                    "docker": {"image": "python:3.11"},
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert len(result) == 1
        assert result[0][0] == "environment.docker.image"
        assert result[0][1] == "python:3.11"
        assert result[0][2] == "python:3.12"

    def test_multiple_mismatches(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test detection of multiple mismatches."""
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "openai", "name": "gpt-4"},
                    "agent": {"type": "codex"},
                    "thinking": "high",
                    "prompt_path": "/different/prompt.jinja",
                }
            )
        )
        (tmp_path / "environment.yaml").write_text(
            yaml.dump(
                {
                    "type": "local",
                    "name": "local-env",
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        # Should have mismatches for: provider, name, agent.type, thinking, prompt_path, env.type, env.name
        assert len(result) >= 5

    def test_missing_field_in_saved_config(
        self, tmp_path, mock_run_cfg, mock_env_spec
    ):
        """Test that missing fields in saved config are skipped."""
        # Old config without thinking field
        (tmp_path / "config.yaml").write_text(
            yaml.dump(
                {
                    "model": {"provider": "anthropic", "name": "opus-4"},
                    "agent": {"type": "claude_code"},
                    # no thinking field
                    "prompt_path": "/path/to/prompt.jinja",
                }
            )
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        # Should not report thinking as mismatch since it's missing in saved
        assert not any(m[0] == "thinking" for m in result)

    def test_invalid_yaml_in_config(
        self, tmp_path, mock_run_cfg, mock_env_spec
    ):
        """Test handling of invalid YAML in config file."""
        (tmp_path / "config.yaml").write_text("invalid: yaml: content: [")

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        # Should return empty list on parse error
        assert result == []

    def test_invalid_yaml_in_environment(
        self, tmp_path, mock_run_cfg, mock_env_spec
    ):
        """Test handling of invalid YAML in environment file."""
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
        (tmp_path / "environment.yaml").write_text("invalid: yaml: [")

        # Should still check config.yaml fields, just skip environment
        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert result == []

    def test_empty_config_yaml(self, tmp_path, mock_run_cfg, mock_env_spec):
        """Test handling of empty config.yaml."""
        (tmp_path / "config.yaml").write_text("")

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert result == []

    def test_non_docker_environment(self, tmp_path, mock_run_cfg):
        """Test validation with non-Docker environment."""
        mock_env_spec = MagicMock()
        mock_env_spec.model_dump.return_value = {
            "type": "local",
            "name": "local-env",
        }

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
            yaml.dump({"type": "local", "name": "local-env"})
        )

        result = _validate_resume_config(tmp_path, mock_run_cfg, mock_env_spec)
        assert result == []

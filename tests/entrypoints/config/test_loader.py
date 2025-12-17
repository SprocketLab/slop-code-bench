"""Tests for the config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from slop_code.entrypoints.config.loader import get_package_config_dir
from slop_code.entrypoints.config.loader import load_run_config
from slop_code.entrypoints.config.loader import parse_override
from slop_code.entrypoints.config.loader import resolve_config_path
from slop_code.evaluation import PassPolicy


class TestParseOverride:
    def test_simple_string(self):
        key, value = parse_override("agent=claude_code")
        assert key == "agent"
        assert value == "claude_code"

    def test_nested_key(self):
        key, value = parse_override("model.name=opus-4")
        assert key == "model.name"
        assert value == "opus-4"

    def test_boolean_true(self):
        key, value = parse_override("enabled=true")
        assert key == "enabled"
        assert value is True

    def test_boolean_false(self):
        key, value = parse_override("enabled=false")
        assert key == "enabled"
        assert value is False

    def test_boolean_case_insensitive(self):
        _, value = parse_override("x=TRUE")
        assert value is True
        _, value = parse_override("x=False")
        assert value is False

    def test_integer(self):
        key, value = parse_override("count=42")
        assert key == "count"
        assert value == 42
        assert isinstance(value, int)

    def test_float(self):
        key, value = parse_override("rate=3.14")
        assert key == "rate"
        assert value == 3.14
        assert isinstance(value, float)

    def test_negative_integer(self):
        # Negative numbers are parsed as integers
        key, value = parse_override("temp=-5")
        assert key == "temp"
        assert value == -5
        assert isinstance(value, int)

    def test_value_with_equals(self):
        key, value = parse_override("expr=a=b")
        assert key == "expr"
        assert value == "a=b"

    def test_whitespace_stripped(self):
        key, value = parse_override("  key  =  value  ")
        assert key == "key"
        assert value == "value"

    def test_invalid_format_no_equals(self):
        with pytest.raises(ValueError, match="Invalid override format"):
            parse_override("no_equals_here")

    def test_empty_key(self):
        with pytest.raises(ValueError, match="key cannot be empty"):
            parse_override("=value")


class TestResolveConfigPath:
    def test_direct_file_path(self, tmp_path):
        config_file = tmp_path / "custom.yaml"
        config_file.write_text("type: claude_code")

        result = resolve_config_path(str(config_file), "agents")
        assert result == config_file

    def test_direct_file_any_extension(self, tmp_path):
        # Should work with any extension if file exists
        config_file = tmp_path / "my_prompt.txt"
        config_file.write_text("prompt content")

        result = resolve_config_path(str(config_file), "prompts")
        assert result == config_file

    def test_relative_path_to_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "my_agent.yaml"
        config_file.write_text("type: claude_code")

        result = resolve_config_path("my_agent.yaml", "agents")
        assert result.exists()
        assert result.name == "my_agent.yaml"

    def test_home_expansion(self, tmp_path, monkeypatch):
        # Create a temp file and simulate ~ expansion
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("type: claude_code")

        # Mock expanduser to return our temp path
        monkeypatch.setattr(Path, "expanduser", lambda self: config_file)

        result = resolve_config_path("~/agent.yaml", "agents")
        assert result == config_file

    def test_bare_name_finds_package_config(self):
        # This should find the built-in claude_code config
        package_config_dir = get_package_config_dir()
        expected = package_config_dir / "agents" / "claude_code.yaml"

        # Only run if the package config exists
        if expected.exists():
            result = resolve_config_path("claude_code", "agents")
            assert result == expected

    def test_bare_name_prompt_uses_jinja_extension(self):
        package_config_dir = get_package_config_dir()
        expected = package_config_dir / "prompts" / "just-solve.jinja"

        if expected.exists():
            result = resolve_config_path("just-solve", "prompts")
            assert result == expected

    def test_file_not_found_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="not found"):
            resolve_config_path("nonexistent_config", "agents")

    def test_explicit_path_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            resolve_config_path(str(tmp_path / "missing.yaml"), "agents")


class TestLoadRunConfig:
    def test_defaults_only(self):
        """Test loading with all defaults (no config file, no flags, no overrides)."""
        config = load_run_config()

        assert config.model.provider == "anthropic"
        assert config.model.name == "sonnet-4.5"
        assert config.thinking == "none"
        assert config.pass_policy == PassPolicy.ANY
        assert config.one_shot.enabled is False
        assert config.one_shot.prefix == ""
        assert config.one_shot.include_first_prefix is False
        # Output path should have been resolved (no ${} remaining)
        assert "${" not in config.output_path
        assert config.problems == []

    def test_cli_flags_override_defaults(self):
        """Test that CLI flags override defaults."""
        config = load_run_config(
            cli_flags={
                "prompt": "best_practice",
                "model": {"provider": "openai", "name": "gpt-4.1"},
            }
        )

        assert config.model.provider == "openai"
        assert config.model.name == "gpt-4.1"
        # Should find the prompt file
        assert config.prompt_path.stem == "best_practice"

    def test_cli_overrides_override_flags(self):
        """Test that key=value overrides take highest priority."""
        config = load_run_config(
            cli_flags={
                "model": {"provider": "anthropic", "name": "sonnet-4.5"},
            },
            cli_overrides=["model.name=opus-4"],
        )

        # Override should win
        assert config.model.name == "opus-4"
        # Provider unchanged
        assert config.model.provider == "anthropic"

    def test_config_file_merging(self, tmp_path):
        """Test loading from a config file."""
        config_file = tmp_path / "run_config.yaml"
        config_file.write_text(
            """
model:
  provider: openai
  name: gpt-4.1
thinking: medium
pass_policy: all-cases
output_path: custom/output/path
"""
        )

        config = load_run_config(config_path=config_file)

        assert config.model.provider == "openai"
        assert config.model.name == "gpt-4.1"
        assert config.thinking == "medium"
        assert config.pass_policy == PassPolicy.ALL_CASES
        assert config.output_path == "custom/output/path"
        assert config.problems == []

    def test_priority_order(self, tmp_path):
        """Test priority: CLI overrides > flags > config file > defaults."""
        config_file = tmp_path / "run_config.yaml"
        config_file.write_text(
            """
model:
  provider: config_provider
  name: config_model
thinking: low
"""
        )

        config = load_run_config(
            config_path=config_file,
            cli_flags={
                "model": {"provider": "flag_provider", "name": "flag_model"},
            },
            cli_overrides=["model.name=override_model"],
        )

        # model.name: override wins
        assert config.model.name == "override_model"
        # model.provider: flag wins over config
        assert config.model.provider == "flag_provider"
        # thinking: config value (no flag or override)
        assert config.thinking == "low"
        assert config.problems == []

    def test_inline_agent_config(self, tmp_path):
        """Test with inline agent configuration."""
        config_file = tmp_path / "run_config.yaml"
        config_file.write_text(
            """
agent:
  type: claude_code
  version: "2.0.51"
  cost_limits:
    step_limit: 50
"""
        )

        config = load_run_config(config_path=config_file)

        assert config.agent_config_path is None
        assert config.agent["type"] == "claude_code"
        assert config.agent["version"] == "2.0.51"

    def test_thinking_preset_override(self):
        """Test overriding thinking via key=value."""
        config = load_run_config(cli_overrides=["thinking=high"])

        assert config.thinking == "high"

    def test_pass_policy_override(self):
        """Test overriding pass_policy via key=value."""
        config = load_run_config(cli_overrides=["pass_policy=all-cases"])

        assert config.pass_policy == PassPolicy.ALL_CASES

    def test_output_path_interpolation(self):
        """Test that output_path interpolation works."""
        config = load_run_config(
            cli_flags={
                "model": {"provider": "test_provider", "name": "test_model"},
            },
            cli_overrides=["thinking=medium"],
        )

        # Output path should contain resolved values
        assert "test_model" in config.output_path
        assert "medium" in config.output_path

    def test_config_file_not_found(self, tmp_path):
        """Test error when config file doesn't exist."""
        missing_file = tmp_path / "missing.yaml"

        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_run_config(config_path=missing_file)

    def test_invalid_override_format(self):
        """Test error on invalid override format."""
        with pytest.raises(ValueError, match="Invalid override format"):
            load_run_config(cli_overrides=["invalid_no_equals"])

    def test_problems_from_config(self, tmp_path):
        """Test loading problems list from config file."""
        config_file = tmp_path / "run_config.yaml"
        config_file.write_text(
            """
problems:
  - alpha
  - beta
"""
        )

        config = load_run_config(config_path=config_file)

        assert config.problems == ["alpha", "beta"]

    def test_problems_string_normalization(self, tmp_path):
        """Test single problem name is coerced into list."""
        config_file = tmp_path / "run_config.yaml"
        config_file.write_text("problems: single_problem\n")

        config = load_run_config(config_path=config_file)

        assert config.problems == ["single_problem"]

    def test_invalid_problems_type(self, tmp_path):
        """Test error when problems contain non-string entries."""
        config_file = tmp_path / "run_config.yaml"
        config_file.write_text(
            """
problems:
  - 123
"""
        )

        with pytest.raises(ValueError, match="Invalid problems configuration"):
            load_run_config(config_path=config_file)

    def test_one_shot_override(self):
        config = load_run_config(
            cli_overrides=[
                "one_shot.enabled=true",
                "one_shot.prefix=--NEXT--",
                "one_shot.include_first_prefix=true",
            ]
        )

        assert config.one_shot.enabled is True
        assert config.one_shot.prefix == "--NEXT--"
        assert config.one_shot.include_first_prefix is True

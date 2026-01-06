"""Tests for evaluation configuration models."""

from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.report import GroupType


def test_group_config_isolated_field_default():
    """Test that isolated field defaults to True."""
    group = GroupConfig(name="test_group")
    assert group.isolated is True


def test_group_config_isolated_field_set_true():
    """Test that isolated field can be set to True."""
    group = GroupConfig(name="test_group", isolated=True)
    assert group.isolated is True


def test_group_config_isolated_field_set_false():
    """Test that isolated field can be explicitly set to False."""
    group = GroupConfig(name="test_group", isolated=False)
    assert group.isolated is False


def test_group_config_all_fields():
    """Test GroupConfig with all fields including isolated."""
    group = GroupConfig(
        name="test_group",
        type=GroupType.CORE,
        group_files={"file1.txt", "file2.txt"},
        timeout=30.0,
        case_defaults={"arg1": "value1"},
        isolated=True,
        case_order=["case1", "case2"],
    )

    assert group.name == "test_group"
    assert group.type == GroupType.CORE
    assert group.group_files == {"file1.txt", "file2.txt"}
    assert group.timeout == 30.0
    assert group.case_defaults == {"arg1": "value1"}
    assert group.isolated is True
    assert group.case_order == ["case1", "case2"]


def test_group_config_regression_with_isolated():
    """Test regression group with isolated flag."""
    group = GroupConfig(
        name="regression_group",
        type=GroupType.REGRESSION,
        original_checkpoint="checkpoint_1",
        original_group="original_group",
        isolated=True,
    )

    assert group.type == GroupType.REGRESSION
    assert group.original_checkpoint == "checkpoint_1"
    assert group.original_group == "original_group"
    assert group.isolated is True


def test_group_config_case_defaults_with_reset():
    """Test that case_defaults can include reset field."""
    group = GroupConfig(
        name="test_group",
        case_defaults={"reset": True, "timeout_s": 10.0},
        isolated=False,
    )

    assert group.case_defaults["reset"] is True
    assert group.case_defaults["timeout_s"] == 10.0
    assert group.isolated is False


# ============================================================================
# CheckpointConfig Tests (simplified pytest-based model)
# ============================================================================


class TestCheckpointConfig:
    """Tests for the simplified CheckpointConfig model."""

    def test_create_minimal(self):
        """Can create CheckpointConfig with minimal required fields."""
        config = CheckpointConfig(
            name="checkpoint_1",
            version=1,
            order=1,
            timeout=30,
            env={},
        )
        assert config.name == "checkpoint_1"
        assert config.version == 1
        assert config.order == 1
        assert config.state == "Draft"  # Default value
        assert config.spec_override is None  # Default value

    def test_create_with_all_fields(self):
        """Can create CheckpointConfig with all fields."""
        config = CheckpointConfig(
            name="checkpoint_2",
            version=2,
            order=2,
            state="Core Tests",
            timeout=60,
            env={"DEBUG": "1"},
            spec_override="# Test Spec\nThis is a test.",
        )
        assert config.name == "checkpoint_2"
        assert config.version == 2
        assert config.order == 2
        assert config.state == "Core Tests"
        assert config.timeout == 60
        assert config.env == {"DEBUG": "1"}
        assert config.spec_override == "# Test Spec\nThis is a test."

    def test_state_values(self):
        """State field accepts valid literal values."""
        for state in ["Draft", "Core Tests", "Full Tests", "Verified"]:
            config = CheckpointConfig(
                name="checkpoint_1",
                version=1,
                order=1,
                state=state,
            )
            assert config.state == state

    def test_spec_override_excluded_from_serialization(self):
        """spec_override is excluded from model_dump output."""
        config = CheckpointConfig(
            name="checkpoint_1",
            version=1,
            order=1,
            spec_override="Override content",
        )
        dumped = config.model_dump()
        assert "spec_override" not in dumped

    def test_inherits_base_config_fields(self):
        """CheckpointConfig inherits env and timeout from BaseConfig."""
        config = CheckpointConfig(
            name="checkpoint_1",
            version=1,
            order=1,
            env={"KEY": "value"},
            timeout=120.5,
        )
        assert config.env == {"KEY": "value"}
        assert config.timeout == 120.5

    def test_get_base_config_returns_inheritable_fields(self):
        """get_base_config() returns env and timeout."""
        config = CheckpointConfig(
            name="checkpoint_1",
            version=1,
            order=1,
            env={"VAR": "val"},
            timeout=45,
        )
        base = config.get_base_config()
        assert base["env"] == {"VAR": "val"}
        assert base["timeout"] == 45


# ============================================================================
# ProblemConfig test_dependencies Tests
# ============================================================================

from pathlib import Path

from slop_code.evaluation.config import ProblemConfig


class TestProblemConfigTestDependencies:
    """Tests for ProblemConfig.test_dependencies field."""

    def test_test_dependencies_default_empty_list(self):
        """test_dependencies should default to empty list."""
        config = ProblemConfig(
            name="test",
            path=Path("/test"),
            version=1,
            description="Test problem",
            entry_file="main.py",
            tags=["test"],
            checkpoints={},
            # NOT specifying test_dependencies - should use default
        )
        assert config.test_dependencies == []

    def test_test_dependencies_accepts_list(self):
        """test_dependencies should accept a list of strings."""
        config = ProblemConfig(
            name="test",
            path=Path("/test"),
            version=1,
            description="Test problem",
            entry_file="main.py",
            tags=["test"],
            checkpoints={},
            test_dependencies=["httpx", "aiohttp"],
        )
        assert config.test_dependencies == ["httpx", "aiohttp"]

    def test_test_dependencies_empty_list(self):
        """test_dependencies should accept empty list."""
        config = ProblemConfig(
            name="test",
            path=Path("/test"),
            version=1,
            description="Test problem",
            entry_file="main.py",
            tags=["test"],
            checkpoints={},
            test_dependencies=[],
        )
        assert config.test_dependencies == []

    def test_test_dependencies_single_dep(self):
        """test_dependencies should work with single dependency."""
        config = ProblemConfig(
            name="test",
            path=Path("/test"),
            version=1,
            description="Test problem",
            entry_file="main.py",
            tags=["test"],
            checkpoints={},
            test_dependencies=["requests"],
        )
        assert config.test_dependencies == ["requests"]

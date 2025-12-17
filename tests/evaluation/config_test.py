"""Tests for evaluation configuration models."""


from slop_code.evaluation.adapters.models import GroupType
from slop_code.evaluation.config import GroupConfig


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

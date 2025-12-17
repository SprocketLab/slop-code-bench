"""Tests for evaluation adapter models."""

from pathlib import Path

from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import GroupType
from slop_code.execution.file_ops import Compression
from slop_code.execution.file_ops import FileType
from slop_code.execution.file_ops import InputFile


def test_base_case_reset_field_default():
    """Test that reset field defaults to False."""
    case = BaseCase(
        id="test_case",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1"
    )
    assert case.reset is False


def test_base_case_reset_field_set_true():
    """Test that reset field can be set to True."""
    case = BaseCase(
        id="test_case",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1",
        reset=True
    )
    assert case.reset is True


def test_base_case_reset_field_set_false():
    """Test that reset field can be explicitly set to False."""
    case = BaseCase(
        id="test_case",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1",
        reset=False
    )
    assert case.reset is False


def test_base_case_all_fields():
    """Test BaseCase with all fields including reset."""
    input_file = InputFile(
        path=Path("test.txt"),
        content="test content",
        file_type=FileType.TEXT,
        compression=Compression.NONE
    )

    case = BaseCase(
        id="test_case",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1",
        order=1,
        arguments=["arg1", "arg2"],
        timeout_s=30.0,
        input_files=[input_file],
        tracked_files=["*.log", "output.txt"],
        reset=True,
        original_group="original_group",
        original_checkpoint="checkpoint_0",
    )

    assert case.id == "test_case"
    assert case.group == "test_group"
    assert case.checkpoint == "checkpoint_1"
    assert case.order == 1
    assert case.arguments == ["arg1", "arg2"]
    assert case.timeout_s == 30.0
    assert len(case.input_files) == 1
    assert case.tracked_files == ["*.log", "output.txt"]
    assert case.reset is True
    assert case.original_group == "original_group"
    assert case.original_checkpoint == "checkpoint_0"


def test_base_case_from_case_defaults():
    """Test that reset can be set via case_defaults pattern."""
    # This simulates how loaders would create cases with defaults
    defaults = {"reset": True, "timeout_s": 15.0}
    case = BaseCase(
        id="test_case",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1",
        **defaults
    )

    assert case.reset is True
    assert case.timeout_s == 15.0


def test_base_case_mixed_reset_scenarios():
    """Test various combinations of reset field."""
    # Case with reset=True and timeout
    case1 = BaseCase(
        id="case1",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1",
        reset=True,
        timeout_s=10.0
    )
    assert case1.reset is True

    # Case with reset=False and input files
    case2 = BaseCase(
        id="case2",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1",
        reset=False,
        input_files=[],
        tracked_files=["output.txt"]
    )
    assert case2.reset is False

    # Case with default reset (should be False)
    case3 = BaseCase(
        id="case3",
        group="test_group",
        group_type=GroupType.CORE,
        checkpoint="checkpoint_1"
    )
    assert case3.reset is False

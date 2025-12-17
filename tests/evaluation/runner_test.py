"""Tests for evaluation runner with workspace reset functionality."""

from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import GroupType
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.runner import CheckpointRunner
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import Workspace


@pytest.fixture
def mock_workspace():
    """Create a mock workspace with reset method."""
    workspace = MagicMock(spec=Workspace)
    workspace.reset = MagicMock()
    return workspace


@pytest.fixture
def mock_session(mock_workspace):
    """Create a mock session with workspace."""
    session = MagicMock(spec=Session)
    session.workspace = mock_workspace
    return session


@pytest.fixture
def mock_loader():
    """Create a mock loader that yields test cases."""
    loader = MagicMock()
    loader.initialize_store = MagicMock(return_value={})
    return loader


@pytest.fixture
def mock_adapter():
    """Create a mock adapter."""
    adapter = MagicMock()
    adapter.run_case = MagicMock()
    adapter.__enter__ = MagicMock(return_value=adapter)
    adapter.__exit__ = MagicMock()
    return adapter


@pytest.fixture
def checkpoint_runner(mock_loader):
    """Create a CheckpointRunner instance with mocked dependencies."""
    checkpoint = MagicMock(spec=CheckpointConfig)
    checkpoint.path = Path("/test/checkpoint")
    checkpoint.name = "checkpoint_1"
    checkpoint.env = {}

    environment = MagicMock(spec=EnvironmentSpec)
    environment.get_full_env = MagicMock(return_value={})
    environment.get_command = MagicMock(return_value="python main.py")

    runner = CheckpointRunner(
        problem_name="test_problem",
        submission=Path("/test/submission"),
        checkpoint=checkpoint,
        environment=environment,
        entry_file="main.py",
        static_assets={},
        adapter=MagicMock(),
        verifier=MagicMock(),
        loader=mock_loader,
        version=1,
    )
    runner.snapshot_fn = MagicMock()
    return runner


@patch('slop_code.evaluation.runner.Workspace')
@patch('slop_code.evaluation.runner.Session')
def test_run_group_with_isolated_true(mock_session_class, mock_workspace_class, checkpoint_runner, mock_adapter):
    """Test that workspace.reset() is called for each case when group.isolated is True."""
    # Setup mocks
    mock_workspace = MagicMock()
    mock_workspace.reset = MagicMock()
    mock_workspace_class.return_value = mock_workspace

    mock_session = MagicMock()
    mock_session_class.return_value = mock_session

    # Create test group with isolated=True
    group = GroupConfig(name="test_group", isolated=True)

    # Create test cases
    cases = [
        (BaseCase(id="case1", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case2", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case3", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
    ]

    checkpoint_runner.loader.return_value = cases
    checkpoint_runner.make_adapter = MagicMock(return_value=mock_adapter)

    with patch('slop_code.evaluation.runner.run_case'):
        checkpoint_runner.run_group(group=group, snapshot=MagicMock())

    # Verify workspace.reset() was called for each case
    assert mock_workspace.reset.call_count == 3


@patch('slop_code.evaluation.runner.Workspace')
@patch('slop_code.evaluation.runner.Session')
def test_run_group_with_isolated_false(mock_session_class, mock_workspace_class, checkpoint_runner, mock_adapter):
    """Test that workspace.reset() is not called when group.isolated is False and cases have reset=False."""
    # Setup mocks
    mock_workspace = MagicMock()
    mock_workspace.reset = MagicMock()
    mock_workspace_class.return_value = mock_workspace

    mock_session = MagicMock()
    mock_session_class.return_value = mock_session

    # Create test group with isolated=False
    group = GroupConfig(name="test_group", isolated=False)

    # Create test cases with reset=False
    cases = [
        (BaseCase(id="case1", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case2", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case3", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
    ]

    checkpoint_runner.loader.return_value = cases
    checkpoint_runner.make_adapter = MagicMock(return_value=mock_adapter)

    with patch('slop_code.evaluation.runner.run_case'):
        checkpoint_runner.run_group(group=group, snapshot=MagicMock())

    # Verify workspace.reset() was never called
    assert mock_workspace.reset.call_count == 0


@patch('slop_code.evaluation.runner.Workspace')
@patch('slop_code.evaluation.runner.Session')
def test_run_group_with_case_reset_true(mock_session_class, mock_workspace_class, checkpoint_runner, mock_adapter):
    """Test that workspace.reset() is called only for cases with reset=True when group.isolated is False."""
    # Setup mocks
    mock_workspace = MagicMock()
    mock_workspace.reset = MagicMock()
    mock_workspace_class.return_value = mock_workspace

    mock_session = MagicMock()
    mock_session_class.return_value = mock_session

    # Create test group with isolated=False
    group = GroupConfig(name="test_group", isolated=False)

    # Create test cases with mixed reset values
    cases = [
        (BaseCase(id="case1", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case2", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=True), MagicMock()),
        (BaseCase(id="case3", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case4", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=True), MagicMock()),
    ]

    checkpoint_runner.loader.return_value = cases
    checkpoint_runner.make_adapter = MagicMock(return_value=mock_adapter)

    with patch('slop_code.evaluation.runner.run_case'):
        checkpoint_runner.run_group(group=group, snapshot=MagicMock())

    # Verify workspace.reset() was called only for cases with reset=True
    assert mock_workspace.reset.call_count == 2


@patch('slop_code.evaluation.runner.Workspace')
@patch('slop_code.evaluation.runner.Session')
def test_run_group_with_isolated_and_case_reset(mock_session_class, mock_workspace_class, checkpoint_runner, mock_adapter):
    """Test that workspace.reset() is called for all cases when group.isolated is True, regardless of case.reset."""
    # Setup mocks
    mock_workspace = MagicMock()
    mock_workspace.reset = MagicMock()
    mock_workspace_class.return_value = mock_workspace

    mock_session = MagicMock()
    mock_session_class.return_value = mock_session

    # Create test group with isolated=True
    group = GroupConfig(name="test_group", isolated=True)

    # Create test cases with mixed reset values
    cases = [
        (BaseCase(id="case1", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case2", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=True), MagicMock()),
        (BaseCase(id="case3", group="test_group", group_type=GroupType.CORE, checkpoint="checkpoint_1", reset=False), MagicMock()),
    ]

    checkpoint_runner.loader.return_value = cases
    checkpoint_runner.make_adapter = MagicMock(return_value=mock_adapter)

    with patch('slop_code.evaluation.runner.run_case'):
        checkpoint_runner.run_group(group=group, snapshot=MagicMock())

    # Verify workspace.reset() was called for all cases
    assert mock_workspace.reset.call_count == 3


@patch('slop_code.evaluation.runner.Workspace')
@patch('slop_code.evaluation.runner.Session')
def test_run_group_regression_with_isolated(mock_session_class, mock_workspace_class, checkpoint_runner, mock_adapter):
    """Test that regression groups can also use the isolated flag."""
    # Setup mocks
    mock_workspace = MagicMock()
    mock_workspace.reset = MagicMock()
    mock_workspace_class.return_value = mock_workspace

    mock_session = MagicMock()
    mock_session_class.return_value = mock_session

    # Create regression group with isolated=True
    group = GroupConfig(
        name="regression_group",
        type=GroupType.REGRESSION,
        original_checkpoint="checkpoint_0",
        original_group="original_group",
        isolated=True,
    )

    # Create test cases
    cases = [
        (BaseCase(id="case1", group="regression_group", group_type=GroupType.REGRESSION, checkpoint="checkpoint_1", reset=False), MagicMock()),
        (BaseCase(id="case2", group="regression_group", group_type=GroupType.REGRESSION, checkpoint="checkpoint_1", reset=False), MagicMock()),
    ]

    checkpoint_runner.loader.return_value = cases
    checkpoint_runner.make_adapter = MagicMock(return_value=mock_adapter)

    with patch('slop_code.evaluation.runner.run_case'):
        checkpoint_runner.run_group(group=group, snapshot=MagicMock())

    # Verify workspace.reset() was called for each case
    assert mock_workspace.reset.call_count == 2

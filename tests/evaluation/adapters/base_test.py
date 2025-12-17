"""Tests for BaseAdapter and AdapterRegistry."""

from __future__ import annotations

from typing import Literal
from unittest.mock import MagicMock

import pytest
from pydantic import Field

from slop_code.evaluation.adapters.base import ADAPTER_REGISTRY
from slop_code.evaluation.adapters.base import AdapterConfig
from slop_code.evaluation.adapters.base import AdapterRegistry
from slop_code.evaluation.adapters.base import BaseAdapter
from slop_code.evaluation.adapters.models import BaseCase
from slop_code.evaluation.adapters.models import CaseResult
from slop_code.evaluation.adapters.models import GroupType
from slop_code.execution import ExecutionError


class MockAdapterConfig(AdapterConfig):
    """Mock adapter config for testing."""

    type: Literal["test"] = "test"


class MockCase(BaseCase):
    """Mock case model."""

    custom_field: str = "test"


class MockResult(CaseResult):
    """Mock result model."""

    type: Literal["test"] = Field(default="test", frozen=True)
    custom_result: str = "result"


class ConcreteTestAdapter(BaseAdapter[MockCase, MockResult, MockAdapterConfig]):
    """Concrete test adapter for testing."""

    case_class = MockCase
    result_class = MockResult
    config_class = MockAdapterConfig

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_enter_called = False
        self.on_exit_called = False
        self.execute_case_called = False

    def _on_enter(self) -> None:
        self.on_enter_called = True

    def _on_exit(self, exc_type, exc, tb) -> None:
        self.on_exit_called = True

    def _execute_case(self, case: MockCase, tracked_files: list[str]) -> MockResult:
        self.execute_case_called = True
        return MockResult(
            id=case.id,
            group_type=case.group_type,
            group=case.group,
            custom_result="executed",
        )


@pytest.fixture
def mock_session():
    """Create a mock session for testing."""
    session = MagicMock()
    session.resolve_static_placeholders = lambda x: x
    session.get_file_contents = lambda x: {}
    return session


@pytest.fixture
def test_config():
    """Create a test adapter config."""
    return MockAdapterConfig(tracked_files=["*.txt"])


@pytest.fixture
def test_case():
    """Create a test case."""
    return MockCase(
        id="test_case_1",
        group_type=GroupType.CORE,
        group="test_group",
        checkpoint="checkpoint_1",
        tracked_files=["*.log"],
    )


class TestBaseAdapter:
    """Tests for BaseAdapter abstract class."""

    def test_session_lifecycle_calls_prepare_and_cleanup(
        self, mock_session, test_config
    ):
        """__enter__ calls session.prepare(), __exit__ calls session.cleanup()."""
        adapter = ConcreteTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        with adapter:
            mock_session.prepare.assert_called_once()

        mock_session.cleanup.assert_called_once()

    def test_on_enter_hook_called_after_prepare(self, mock_session, test_config):
        """_on_enter() is called after session.prepare()."""
        adapter = ConcreteTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        with adapter:
            assert adapter.on_enter_called

    def test_on_exit_hook_called_before_cleanup(self, mock_session, test_config):
        """_on_exit() is called before session.cleanup()."""
        call_order = []
        mock_session.cleanup = lambda: call_order.append("cleanup")

        adapter = ConcreteTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        # Override _on_exit to track order
        original_on_exit = adapter._on_exit

        def tracked_on_exit(*args):
            call_order.append("on_exit")
            original_on_exit(*args)

        adapter._on_exit = tracked_on_exit

        with adapter:
            pass

        assert call_order == ["on_exit", "cleanup"]

    def test_resolve_case_placeholders(self, mock_session, test_config, test_case):
        """_resolve_case_placeholders uses session.resolve_static_placeholders."""
        mock_session.resolve_static_placeholders = MagicMock(
            return_value=test_case.model_dump()
        )

        adapter = ConcreteTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        resolved = adapter._resolve_case_placeholders(test_case)

        mock_session.resolve_static_placeholders.assert_called_once()
        assert isinstance(resolved, MockCase)

    def test_merge_tracked_files_combines_adapter_and_case(
        self, mock_session, test_config, test_case
    ):
        """Tracked files from adapter config and case are merged."""
        adapter = ConcreteTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        merged = adapter._merge_tracked_files(test_case)

        # Should contain both adapter-level (*.txt) and case-level (*.log)
        assert "*.txt" in merged
        assert "*.log" in merged

    def test_make_error_result_sets_adapter_error_flag(
        self, mock_session, test_config, test_case
    ):
        """_make_error_result creates result with adapter_error=True."""
        adapter = ConcreteTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        exc = Exception("Test error")
        result = adapter._make_error_result(test_case, exc)

        assert result.adapter_error is True
        assert result.status_code == -1
        assert "Test error" in result.stderr

    def test_run_case_catches_execution_error(self, mock_session, test_config, test_case):
        """ExecutionError in _execute_case returns error result, not raises."""

        class ErrorAdapter(ConcreteTestAdapter):
            def _execute_case(self, case, tracked_files):
                raise ExecutionError("Execution failed")

        adapter = ErrorAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        result = adapter.run_case(test_case)

        assert result.adapter_error is True
        assert result.status_code == -1
        assert "Execution failed" in result.stderr


class TestAdapterRegistry:
    """Tests for AdapterRegistry."""

    @pytest.fixture(autouse=True)
    def isolated_registry(self):
        """Use a fresh registry for each test."""
        # Save original adapters
        original = dict(AdapterRegistry._adapters)
        AdapterRegistry._adapters.clear()
        yield
        # Restore original adapters
        AdapterRegistry._adapters = original

    def test_register_decorator_adds_to_registry(self):
        """@ADAPTER_REGISTRY.register("foo") adds class to _adapters."""

        @AdapterRegistry.register("foo")
        class FooAdapter(ConcreteTestAdapter):
            pass

        assert "foo" in AdapterRegistry._adapters
        assert AdapterRegistry._adapters["foo"] is FooAdapter

    def test_get_returns_registered_adapter(self):
        """get("foo") returns registered adapter class."""

        @AdapterRegistry.register("bar")
        class BarAdapter(ConcreteTestAdapter):
            pass

        result = AdapterRegistry.get("bar")
        assert result is BarAdapter

    def test_get_unknown_type_raises_value_error(self):
        """get("unknown") raises ValueError with available types."""
        with pytest.raises(ValueError) as exc_info:
            AdapterRegistry.get("unknown")

        assert "Unknown adapter type: unknown" in str(exc_info.value)

    def test_duplicate_registration_raises_error(self):
        """Registering same type twice raises ValueError."""

        @AdapterRegistry.register("dup")
        class DupAdapter1(ConcreteTestAdapter):
            pass

        with pytest.raises(ValueError) as exc_info:

            @AdapterRegistry.register("dup")
            class DupAdapter2(ConcreteTestAdapter):
                pass

        assert "already registered" in str(exc_info.value)

    def test_make_adapter_creates_instance(self, mock_session):
        """make_adapter() returns properly initialized adapter instance."""

        @AdapterRegistry.register("make_test")
        class MakeTestAdapter(ConcreteTestAdapter):
            pass

        # Create a custom config with matching type
        class MakeTestConfig(MockAdapterConfig):
            type: Literal["make_test"] = "make_test"

        config = MakeTestConfig()

        adapter = AdapterRegistry.make_adapter(
            config=config,
            session=mock_session,
            env={"KEY": "value"},
            command="test_cmd",
            timeout=30.0,
            isolated=True,
        )

        assert isinstance(adapter, MakeTestAdapter)
        assert adapter.env == {"KEY": "value"}
        assert adapter.command == "test_cmd"
        assert adapter.timeout == 30.0
        assert adapter.isolated is True

    def test_clear_removes_all_adapters(self):
        """clear() removes all registered adapters."""

        @AdapterRegistry.register("clear_test")
        class ClearTestAdapter(ConcreteTestAdapter):
            pass

        assert "clear_test" in AdapterRegistry._adapters

        AdapterRegistry.clear()

        assert len(AdapterRegistry._adapters) == 0


class TestConcreteAdapter:
    """Test that a minimal subclass works correctly."""

    def test_minimal_subclass_works(self, mock_session, test_config, test_case):
        """Subclass with only _execute_case works via base class."""
        adapter = ConcreteTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        result = adapter.run_case(test_case)

        assert adapter.execute_case_called
        assert result.custom_result == "executed"

    def test_subclass_can_override_hooks(self, mock_session, test_config):
        """Subclass _on_enter/_on_exit are called in correct order."""
        call_order = []

        class HookTestAdapter(ConcreteTestAdapter):
            def _on_enter(self) -> None:
                call_order.append("on_enter")

            def _on_exit(self, exc_type, exc, tb) -> None:
                call_order.append("on_exit")

        adapter = HookTestAdapter(
            cfg=test_config,
            session=mock_session,
            env={},
            command="test",
        )

        with adapter:
            call_order.append("inside")

        assert call_order == ["on_enter", "inside", "on_exit"]


class TestGlobalRegistry:
    """Test that the global ADAPTER_REGISTRY works with real adapters."""

    def test_cli_adapter_registered(self):
        """CLI adapter is registered in global registry."""
        # Import adapters module to trigger registration
        from slop_code.evaluation import adapters  # noqa: F401

        assert "cli" in ADAPTER_REGISTRY._adapters

    def test_api_adapter_registered(self):
        """API adapter is registered in global registry."""
        from slop_code.evaluation import adapters  # noqa: F401

        assert "api" in ADAPTER_REGISTRY._adapters

    def test_playwright_adapter_registered(self):
        """Playwright adapter is registered in global registry."""
        from slop_code.evaluation import adapters  # noqa: F401

        assert "playwright" in ADAPTER_REGISTRY._adapters

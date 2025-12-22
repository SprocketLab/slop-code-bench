"""Tests for the logging module, focusing on stdlib logger adapter."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
import structlog

from slop_code.logging import StdlibLoggerAdapter
from slop_code.logging import get_logger
from slop_code.logging import is_structlog_configured
from slop_code.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_logging_state():
    """Reset logging state before and after each test."""
    # Note: We don't call reset_logging() here because it clears
    # handlers that pytest's caplog fixture installs
    # Instead, just reset structlog configuration
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


class TestStdlibLoggerAdapter:
    """Test the StdlibLoggerAdapter class."""

    def test_basic_logging_without_kwargs(self, caplog):
        """Test basic logging without kwargs works."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        with caplog.at_level(logging.DEBUG):
            adapter.debug("Debug message")
            adapter.info("Info message")
            adapter.warning("Warning message")
            adapter.error("Error message")
            adapter.critical("Critical message")

        assert "Debug message" in caplog.text
        assert "Info message" in caplog.text
        assert "Warning message" in caplog.text
        assert "Error message" in caplog.text
        assert "Critical message" in caplog.text

    def test_logging_with_single_kwarg(self, caplog):
        """Test logging with a single kwarg."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        with caplog.at_level(logging.INFO):
            adapter.info("Server started", port=8080)

        assert "Server started port=8080" in caplog.text

    def test_logging_with_multiple_kwargs(self, caplog):
        """Test logging with multiple kwargs."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        with caplog.at_level(logging.INFO):
            adapter.info(
                "Connection established",
                host="localhost",
                port=8080,
                secure=True,
            )

        # Check that all kwargs are in the message (sorted order)
        assert "Connection established" in caplog.text
        assert "host='localhost'" in caplog.text
        assert "port=8080" in caplog.text
        assert "secure=True" in caplog.text

    def test_logging_with_exc_info(self, caplog):
        """Test logging with exc_info kwarg."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        try:
            raise ValueError("Test error")
        except ValueError:
            with caplog.at_level(logging.ERROR):
                adapter.error("An error occurred", exc_info=True)

        assert "An error occurred" in caplog.text
        assert "ValueError: Test error" in caplog.text
        assert "Traceback" in caplog.text

    def test_logging_with_exc_info_and_other_kwargs(self, caplog):
        """Test logging with exc_info and other kwargs."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        try:
            raise ValueError("Test error")
        except ValueError:
            with caplog.at_level(logging.ERROR):
                adapter.error(
                    "Request failed", url="/api/test", status=500, exc_info=True
                )

        assert "Request failed" in caplog.text
        assert "status=500" in caplog.text
        assert "url='/api/test'" in caplog.text
        assert "ValueError: Test error" in caplog.text

    def test_exception_method(self, caplog):
        """Test the exception method adds exc_info automatically."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        try:
            raise RuntimeError("Test runtime error")
        except RuntimeError:
            with caplog.at_level(logging.ERROR):
                adapter.exception("Caught exception", request_id=123)

        assert "Caught exception" in caplog.text
        assert "request_id=123" in caplog.text
        assert "RuntimeError: Test runtime error" in caplog.text

    def test_verbose_kwarg_handling(self, caplog):
        """Test that verbose=True kwarg is handled properly."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        # Verbose kwarg should be removed from output
        with caplog.at_level(logging.DEBUG):
            adapter.debug("Verbose message", verbose=True)

        assert "Verbose message" in caplog.text
        assert "verbose=" not in caplog.text  # Should be removed, not formatted

    def test_complex_object_formatting(self, caplog):
        """Test formatting of complex objects in kwargs."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        # Test with dict
        with caplog.at_level(logging.INFO):
            adapter.info("Dict data", data={"key": "value", "number": 42})

        assert "data={'key': 'value', 'number': 42}" in caplog.text

        # Test with list
        caplog.clear()
        with caplog.at_level(logging.INFO):
            adapter.info("List data", items=[1, 2, 3])

        assert "items=[1, 2, 3]" in caplog.text

    def test_pydantic_model_formatting(self, caplog):
        """Test formatting of objects with model_dump method."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        # Mock a pydantic-like model
        mock_model = MagicMock()
        mock_model.model_dump = MagicMock(
            return_value={"field": "value", "number": 123}
        )

        with caplog.at_level(logging.INFO):
            adapter.info("Model data", model=mock_model)

        assert "model={'field': 'value', 'number': 123}" in caplog.text

    def test_log_method_with_level(self, caplog):
        """Test the log method with specific level."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        with caplog.at_level(logging.DEBUG):
            adapter.log(logging.WARNING, "Custom level message", custom="data")

        assert "Custom level message custom='data'" in caplog.text
        assert logging.WARNING in [rec.levelno for rec in caplog.records]

    def test_adapter_logger_methods(self):
        """Test that adapter properly proxies logger methods."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        # Test setLevel
        adapter.setLevel(logging.WARNING)
        assert adapter.getEffectiveLevel() == logging.WARNING

        # Test isEnabledFor
        assert adapter.isEnabledFor(logging.ERROR) is True
        assert adapter.isEnabledFor(logging.DEBUG) is False

        # Test name attribute
        assert adapter.name == "test"

    def test_adapter_handler_methods(self):
        """Test that adapter properly proxies handler methods."""
        logger = logging.getLogger("test")
        adapter = StdlibLoggerAdapter(logger)

        handler = logging.StreamHandler()

        # Test addHandler
        adapter.addHandler(handler)
        assert handler in adapter.handlers

        # Test hasHandlers
        assert adapter.hasHandlers() is True

        # Test removeHandler
        adapter.removeHandler(handler)
        assert handler not in adapter.handlers


class TestGetLogger:
    """Test the get_logger function with auto-detection."""

    def test_get_logger_without_structlog(self):
        """Test get_logger returns StdlibLoggerAdapter when structlog not configured."""
        # Don't call reset_logging() as it clears caplog handlers
        # The fixture already resets structlog

        # Structlog should not be configured
        assert is_structlog_configured() is False

        logger = get_logger("test")
        assert isinstance(logger, StdlibLoggerAdapter)
        assert logger.name == "test"

    def test_get_logger_with_structlog(self):
        """Test get_logger returns structlog logger when configured."""
        # Configure structlog
        setup_logging()

        # Structlog should now be configured
        assert is_structlog_configured() is True

        logger = get_logger("test")
        # Should be a structlog logger (might be BoundLoggerLazyProxy or BoundLogger)
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        # Verify it's NOT our StdlibLoggerAdapter
        assert not isinstance(logger, StdlibLoggerAdapter)

    def test_get_logger_kwargs_compatibility_without_structlog(self, caplog):
        """Test that kwargs work with get_logger when structlog is not configured."""
        # Don't call reset_logging() as it clears caplog handlers

        # Need to ensure the logger hierarchy is set up for caplog
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        with caplog.at_level(logging.INFO):
            # This should not raise an error
            logger.info("Testing kwargs", key1="value1", key2=42)

        assert "Testing kwargs" in caplog.text
        assert "key1='value1'" in caplog.text
        assert "key2=42" in caplog.text

    def test_get_logger_kwargs_compatibility_with_structlog(self, capsys):
        """Test that kwargs work with get_logger when structlog is configured."""
        # Configure structlog with simple console renderer for testing
        setup_logging(enable_colors=False)

        # Ensure logger level is set
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        # This should work with structlog's native kwargs support
        logger.info("Testing kwargs", key1="value1", key2=42)

        # With structlog configured, output goes to stdout
        captured = capsys.readouterr()
        assert "Testing kwargs" in captured.out
        # The kwargs should also be present in the output
        assert "key1" in captured.out or "value1" in captured.out


class TestRealWorldUsage:
    """Test real-world usage patterns found in the codebase."""

    def test_multiple_kwargs_pattern(self, caplog):
        """Test the multiple kwargs pattern used throughout the codebase."""
        # Ensure the logger is set to DEBUG level
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        with caplog.at_level(logging.DEBUG):
            # Pattern from claude_code agent
            logger.debug(
                "Received payload",
                msg_id="123",
                type="test_type",
                content="test content",
            )

        assert "Received payload" in caplog.text
        assert "msg_id='123'" in caplog.text
        assert "type='test_type'" in caplog.text

    def test_verbose_flag_pattern(self, caplog):
        """Test the verbose=True pattern used in the codebase."""
        # Ensure the logger is set to DEBUG level
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        with caplog.at_level(logging.DEBUG):
            logger.debug("Preparing session", verbose=True)
            logger.debug("Creating Docker client", verbose=True)

        assert "Preparing session" in caplog.text
        assert "Creating Docker client" in caplog.text
        # verbose should not appear in the output
        assert "verbose=" not in caplog.text

    def test_error_with_exc_info_pattern(self, caplog):
        """Test the error logging with exc_info pattern."""
        # Ensure the logger is set to DEBUG level
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        try:
            raise RuntimeError("Something went wrong")
        except RuntimeError:
            with caplog.at_level(logging.ERROR):
                logger.error(
                    "Verifier error", error="RuntimeError", exc_info=True
                )

        assert "Verifier error" in caplog.text
        assert "error='RuntimeError'" in caplog.text
        assert "Something went wrong" in caplog.text

    def test_complex_object_logging_pattern(self, caplog):
        """Test logging of complex objects as found in the codebase."""
        # Ensure the logger is set to DEBUG level
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        # Mock a result object with model_dump
        result = MagicMock()
        result.model_dump = MagicMock(
            return_value={"status": "failed", "code": 1}
        )

        with caplog.at_level(logging.ERROR):
            logger.error("Result", result=result)

        assert "Result" in caplog.text
        assert "result={'status': 'failed', 'code': 1}" in caplog.text

    def test_stdout_stderr_pattern(self, caplog):
        """Test the stdout/stderr logging pattern from api.py."""
        # Ensure the logger is set to DEBUG level
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        with caplog.at_level(logging.DEBUG):
            logger.debug("stdout", out="Hello, World!")
            logger.error("stderr", err="Error occurred")

        assert "stdout out='Hello, World!'" in caplog.text
        assert "stderr err='Error occurred'" in caplog.text


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_mixed_usage_in_same_session(self, caplog):
        """Test that switching between structlog and stdlib works."""
        # Start without structlog
        logging.getLogger("test1").setLevel(logging.DEBUG)
        logger1 = get_logger("test1")

        with caplog.at_level(logging.INFO):
            logger1.info("Without structlog", data="test1")

        assert "Without structlog data='test1'" in caplog.text

        # Now configure structlog (output will go to console, not caplog)
        # We just verify that it doesn't raise an error
        caplog.clear()
        setup_logging(enable_colors=False)
        logger2 = get_logger("test2")

        # Verify the logger type changed after structlog setup
        assert not isinstance(logger2, StdlibLoggerAdapter)

        # This should work without errors (output goes to console)
        logger2.info("With structlog", data="test2")
        # We can't easily capture structlog console output in this test
        # but we've verified it works without errors

    def test_no_kwargs_still_works(self, caplog):
        """Test that calls without kwargs still work properly."""
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        with caplog.at_level(logging.DEBUG):
            # These should all work fine without kwargs
            logger.debug("Debug")
            logger.info("Info")
            logger.warning("Warning")
            logger.error("Error")
            logger.critical("Critical")

        assert "Debug" in caplog.text
        assert "Info" in caplog.text
        assert "Warning" in caplog.text
        assert "Error" in caplog.text
        assert "Critical" in caplog.text

    def test_positional_args_compatibility(self, caplog):
        """Test that positional args for string formatting still work."""
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        with caplog.at_level(logging.INFO):
            # This uses % formatting with positional args
            logger.info("Hello %s", "World", user="Alice")

        assert "Hello World user='Alice'" in caplog.text

    def test_special_kwargs_filtering(self, caplog):
        """Test that special kwargs are properly handled and not displayed."""
        logging.getLogger("test").setLevel(logging.DEBUG)
        logger = get_logger("test")

        with caplog.at_level(logging.INFO):
            # These special kwargs should not appear in the message
            logger.info(
                "Test message", exc_info=None, stack_info=False, stacklevel=2
            )

        assert "Test message" in caplog.text
        assert "exc_info=" not in caplog.text
        assert "stack_info=" not in caplog.text
        assert "stacklevel=" not in caplog.text

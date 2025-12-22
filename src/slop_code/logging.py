"""Lightweight structlog helpers used across the repo.

This module centralizes logging configuration and utilities for handling
a custom VERBOSE level, file logging, and automatic structlog detection.

Key features:
- `get_logger()`: Auto-detects structlog vs stdlib logging
- `LoggingConfig`: Centralized configuration dataclass
- `setup_logging()`: Unified setup for standard and Rich console logging
  - Supports both standard console and Rich console output
  - Optional multiprocessing/multithreading tracking via `add_multiproc_info`
  - Automatically handles file logging when `log_dir` is provided
- `setup_live_logging()`: Wrapper around setup_logging() for backward
  compatibility (use setup_logging(console=...) for new code)
- `setup_problem_logging()`: Isolated file-only logging for multiprocessing
  workers (automatically enables process/thread tracking)
- `is_structlog_configured()`: Check if structlog is set up
- `reset_logging()`: Clean slate for testing/re-initialization

This module avoids coupling to any framework and can be safely imported
by library and CLI code.
"""

import functools
import logging
import os
import sys
import threading
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import structlog
from rich.console import Console
from rich.logging import RichHandler
from structlog.contextvars import merge_contextvars
from structlog.processors import JSONRenderer
from structlog.processors import TimeStamper
from structlog.stdlib import BoundLogger
from structlog.stdlib import ProcessorFormatter
from structlog.types import Processor

VERBOSE = 15
logging.addLevelName(VERBOSE, "VERBOSE")

ADDITIONAL_LOGGERS = ("litellm", "minisweagent")


@dataclass
class LoggingConfig:
    """Configuration for logging setup.

    Attributes:
        verbosity: Verbosity level (0=INFO, 1=DEBUG for internal,
            >=2=DEBUG for all).
        enable_colors: Enable colored console output.
        log_dir: Directory for log files (None = no file logging).
        log_file_name: Name of the log file.
        console_level: Minimum level for console output.
        file_level: Minimum level for file output.
        internal_roots: Package prefixes considered "internal" for
            verbosity control.
        extra_processors: Additional structlog processors to include.
        rich_console: Rich Console instance for live logging (None = use
            standard console renderer).
        add_multiproc_info: Whether to add process/thread info to logs.
        verbose_enabled: Whether VERBOSE level messages should be shown.
    """

    verbosity: int = 0
    enable_colors: bool = True
    log_dir: Path | None = None
    log_file_name: str = "log.log"
    console_level: int = logging.INFO
    file_level: int = logging.DEBUG
    internal_roots: tuple[str, ...] = ("slop_code", "agent_runner", "problems")
    extra_processors: list[Processor] = field(default_factory=list)
    rich_console: Console | None = None
    add_multiproc_info: bool = False
    verbose_enabled: bool = field(init=False)

    def __post_init__(self):
        """Set verbose_enabled based on verbosity level."""
        self.verbose_enabled = self.verbosity > 0
        # Adjust console level based on verbosity
        if self.verbosity == 0:
            self.console_level = logging.INFO
        else:
            self.console_level = logging.DEBUG


def _set_external_loggers_to_warning(exempt_prefixes: tuple[str, ...]):
    """Clamp non-internal logger levels to WARNING to reduce noisy output."""

    manager = logging.root.manager
    for name, logger in manager.loggerDict.items():
        if not isinstance(logger, logging.Logger):
            continue
        if not name or name.startswith(exempt_prefixes):
            continue
        logger.setLevel(logging.WARNING)
    for name in ADDITIONAL_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def is_structlog_configured() -> bool:
    """Check if structlog has been configured.

    Returns:
        True if structlog.configure() has been called, False otherwise.
    """
    try:
        # Try to get the current configuration
        # If structlog is configured, this will return the config
        # If not configured, it will return a default but we can check
        # if any processors are set up
        return structlog.is_configured()
    except AttributeError:
        # Fallback for older versions of structlog
        # Check if _config has been set
        return hasattr(structlog, "_config") and structlog._config is not None


class StdlibLoggerAdapter:
    """Adapter that wraps stdlib logging.Logger to support structlog-style kwargs.

    This allows code to use kwargs in log calls even when structlog is not
    configured, providing a consistent API across the codebase.

    Example:
        logger.info("Server started", port=8080, host="localhost")
        # With structlog: Uses native kwargs support
        # With stdlib: Formats kwargs into the message string
    """

    def __init__(self, logger: logging.Logger):
        """Initialize the adapter with a stdlib logger.

        Args:
            logger: The stdlib logging.Logger to wrap.
        """
        self.logger = logger
        self.name = logger.name

    def _format_kwargs(self, kwargs: dict) -> str:
        """Format kwargs as a string to append to the log message.

        Args:
            kwargs: The keyword arguments to format.

        Returns:
            Formatted string like " key1=value1 key2=value2" or empty string.
        """
        if not kwargs:
            return ""

        formatted_pairs = []
        for key, value in sorted(kwargs.items()):
            # Handle special cases for complex objects
            if hasattr(value, "model_dump") and callable(value.model_dump):
                # Pydantic models
                try:
                    value = value.model_dump(mode="json")
                except Exception:
                    value = repr(value)
            elif isinstance(value, (dict, list)) and len(str(value)) > 100:
                # Truncate long collections
                value = f"{str(value)[:100]}..."
            else:
                value = repr(value)
            formatted_pairs.append(f"{key}={value}")

        return " " + " ".join(formatted_pairs)

    def _log(self, level: int, msg: str, *args, **kwargs):
        """Internal method to handle logging with kwargs.

        Args:
            level: The logging level.
            msg: The log message.
            *args: Positional arguments for string formatting.
            **kwargs: Keyword arguments, some passed to logger, others formatted.
        """
        # Extract special kwargs that stdlib logger understands
        exc_info = kwargs.pop("exc_info", None)
        stack_info = kwargs.pop("stack_info", None)
        stacklevel = kwargs.pop(
            "stacklevel", 2
        )  # Default to 2 to skip wrapper frame
        extra = kwargs.pop("extra", None)

        # Handle the special 'verbose' kwarg used by VerboseFilter
        verbose = kwargs.pop("verbose", False)

        # Format remaining kwargs into the message
        kwargs_str = self._format_kwargs(kwargs)
        if kwargs_str:
            msg = f"{msg}{kwargs_str}"

        # Create the log record with the appropriate level
        if verbose and level == logging.DEBUG:
            # For verbose messages at DEBUG level, use VERBOSE level
            level = VERBOSE

        # Pass through to the underlying logger
        # Use _log instead of log to maintain compatibility with pytest's caplog
        if hasattr(self.logger, "_log"):
            self.logger._log(
                level,
                msg,
                args,
                exc_info=exc_info,
                extra=extra,
                stack_info=stack_info,
                stacklevel=stacklevel,
            )
        else:
            self.logger.log(
                level,
                msg,
                *args,
                exc_info=exc_info,
                stack_info=stack_info,
                stacklevel=stacklevel,
                extra=extra,
            )

    def debug(self, msg: str, *args, **kwargs):
        """Log a debug message with optional kwargs."""
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        """Log an info message with optional kwargs."""
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        """Log a warning message with optional kwargs."""
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        """Log an error message with optional kwargs."""
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        """Log a critical message with optional kwargs."""
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        """Log an exception with traceback."""
        kwargs["exc_info"] = True
        self.error(msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args, **kwargs):
        """Log a message at the specified level with optional kwargs."""
        self._log(level, msg, *args, **kwargs)

    def setLevel(self, level):
        """Set the logging level of the underlying logger."""
        self.logger.setLevel(level)

    def getEffectiveLevel(self):
        """Get the effective logging level."""
        return self.logger.getEffectiveLevel()

    def isEnabledFor(self, level):
        """Check if the logger is enabled for the specified level."""
        return self.logger.isEnabledFor(level)

    def addHandler(self, handler):
        """Add a handler to the underlying logger."""
        self.logger.addHandler(handler)

    def removeHandler(self, handler):
        """Remove a handler from the underlying logger."""
        self.logger.removeHandler(handler)

    def hasHandlers(self):
        """Check if the logger has handlers."""
        return self.logger.hasHandlers()

    @property
    def handlers(self):
        """Get the handlers of the underlying logger."""
        return self.logger.handlers


def get_logger(name: str | None = None):
    """Get a logger, auto-detecting structlog vs stdlib logging.

    This function checks if structlog has been configured. If it has,
    it returns a structlog BoundLogger. Otherwise, it returns a
    StdlibLoggerAdapter that wraps a standard library Logger to support
    structlog-style kwargs.

    Args:
        name: Logger name (e.g., __name__). If None, uses the calling
            module's name.

    Returns:
        A structlog BoundLogger if structlog is configured, otherwise
        a StdlibLoggerAdapter wrapping a stdlib logging.Logger.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("This works with both structlog and stdlib")
        >>> logger.info("Server started", port=8080, host="localhost")
    """
    if is_structlog_configured():
        return structlog.get_logger(name)
    return StdlibLoggerAdapter(logging.getLogger(name))


def filter_verbose_msg(_, __, event_dict, verbose_enabled: bool):
    """Drop events tagged as verbose when verbosity is disabled.

    Args:
        _:
            Unused logger instance (structlog processor signature).
        __:
            Unused log method name (structlog processor signature).
        event_dict: Mutable event dictionary produced by structlog.
        verbose_enabled: Whether verbose events should be kept.

    Returns:
        The (possibly mutated) ``event_dict`` when kept.

    Raises:
        structlog.DropEvent: When the event is marked as verbose and
            ``verbose_enabled`` is False.
    """
    if event_dict.pop("verbose", False) and not verbose_enabled:
        raise structlog.DropEvent
    return event_dict


class VerboseFilter(logging.Filter):
    """Handler filter that gates records at the custom VERBOSE level.

    The filter lets all non-VERBOSE records pass. VERBOSE records only pass
    when ``_verbose_enabled`` is True. Attach this to specific handlers to
    enable per-sink verbosity control.
    """

    def __init__(self, name="", verbose_enabled: bool = False):
        super().__init__(name)
        self._verbose_enabled = verbose_enabled

    def filter(self, record):
        """Return True to emit the record, False to suppress it.

        Args:
            record: Logging record being considered.

        Returns:
            True if the record should be emitted for this handler; False
            otherwise.
        """
        # If the message is at our custom VERBOSE level
        if record.levelno == VERBOSE:
            return (
                self._verbose_enabled
            )  # Allow if filter is enabled, suppress if not

        # For all other log levels (DEBUG, INFO, WARNING, etc.), always allow them to pass this filter.
        return True

    def set_verbose_enabled(self, enabled: bool):
        """Enable or disable passing VERBOSE records for this handler.

        Args:
            enabled: When True, VERBOSE records pass; otherwise they drop.
        """
        self._verbose_enabled = enabled


def make_file_logger(
    log_file: Path,
    level: int = logging.DEBUG,
    file_write_mode: str = "w",
    msg_prefix: str = "",
) -> logging.FileHandler:
    """Create a configured file handler.

    Args:
        log_file: Destination path of the log file.
        level: Log level for this handler (defaults to DEBUG).
        file_write_mode: File open mode, e.g. ``"w"`` or ``"a"``.
        msg_prefix: Optional prefix injected before each message.

    Returns:
        A ``logging.FileHandler`` with a consistent formatter applied.
    """
    file_handler = logging.FileHandler(log_file, mode=file_write_mode)
    file_handler.setFormatter(
        logging.Formatter(
            f"[%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d] {msg_prefix}%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    file_handler.setLevel(level)
    return file_handler


def add_logger_name(logger, method_name, event_dict):
    """
    Adds the name of the standard library logger to the event dictionary.
    """
    if isinstance(logger, structlog.stdlib.BoundLogger):
        event_dict["logger_name"] = logger._logger.name
        event_dict["method_name"] = method_name
    return event_dict


def add_process_thread_info(logger, method_name, event_dict):
    """Add process ID and thread name to the event dictionary.

    Useful for debugging multiprocessing and multithreading issues.

    Args:
        logger: The logger instance (unused).
        method_name: The log method name (unused).
        event_dict: Mutable event dictionary produced by structlog.

    Returns:
        The event_dict with process_id and thread_name added.
    """
    event_dict["process_id"] = os.getpid()
    event_dict["thread_name"] = threading.current_thread().name
    return event_dict


def _get_shared_processors(
    verbose_enabled: bool = True,
    add_multiproc_info: bool = False,
):
    """Create the standard shared processor chain.

    Args:
        verbose_enabled: Whether to keep verbose log messages.
        add_multiproc_info: Whether to add process/thread info to logs.

    Returns:
        List of structlog processors for consistent formatting.
    """
    processors = [
        merge_contextvars,
        functools.partial(filter_verbose_msg, verbose_enabled=verbose_enabled),
        TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        structlog.processors.format_exc_info,
        add_logger_name,
    ]

    if add_multiproc_info:
        processors.append(add_process_thread_info)

    return processors


def _create_console_handler(
    config: LoggingConfig,
    processor: Processor | None = None,
) -> logging.StreamHandler:
    """Create a console handler with structlog formatting.

    Args:
        config: Logging configuration.
        processor: Optional custom processor (defaults to ConsoleRenderer or
            live renderer for Rich console).

    Returns:
        Configured console handler (RichHandler if rich_console is set,
        otherwise StreamHandler).
    """
    # Use Rich console if provided
    if config.rich_console is not None:

        def live_renderer(_, __, event_dict):
            """Custom renderer for live console output."""
            out = event_dict.pop("event")
            event_dict.pop("level", None)
            event_dict.pop("timestamp", None)
            if event_dict:
                out = f"{out} {' '.join(k + '=' + repr(v) for k, v in sorted(event_dict.items()))}"
            return out

        root_logger = logging.getLogger()
        root_logger.handlers.clear()

        handler = RichHandler(
            console=config.rich_console,
            rich_tracebacks=True,
            show_path=False,
        )
        handler.setLevel(config.console_level)
        handler.setFormatter(
            ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    live_renderer,
                ],
            )
        )
        return handler

    # Use standard console renderer
    if processor is None:
        processor = structlog.dev.ConsoleRenderer(
            colors=config.enable_colors,
            exception_formatter=structlog.dev.RichTracebackFormatter(
                max_frames=4,
                show_locals=False,
                extra_lines=1,
            ),
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(config.console_level)
    handler.setFormatter(
        ProcessorFormatter(
            processor=processor,
            foreign_pre_chain=_get_shared_processors(
                config.verbose_enabled,
                config.add_multiproc_info,
            ),
        )
    )
    handler.addFilter(VerboseFilter(verbose_enabled=config.verbose_enabled))
    return handler


def _create_file_handler(
    log_file: Path,
    config: LoggingConfig,
    ensure_log_dir: bool = True,
) -> logging.FileHandler:
    """Create a file handler with JSON formatting.

    Args:
        log_file: Path to log file.
        config: Logging configuration.

    Returns:
        Configured file handler.
    """
    if ensure_log_dir:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        ProcessorFormatter(
            processor=JSONRenderer(),
            foreign_pre_chain=_get_shared_processors(
                config.verbose_enabled,
                config.add_multiproc_info,
            ),
        )
    )
    handler.addFilter(VerboseFilter(verbose_enabled=config.verbose_enabled))
    return handler


def _configure_structlog(config: LoggingConfig):
    """Configure structlog with standard processors.

    Args:
        config: Logging configuration.
    """
    processors = (
        _get_shared_processors(
            config.verbose_enabled,
            config.add_multiproc_info,
        )
        + config.extra_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter]
    )

    # When using Rich console, use simple BoundLogger wrapper
    # to match old setup_live_logging behavior
    if config.rich_console is not None:
        wrapper_class = structlog.stdlib.BoundLogger
    else:
        wrapper_class = structlog.make_filtering_bound_logger(logging.DEBUG)

    # Clear the logger cache to force recreation with new configuration
    # This ensures all modules get fresh loggers with the current setup
    structlog.reset_defaults()

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=wrapper_class,
        cache_logger_on_first_use=True,
    )


def _setup_root_logger(
    config: LoggingConfig,
    handlers: list[logging.Handler],
):
    """Configure the root logger with handlers.

    Args:
        config: Logging configuration.
        handlers: List of handlers to attach.
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # When using Rich console (live logging), always set to DEBUG
    # to match the old setup_live_logging behavior
    if config.rich_console is not None:
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(logging.WARNING)

    for handler in handlers:
        root_logger.addHandler(handler)

    # Set internal package loggers to appropriate levels
    if config.verbosity <= 0:
        for name in config.internal_roots:
            logging.getLogger(name).setLevel(logging.INFO)
    else:
        root_logger.setLevel(logging.DEBUG)
        for name in config.internal_roots:
            logging.getLogger(name).setLevel(logging.DEBUG)

    # Clamp external loggers to WARNING unless verbosity >= 2
    if config.verbosity < 2:
        _set_external_loggers_to_warning(config.internal_roots)


def reset_logging():
    """Reset logging configuration to a clean state.

    Clears all handlers from the root logger and resets structlog
    configuration. Useful for testing or re-initialization.
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.WARNING)

    # Reset structlog by reconfiguring with minimal setup
    structlog.reset_defaults()


def setup_live_logging(
    console: Console,
    log_dir: Path | None = None,
    verbosity: int = 0,
    log_file_name: str = "log.log",
):
    """Setup live logging for the current process.

    This function is now a convenience wrapper around setup_logging() that
    provides Rich console output. For new code, prefer using setup_logging()
    directly with the console parameter.

    Args:
        console: Rich console instance for output.
        log_dir: Optional directory for file logging.
        verbosity: Verbosity level (see setup_logging for details).
        log_file_name: Name of the log file.
    """
    setup_logging(
        console=console,
        log_dir=log_dir,
        verbosity=verbosity,
        log_file_name=log_file_name,
    )


def setup_logging(
    log_dir: Path | None = None,
    verbosity: int = 0,
    log_file_name: str = "log.log",
    extra_processors: list[Processor] | None = None,
    console: Console | None = None,
    *,
    add_multiproc_info: bool = False,
    enable_colors: bool = True,
    ensure_log_dir: bool = True,
    suppress_console: bool = False,
) -> BoundLogger | None:
    """Configure structlog + stdlib logging for the current process.

    This function supports both standard console logging and Rich-based live
    logging. When a Rich Console is provided, it uses RichHandler for enhanced
    output formatting. Use the returned logger for immediate logging, or call
    ``get_logger(__name__)`` elsewhere.

    Args:
        log_dir: Directory to write the log file into. If provided, a file
            handler is installed. When None, only console logging is used.
        verbosity: Verbosity tier — ``0`` keeps INFO for ``slop_code`` while
            third-party libraries are clamped to WARNING, ``1`` enables DEBUG
            for ``slop_code`` (and internal aliases) while leaving third-party
            libraries at WARNING, and ``>=2`` enables DEBUG for all loggers.
            Any value above zero also keeps events tagged with ``verbose=True``.
        log_file_name: Log file name, e.g. ``"log.log"``.
        enable_colors: Enable colored logging (only used when console is None).
        ensure_log_dir: Whether to ensure the log directory exists.
        extra_processors: Additional structlog processors to include.
        console: Optional Rich Console instance for live logging with enhanced
            formatting. When provided, uses RichHandler instead of standard
            console renderer.
        add_multiproc_info: Whether to add process ID and thread name to all
            log events. Useful for debugging multiprocessing/multithreading
            issues.
        suppress_console: When True, skip console handler (logs only go to file).
            Useful for quiet/JSON output modes where only the final result
            should be printed.

    Returns:
        A structlog ``BoundLogger`` instance bound to this module when using
        standard logging. Returns None when using Rich console for backward
        compatibility with setup_live_logging.
    """
    config = LoggingConfig(
        verbosity=verbosity,
        enable_colors=enable_colors,
        log_dir=log_dir,
        log_file_name=log_file_name,
        extra_processors=extra_processors or [],
        rich_console=console,
        add_multiproc_info=add_multiproc_info,
    )

    handlers: list[logging.Handler] = (
        [] if suppress_console else [_create_console_handler(config)]
    )

    if log_dir is not None:
        handlers.append(
            _create_file_handler(
                log_dir / log_file_name, config, ensure_log_dir=ensure_log_dir
            )
        )

    _setup_root_logger(config, handlers)
    _configure_structlog(config)

    # Return None when using Rich console for backward compatibility
    if console is not None:
        return None
    return structlog.get_logger(__name__)


def setup_problem_logging(
    log_dir: Path,
    problem_name: str,
    add_multiproc_info: bool = True,
    log_file_name: str | None = None,
) -> BoundLogger:
    """Configure isolated logging for a single problem execution.

    This sets up structlog + stdlib logging with only file output (no console)
    for use in multiprocessing workers. Each problem gets its own log file
    to avoid interleaved output.

    Args:
        log_dir: Directory where log file should be created.
        problem_name: Name of the problem (used for log filename if
            log_file_name is not provided).
        add_multiproc_info: Whether to add process_id and thread_name to logs.
            Set to False when using context binding for other identifiers.
        log_file_name: Optional custom log file name. If not provided,
            defaults to ``{problem_name}.log``.

    Returns:
        A structlog ``BoundLogger`` instance for this problem.
    """
    # Create logs directory if it doesn't exist
    log_dir.mkdir(parents=True, exist_ok=True)

    # Determine log file name
    actual_log_file_name = log_file_name or f"{problem_name}.log"

    # Configure with high verbosity (DEBUG) for problem logs
    config = LoggingConfig(
        verbosity=1,  # Enable DEBUG for internal packages
        log_dir=log_dir,
        log_file_name=actual_log_file_name,
        add_multiproc_info=add_multiproc_info,
    )

    # Set up file handler only (no console for multiprocessing)
    log_file = log_dir / actual_log_file_name
    file_handler = _create_file_handler(log_file, config, ensure_log_dir=True)

    # Clear and setup root logger - completely isolated logging for this worker
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)

    # Configure structlog for multiprocessing
    processors = _get_shared_processors(
        verbose_enabled=True,
        add_multiproc_info=True,
    ) + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter]

    # Clear the logger cache to force recreation with new configuration
    # This is necessary because other modules may have cached loggers
    # from a previous configuration (e.g., Rich console setup)
    structlog.reset_defaults()

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG),
        cache_logger_on_first_use=False,  # Important for multiprocessing
    )

    # Set internal package loggers to DEBUG
    for name in config.internal_roots:
        logging.getLogger(name).setLevel(logging.DEBUG)

    _set_external_loggers_to_warning(config.internal_roots)

    return structlog.get_logger(__name__)

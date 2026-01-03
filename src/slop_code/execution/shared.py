"""Shared utilities for runtime implementations.

This module provides common utilities used by both streaming and execution
runtimes across Docker and local implementations:

- **SPLIT_STRING**: Marker separating setup output from command output
- **HANDLE_ENTRY_NAME**: Name of the entry script file
- **HANDLE_ENTRY_TEMPLATE**: Template for generating entry scripts
- **split_setup_output**: Parse setup vs command output
- **write_entry_script**: Generate entry script with setup commands
"""

from pathlib import Path

from slop_code.logging import get_logger

logger = get_logger(__name__)


HANDLE_ENTRY_NAME = "HANDLE_ENTRY.sh"

SPLIT_STRING = "_____STARTING COMMAND_____"

HANDLE_ENTRY_TEMPLATE = f"""#!/bin/sh
{{setup_commands}}
echo "\n\n{SPLIT_STRING}\n" >&2
echo "\n\n{SPLIT_STRING}\n"
{{command}}
"""


def split_setup_output(
    stdout: str,
    stderr: str,
    split_string: str = SPLIT_STRING,
) -> tuple[str, str, str, str]:
    """Split output into setup and command portions.

    The output is split at the split_string marker, which is echoed
    by the entry script after setup commands complete.

    Args:
        stdout: Raw stdout output
        stderr: Raw stderr output
        split_string: Marker string to split on

    Returns:
        Tuple of (setup_stdout, stdout, setup_stderr, stderr)
    """
    try:
        *setup_stdout_parts, command_stdout = stdout.split(split_string)
        setup_stdout = "\n".join(setup_stdout_parts)
    except ValueError:
        setup_stdout = ""
        command_stdout = stdout

    try:
        *setup_stderr_parts, command_stderr = stderr.split(split_string)
        setup_stderr = "\n".join(setup_stderr_parts)
    except ValueError:
        setup_stderr = ""
        command_stderr = stderr

    return setup_stdout, command_stdout, setup_stderr, command_stderr


def format_setup_commands(setup_commands: list[str]) -> str:
    """Format setup commands for inclusion in entry script.

    Args:
        setup_commands: List of setup commands to run

    Returns:
        Formatted setup commands string or empty string if no commands
    """
    if not setup_commands:
        logger.debug("No setup commands to format", verbose=True)
        return ""
    joined = "\n".join(setup_commands)
    logger.debug(
        "Formatted setup commands",
        num_commands=len(setup_commands),
        verbose=True,
    )
    return f"{joined}\n\n"


def write_entry_script(
    working_dir: Path,
    command: str,
    setup_commands: list[str] | None = None,
) -> Path:
    """Write the entry script that handles setup + command execution.

    The entry script runs setup commands first, then echoes the SPLIT_STRING
    marker to both stdout and stderr, then runs the actual command. This
    allows output parsing to separate setup output from command output.

    Args:
        working_dir: Directory to write the script to
        command: Command to execute after setup
        setup_commands: Optional list of setup commands

    Returns:
        Path to the written entry script
    """
    script_path = working_dir / HANDLE_ENTRY_NAME
    logger.debug(
        "Writing entry script",
        script_path=script_path,
        verbose=True,
    )
    script_path.write_text(
        HANDLE_ENTRY_TEMPLATE.format(
            setup_commands=format_setup_commands(setup_commands or []),
            command=command,
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path

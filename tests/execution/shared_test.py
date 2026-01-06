"""Tests for shared execution utilities."""

from __future__ import annotations

from pathlib import Path

from slop_code.execution.shared import HANDLE_ENTRY_NAME
from slop_code.execution.shared import HANDLE_ENTRY_TEMPLATE
from slop_code.execution.shared import SPLIT_STRING
from slop_code.execution.shared import format_setup_commands
from slop_code.execution.shared import split_setup_output
from slop_code.execution.shared import write_entry_script


class TestSplitString:
    """Tests for the SPLIT_STRING constant."""

    def test_split_string_is_unique_marker(self) -> None:
        """SPLIT_STRING should be a unique marker unlikely to appear in output."""
        assert "_____STARTING COMMAND_____" in SPLIT_STRING
        assert len(SPLIT_STRING) > 10  # Reasonably long to avoid collisions


class TestFormatSetupCommands:
    """Tests for format_setup_commands function."""

    def test_empty_list_returns_empty_string(self) -> None:
        """Empty command list returns empty string."""
        result = format_setup_commands([])
        assert result == ""

    def test_single_command(self) -> None:
        """Single command is formatted correctly."""
        result = format_setup_commands(["echo hello"])
        assert result == "echo hello\n\n"

    def test_multiple_commands_joined_with_newlines(self) -> None:
        """Multiple commands are joined with newlines."""
        result = format_setup_commands(
            ["cd /app", "pip install -e .", "echo done"]
        )
        assert result == "cd /app\npip install -e .\necho done\n\n"

    def test_preserves_command_content(self) -> None:
        """Commands with special characters are preserved."""
        result = format_setup_commands(
            ['echo "hello world"', "export VAR='value'"]
        )
        assert 'echo "hello world"' in result
        assert "export VAR='value'" in result


class TestWriteEntryScript:
    """Tests for write_entry_script function."""

    def test_creates_script_file(self, tmp_path: Path) -> None:
        """Script file is created at expected path."""
        script_path = write_entry_script(tmp_path, "python main.py")
        assert script_path.exists()
        assert script_path.name == HANDLE_ENTRY_NAME

    def test_script_is_executable(self, tmp_path: Path) -> None:
        """Script has executable permissions."""
        script_path = write_entry_script(tmp_path, "python main.py")
        assert script_path.stat().st_mode & 0o111  # Has any execute bit

    def test_script_contains_shebang(self, tmp_path: Path) -> None:
        """Script starts with shell shebang."""
        script_path = write_entry_script(tmp_path, "python main.py")
        content = script_path.read_text()
        assert content.startswith("#!/bin/sh\n")

    def test_script_contains_command(self, tmp_path: Path) -> None:
        """Script contains the specified command."""
        script_path = write_entry_script(tmp_path, "python main.py --verbose")
        content = script_path.read_text()
        assert "python main.py --verbose" in content

    def test_script_echoes_split_string(self, tmp_path: Path) -> None:
        """Script echoes SPLIT_STRING to both stdout and stderr."""
        script_path = write_entry_script(tmp_path, "echo test")
        content = script_path.read_text()
        # Should echo split string to both stdout and stderr
        assert SPLIT_STRING in content
        # Should have both stdout and stderr echoes
        assert ">&2" in content  # stderr redirect present

    def test_script_with_no_setup_commands(self, tmp_path: Path) -> None:
        """Script works without setup commands."""
        script_path = write_entry_script(tmp_path, "ls -la")
        content = script_path.read_text()
        # Should still have split marker before command
        assert SPLIT_STRING in content
        assert "ls -la" in content

    def test_script_with_setup_commands(self, tmp_path: Path) -> None:
        """Script includes setup commands before split marker."""
        script_path = write_entry_script(
            tmp_path,
            "python main.py",
            setup_commands=["cd /app", "pip install -e ."],
        )
        content = script_path.read_text()
        # Setup should come before split marker
        split_idx = content.find(SPLIT_STRING)
        assert "cd /app" in content[:split_idx]
        assert "pip install -e ." in content[:split_idx]

    def test_script_command_after_split_marker(self, tmp_path: Path) -> None:
        """Main command comes after split marker."""
        script_path = write_entry_script(
            tmp_path, "python main.py", setup_commands=["echo setup"]
        )
        content = script_path.read_text()
        split_idx = content.rfind(SPLIT_STRING)
        assert "python main.py" in content[split_idx:]

    def test_overwrites_existing_script(self, tmp_path: Path) -> None:
        """Writing script overwrites any existing file."""
        script_path = tmp_path / HANDLE_ENTRY_NAME
        script_path.write_text("old content")

        write_entry_script(tmp_path, "new command")
        content = script_path.read_text()
        assert "old content" not in content
        assert "new command" in content


class TestSplitSetupOutput:
    """Tests for split_setup_output function."""

    def test_splits_stdout_at_marker(self) -> None:
        """Splits stdout at the marker."""
        stdout = f"setup output\n{SPLIT_STRING}\ncommand output"
        stderr = ""
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, stderr
        )
        assert "setup output" in setup_stdout
        assert "command output" in cmd_stdout
        assert setup_stderr == ""
        assert cmd_stderr == ""

    def test_splits_stderr_at_marker(self) -> None:
        """Splits stderr at the marker."""
        stdout = ""
        stderr = f"setup error\n{SPLIT_STRING}\ncommand error"
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, stderr
        )
        assert setup_stdout == ""
        assert cmd_stdout == ""
        assert "setup error" in setup_stderr
        assert "command error" in cmd_stderr

    def test_splits_both_stdout_and_stderr(self) -> None:
        """Splits both stdout and stderr independently."""
        stdout = f"setup out\n{SPLIT_STRING}\ncmd out"
        stderr = f"setup err\n{SPLIT_STRING}\ncmd err"
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, stderr
        )
        assert "setup out" in setup_stdout
        assert "cmd out" in cmd_stdout
        assert "setup err" in setup_stderr
        assert "cmd err" in cmd_stderr

    def test_no_marker_returns_all_as_command_output(self) -> None:
        """Without marker, all output is command output."""
        stdout = "just command output"
        stderr = "just command error"
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, stderr
        )
        assert setup_stdout == ""
        assert cmd_stdout == "just command output"
        assert setup_stderr == ""
        assert cmd_stderr == "just command error"

    def test_empty_output(self) -> None:
        """Handles empty output gracefully."""
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            "", ""
        )
        assert setup_stdout == ""
        assert cmd_stdout == ""
        assert setup_stderr == ""
        assert cmd_stderr == ""

    def test_marker_at_start(self) -> None:
        """Handles marker at the very start."""
        stdout = f"{SPLIT_STRING}\ncommand output"
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, ""
        )
        assert setup_stdout == ""
        assert "command output" in cmd_stdout

    def test_marker_at_end(self) -> None:
        """Handles marker at the very end."""
        stdout = f"setup output\n{SPLIT_STRING}"
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, ""
        )
        assert "setup output" in setup_stdout
        assert cmd_stdout == ""

    def test_multiple_markers_uses_last(self) -> None:
        """When multiple markers exist, split at last occurrence."""
        stdout = f"first\n{SPLIT_STRING}\nmiddle\n{SPLIT_STRING}\nlast"
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, ""
        )
        # Everything before the last marker should be in setup
        assert "first" in setup_stdout
        assert "middle" in setup_stdout
        assert cmd_stdout.strip() == "last"

    def test_custom_split_string(self) -> None:
        """Can use custom split string."""
        custom_marker = "===CUSTOM==="
        stdout = f"setup\n{custom_marker}\ncommand"
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, "", split_string=custom_marker
        )
        assert "setup" in setup_stdout
        assert "command" in cmd_stdout

    def test_preserves_whitespace_in_output(self) -> None:
        """Whitespace in output is preserved."""
        stdout = (
            f"  setup with spaces  \n{SPLIT_STRING}\n  command with spaces  "
        )
        setup_stdout, cmd_stdout, setup_stderr, cmd_stderr = split_setup_output(
            stdout, ""
        )
        assert "  setup with spaces  " in setup_stdout
        assert "  command with spaces  " in cmd_stdout


class TestHandleEntryTemplate:
    """Tests for the entry script template."""

    def test_template_has_placeholders(self) -> None:
        """Template contains expected placeholders."""
        assert "{setup_commands}" in HANDLE_ENTRY_TEMPLATE
        assert "{command}" in HANDLE_ENTRY_TEMPLATE

    def test_template_format_works(self) -> None:
        """Template can be formatted with values."""
        result = HANDLE_ENTRY_TEMPLATE.format(
            setup_commands="echo setup\n\n", command="echo main"
        )
        assert "echo setup" in result
        assert "echo main" in result
        assert SPLIT_STRING in result

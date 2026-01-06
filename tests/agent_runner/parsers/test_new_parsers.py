"""Tests for the new simplified trajectory parsers."""

from pathlib import Path

import pytest

from slop_code.agent_runner.trajectory import (
    AgentStep,
    ThinkingStep,
    ToolUseStep,
    Trajectory,
    UserStep,
)
from slop_code.agent_runner.trajectory_parsing import (
    parse_trajectory,
    ParseError,
)
from slop_code.agent_runner.agents.claude_code.parser import ClaudeCodeParser
from slop_code.agent_runner.agents.codex.parser import CodexParser
from slop_code.agent_runner.agents.gemini.parser import GeminiParser
from slop_code.agent_runner.agents.miniswe.parser import MinisweParser
from slop_code.agent_runner.agents.opencode.parser import OpenCodeParser
from slop_code.agent_runner.agents.openhands.parser import OpenHandsParser


# Path to test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestClaudeCodeParser:
    """Tests for ClaudeCodeParser."""

    def test_can_parse_claude_code_file(self, tmp_path: Path) -> None:
        """Test detection of Claude Code trajectory format."""
        # Create a minimal Claude Code trajectory
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "system", "subtype": "init", "model": "test"}\n'
        )

        parser = ClaudeCodeParser()
        assert parser.can_parse(tmp_path) is True

    def test_cannot_parse_non_claude_file(self, tmp_path: Path) -> None:
        """Test rejection of non-Claude Code files."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"type": "thread.started"}\n')

        parser = ClaudeCodeParser()
        assert parser.can_parse(tmp_path) is False

    def test_parse_thinking_step(self, tmp_path: Path) -> None:
        """Test parsing thinking blocks."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "system", "subtype": "init", "model": "test"}\n'
            '{"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Let me think..."}]}}\n'
        )

        parser = ClaudeCodeParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ThinkingStep)
        assert traj.steps[0].content == "Let me think..."

    def test_parse_agent_step(self, tmp_path: Path) -> None:
        """Test parsing text blocks."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "system", "subtype": "init", "model": "test"}\n'
            '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello!"}]}}\n'
        )

        parser = ClaudeCodeParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], AgentStep)
        assert traj.steps[0].content == "Hello!"

    def test_parse_tool_use_step(self, tmp_path: Path) -> None:
        """Test parsing tool_use blocks with results."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "system", "subtype": "init", "model": "test"}\n'
            '{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "tool1", "name": "Bash", "input": {"command": "ls"}}]}}\n'
            '{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tool1", "content": "file1.txt\\nfile2.txt"}]}}\n'
        )

        parser = ClaudeCodeParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ToolUseStep)
        assert traj.steps[0].type == "Bash"
        assert traj.steps[0].arguments == {"command": "ls"}
        assert traj.steps[0].result == "file1.txt\nfile2.txt"

    def test_parse_metadata(self, tmp_path: Path) -> None:
        """Test metadata extraction from init event."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "system", "subtype": "init", "model": "claude-3", "tools": ["Bash", "Read"], "session_id": "abc123"}\n'
        )

        parser = ClaudeCodeParser()
        traj = parser.parse(tmp_path)

        assert traj.metadata["model"] == "claude-3"
        assert traj.metadata["tools"] == ["Bash", "Read"]
        assert traj.metadata["session_id"] == "abc123"


class TestCodexParser:
    """Tests for CodexParser."""

    def test_can_parse_codex_file(self, tmp_path: Path) -> None:
        """Test detection of Codex trajectory format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"type": "thread.started", "thread_id": "abc"}\n')

        parser = CodexParser()
        assert parser.can_parse(tmp_path) is True

    def test_cannot_parse_non_codex_file(self, tmp_path: Path) -> None:
        """Test rejection of non-Codex files."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"type": "system", "subtype": "init"}\n')

        parser = CodexParser()
        assert parser.can_parse(tmp_path) is False

    def test_parse_reasoning_step(self, tmp_path: Path) -> None:
        """Test parsing reasoning items."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "thread.started", "thread_id": "abc"}\n'
            '{"type": "item.completed", "item": {"type": "reasoning", "text": "Thinking about it..."}}\n'
        )

        parser = CodexParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ThinkingStep)
        assert traj.steps[0].content == "Thinking about it..."

    def test_parse_command_execution_step(self, tmp_path: Path) -> None:
        """Test parsing command_execution items."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "thread.started", "thread_id": "abc"}\n'
            '{"type": "item.completed", "item": {"type": "command_execution", "command": "/bin/bash -lc ls", "aggregated_output": "file.txt", "exit_code": 0}}\n'
        )

        parser = CodexParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ToolUseStep)
        assert traj.steps[0].type == "bash"
        assert traj.steps[0].arguments["command"] == "ls"
        assert traj.steps[0].result == "file.txt"

    def test_parse_agent_message_step(self, tmp_path: Path) -> None:
        """Test parsing agent_message items."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "thread.started", "thread_id": "abc"}\n'
            '{"type": "item.completed", "item": {"type": "agent_message", "text": "Done!"}}\n'
        )

        parser = CodexParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], AgentStep)
        assert traj.steps[0].content == "Done!"


class TestOpenCodeParser:
    """Tests for OpenCodeParser."""

    def test_can_parse_opencode_file(self, tmp_path: Path) -> None:
        """Test detection of OpenCode trajectory format."""
        jsonl = tmp_path / "messages.jsonl"
        jsonl.write_text('{"type": "step_start"}\n')

        parser = OpenCodeParser()
        assert parser.can_parse(tmp_path) is True

    def test_cannot_parse_non_opencode_file(self, tmp_path: Path) -> None:
        """Test rejection of non-OpenCode files."""
        jsonl = tmp_path / "messages.jsonl"
        jsonl.write_text('{"type": "system", "subtype": "init"}\n')

        parser = OpenCodeParser()
        assert parser.can_parse(tmp_path) is False

    def test_parse_text_step(self, tmp_path: Path) -> None:
        """Test parsing text events."""
        jsonl = tmp_path / "messages.jsonl"
        jsonl.write_text(
            '{"type": "step_start"}\n'
            '{"type": "text", "part": {"text": "Hello world"}}\n'
        )

        parser = OpenCodeParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], AgentStep)
        assert traj.steps[0].content == "Hello world"

    def test_parse_tool_use_step(self, tmp_path: Path) -> None:
        """Test parsing tool_use events."""
        jsonl = tmp_path / "messages.jsonl"
        jsonl.write_text(
            '{"type": "step_start"}\n'
            '{"type": "tool_use", "part": {"tool": "read", "state": {"input": {"filePath": "/test.py"}, "output": "content"}}}\n'
        )

        parser = OpenCodeParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ToolUseStep)
        assert traj.steps[0].type == "read"
        assert traj.steps[0].arguments == {"filePath": "/test.py"}
        assert traj.steps[0].result == "content"


class TestParseTrajectory:
    """Tests for the auto-detect parse_trajectory function."""

    def test_auto_detect_claude_code(self, tmp_path: Path) -> None:
        """Test auto-detection of Claude Code format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "system", "subtype": "init", "model": "test"}\n'
            '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}}\n'
        )

        traj = parse_trajectory(tmp_path)
        assert traj.agent_type == "claude_code"

    def test_auto_detect_codex(self, tmp_path: Path) -> None:
        """Test auto-detection of Codex format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "thread.started", "thread_id": "abc"}\n'
            '{"type": "item.completed", "item": {"type": "agent_message", "text": "Hi"}}\n'
        )

        traj = parse_trajectory(tmp_path)
        assert traj.agent_type == "codex"

    def test_auto_detect_opencode(self, tmp_path: Path) -> None:
        """Test auto-detection of OpenCode format."""
        jsonl = tmp_path / "messages.jsonl"
        jsonl.write_text(
            '{"type": "step_start"}\n{"type": "text", "part": {"text": "Hi"}}\n'
        )

        traj = parse_trajectory(tmp_path)
        assert traj.agent_type == "opencode"

    def test_raises_on_unknown_format(self, tmp_path: Path) -> None:
        """Test error on unrecognized format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"unknown": "format"}\n')

        with pytest.raises(ParseError):
            parse_trajectory(tmp_path)

    def test_raises_on_nonexistent_path(self, tmp_path: Path) -> None:
        """Test error on nonexistent path."""
        with pytest.raises(ValueError):
            parse_trajectory(tmp_path / "nonexistent")


class TestGeminiParser:
    """Tests for GeminiParser."""

    def test_can_parse_gemini_file(self, tmp_path: Path) -> None:
        """Test detection of Gemini trajectory format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"type": "init", "model": "gemini-pro"}\n')

        parser = GeminiParser()
        assert parser.can_parse(tmp_path) is True

    def test_cannot_parse_non_gemini_file(self, tmp_path: Path) -> None:
        """Test rejection of non-Gemini files."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"type": "thread.started"}\n')

        parser = GeminiParser()
        assert parser.can_parse(tmp_path) is False

    def test_parse_tool_use_message(self, tmp_path: Path) -> None:
        """Test parsing tool_use from message event."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "init", "model": "gemini-pro"}\n'
            '{"type": "message", "role": "assistant", "content": {"tool_use": {"id": "t1", "name": "execute_bash", "input": {"cmd": "ls"}}}}\n'
            '{"type": "message", "role": "user", "content": {"tool_result": {"tool_use_id": "t1", "content": "file.txt"}}}\n'
        )

        parser = GeminiParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ToolUseStep)
        assert traj.steps[0].type == "execute_bash"
        assert traj.steps[0].result == "file.txt"

    def test_parse_standalone_tool_events(self, tmp_path: Path) -> None:
        """Test parsing standalone tool_use and tool_result events."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "init", "model": "gemini-pro"}\n'
            '{"type": "tool_use", "id": "t1", "name": "read_file", "input": {"path": "/test.py"}}\n'
            '{"type": "tool_result", "tool_use_id": "t1", "content": "print(hello)"}\n'
        )

        parser = GeminiParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ToolUseStep)
        assert traj.steps[0].type == "read_file"
        assert traj.steps[0].result == "print(hello)"

    def test_parse_text_message(self, tmp_path: Path) -> None:
        """Test parsing text from assistant message."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "init", "model": "gemini-pro"}\n'
            '{"type": "message", "role": "assistant", "content": {"text": "Hello!"}}\n'
        )

        parser = GeminiParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], AgentStep)
        assert traj.steps[0].content == "Hello!"

    def test_parse_metadata(self, tmp_path: Path) -> None:
        """Test metadata extraction from init event."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"type": "init", "model": "gemini-1.5-pro"}\n')

        parser = GeminiParser()
        traj = parser.parse(tmp_path)

        assert traj.metadata["model"] == "gemini-1.5-pro"


class TestMinisweParser:
    """Tests for MinisweParser."""

    def test_can_parse_miniswe_file(self, tmp_path: Path) -> None:
        """Test detection of MiniSWE trajectory format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"role": "system", "content": "You are an assistant"}\n'
        )

        parser = MinisweParser()
        assert parser.can_parse(tmp_path) is True

    def test_cannot_parse_non_miniswe_file(self, tmp_path: Path) -> None:
        """Test rejection of non-MiniSWE files."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text('{"type": "init", "model": "gemini"}\n')

        parser = MinisweParser()
        assert parser.can_parse(tmp_path) is False

    def test_parse_thought_block(self, tmp_path: Path) -> None:
        """Test parsing THOUGHT blocks."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"role": "system", "content": "System prompt"}\n'
            '{"role": "assistant", "content": "THOUGHT: Let me analyze this problem carefully."}\n'
        )

        parser = MinisweParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ThinkingStep)
        assert "analyze this problem" in traj.steps[0].content

    def test_parse_bash_command(self, tmp_path: Path) -> None:
        """Test parsing bash commands."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"role": "system", "content": "System prompt"}\n'
            '{"role": "assistant", "content": "THOUGHT: Check files\\n\\n```bash\\nls -la\\n```"}\n'
            '{"role": "environment", "content": "total 8\\nfile1.txt\\nfile2.txt"}\n'
        )

        parser = MinisweParser()
        traj = parser.parse(tmp_path)

        # Should have thinking + tool use
        assert len(traj.steps) == 2
        assert isinstance(traj.steps[0], ThinkingStep)
        assert isinstance(traj.steps[1], ToolUseStep)
        assert traj.steps[1].type == "bash"
        assert traj.steps[1].arguments["command"] == "ls -la"
        assert "file1.txt" in traj.steps[1].result

    def test_parse_user_message(self, tmp_path: Path) -> None:
        """Test parsing user messages."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"role": "system", "content": "System prompt"}\n'
            '{"role": "user", "content": "Please fix the bug"}\n'
        )

        parser = MinisweParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], UserStep)
        assert traj.steps[0].content == "Please fix the bug"


class TestOpenHandsParser:
    """Tests for OpenHandsParser."""

    def test_can_parse_openhands_json(self, tmp_path: Path) -> None:
        """Test detection of OpenHands trajectory.json format."""
        import json

        traj_file = tmp_path / "trajectory.json"
        traj_file.write_text(
            json.dumps(
                [
                    {
                        "source": "agent",
                        "action": "message",
                        "args": {"content": "Hi"},
                    },
                    {"llm_metrics": {"accumulated_cost": 0.01}},
                ]
            )
        )

        parser = OpenHandsParser()
        assert parser.can_parse(tmp_path) is True

    def test_cannot_parse_non_openhands_file(self, tmp_path: Path) -> None:
        """Test rejection of non-OpenHands files."""
        import json

        traj_file = tmp_path / "trajectory.json"
        traj_file.write_text(json.dumps({"type": "init"}))

        parser = OpenHandsParser()
        assert parser.can_parse(tmp_path) is False

    def test_parse_bash_action(self, tmp_path: Path) -> None:
        """Test parsing bash execution."""
        import json

        traj_file = tmp_path / "trajectory.json"
        traj_file.write_text(
            json.dumps(
                [
                    {
                        "source": "agent",
                        "action": "run",
                        "args": {"command": "ls -la"},
                        "message": "",
                    },
                    {
                        "source": "environment",
                        "action": "observation",
                        "args": {"content": "file1.txt"},
                        "message": "",
                    },
                ]
            )
        )

        parser = OpenHandsParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ToolUseStep)
        assert traj.steps[0].type == "bash"
        assert traj.steps[0].arguments["command"] == "ls -la"
        assert traj.steps[0].result == "file1.txt"

    def test_parse_edit_action(self, tmp_path: Path) -> None:
        """Test parsing file edit."""
        import json

        traj_file = tmp_path / "trajectory.json"
        traj_file.write_text(
            json.dumps(
                [
                    {
                        "source": "agent",
                        "action": "edit",
                        "args": {"path": "/test.py", "content": "print(1)"},
                        "message": "",
                    },
                ]
            )
        )

        parser = OpenHandsParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], ToolUseStep)
        assert traj.steps[0].type == "edit"
        assert traj.steps[0].arguments["path"] == "/test.py"

    def test_parse_agent_message(self, tmp_path: Path) -> None:
        """Test parsing agent message."""
        import json

        traj_file = tmp_path / "trajectory.json"
        traj_file.write_text(
            json.dumps(
                [
                    {
                        "source": "agent",
                        "action": "message",
                        "args": {"content": "Task completed!"},
                        "message": "",
                    },
                ]
            )
        )

        parser = OpenHandsParser()
        traj = parser.parse(tmp_path)

        assert len(traj.steps) == 1
        assert isinstance(traj.steps[0], AgentStep)
        assert traj.steps[0].content == "Task completed!"

    def test_parse_metadata(self, tmp_path: Path) -> None:
        """Test metadata extraction from llm_metrics."""
        import json

        traj_file = tmp_path / "trajectory.json"
        traj_file.write_text(
            json.dumps(
                [
                    {
                        "source": "agent",
                        "action": "message",
                        "args": {"content": "Hi"},
                        "message": "",
                    },
                    {
                        "source": "agent",
                        "llm_metrics": {
                            "accumulated_cost": 0.05,
                            "accumulated_token_usage": {
                                "prompt_tokens": 1000,
                                "completion_tokens": 500,
                            },
                        },
                    },
                ]
            )
        )

        parser = OpenHandsParser()
        traj = parser.parse(tmp_path)

        assert traj.metadata["accumulated_cost"] == 0.05
        assert traj.metadata["total_tokens"]["input"] == 1000
        assert traj.metadata["total_tokens"]["output"] == 500

    def test_auto_detect_openhands(self, tmp_path: Path) -> None:
        """Test auto-detection of OpenHands format."""
        import json

        traj_file = tmp_path / "trajectory.json"
        traj_file.write_text(
            json.dumps(
                [
                    {
                        "source": "agent",
                        "action": "message",
                        "args": {"content": "Hello"},
                        "message": "",
                    },
                ]
            )
        )

        traj = parse_trajectory(tmp_path)
        assert traj.agent_type == "openhands"


class TestAutoDetectNewParsers:
    """Test auto-detection for all new parsers."""

    def test_auto_detect_gemini(self, tmp_path: Path) -> None:
        """Test auto-detection of Gemini format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"type": "init", "model": "gemini-pro"}\n'
            '{"type": "message", "role": "assistant", "content": {"text": "Hi"}}\n'
        )

        traj = parse_trajectory(tmp_path)
        assert traj.agent_type == "gemini"

    def test_auto_detect_miniswe(self, tmp_path: Path) -> None:
        """Test auto-detection of MiniSWE format."""
        jsonl = tmp_path / "stdout.jsonl"
        jsonl.write_text(
            '{"role": "system", "content": "System"}\n'
            '{"role": "assistant", "content": "Hello"}\n'
        )

        traj = parse_trajectory(tmp_path)
        assert traj.agent_type == "miniswe"

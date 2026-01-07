"""Helper functions for parser tests using real trajectory data."""

from __future__ import annotations


def get_claude_init() -> dict:
    """Get realistic Claude Code init message."""
    return {
        "type": "system",
        "subtype": "init",
        "cwd": "/workspace",
        "session_id": "test-session-id",
        "tools": ["Task", "Bash", "Read", "Edit", "Write"],
        "model": "claude-3-sonnet-4-20250514",
    }


def get_claude_thinking() -> dict:
    """Get realistic Claude Code thinking message."""
    return {
        "type": "assistant",
        "message": {
            "model": "claude-3-sonnet-4-20250514",
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "thinking",
                    "thinking": "I need to read the file first.",
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 20},
        },
        "parent_tool_use_id": None,
        "session_id": "test-session-id",
    }


def get_claude_tool_use(
    tool_id: str = "tool_test", tool_name: str = "Read"
) -> dict:
    """Get realistic Claude Code tool_use message."""
    return {
        "type": "assistant",
        "message": {
            "model": "claude-3-sonnet-4-20250514",
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": {"file_path": "test.txt"},
                }
            ],
            "usage": {"input_tokens": 15, "output_tokens": 25},
        },
        "parent_tool_use_id": None,
        "session_id": "test-session-id",
    }


def get_claude_tool_result(
    tool_use_id: str = "tool_test", content: str = "File content"
) -> dict:
    """Get realistic Claude Code tool_result message."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                    "is_error": False,
                }
            ],
        },
        "parent_tool_use_id": None,
        "session_id": "test-session-id",
    }


def get_codex_thread_started() -> dict:
    """Get realistic Codex thread.started message."""
    return {"type": "thread.started", "thread_id": "test-thread-id"}


def get_codex_turn_started() -> dict:
    """Get realistic Codex turn.started message."""
    return {"type": "turn.started"}


def get_codex_reasoning(text: str = "I need to analyze the code") -> dict:
    """Get realistic Codex reasoning message."""
    return {
        "type": "item.completed",
        "item": {"id": "item_0", "type": "reasoning", "text": text},
    }


def get_codex_command(
    command: str = "ls -la", exit_code: int = 0, output: str = ""
) -> dict:
    """Get realistic Codex command execution messages."""
    return [
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": f"/bin/bash -lc {command}",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": f"/bin/bash -lc {command}",
                "aggregated_output": output,
                "exit_code": exit_code,
                "status": "completed",
            },
        },
    ]


def get_codex_turn_complete() -> dict:
    """Get realistic Codex turn.completed message."""
    return {
        "type": "turn.completed",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def get_opencode_step_start() -> dict:
    """Get realistic OpenCode step_start message."""
    return {
        "type": "step_start",
        "timestamp": 1234567890000,
        "sessionID": "test_session",
        "part": {
            "id": "prt_test",
            "sessionID": "test_session",
            "messageID": "msg_test",
            "type": "step-start",
        },
    }


def get_opencode_step_finish(
    reason: str = "tool-calls", tokens: dict = None
) -> dict:
    """Get realistic OpenCode step_finish message."""
    part = {
        "id": "prt_test",
        "sessionID": "test_session",
        "messageID": "msg_test",
        "type": "step-finish",
        "reason": reason,
    }
    if tokens:
        part["tokens"] = tokens

    return {
        "type": "step_finish",
        "timestamp": 1234567891000,
        "sessionID": "test_session",
        "part": part,
    }


def get_gemini_init() -> dict:
    """Get realistic Gemini init message."""
    return {"type": "init", "model": "gemini-1.5-pro"}


def get_gemini_result() -> dict:
    """Get realistic Gemini result message."""
    return {
        "type": "result",
        "stats": {"input_tokens": 100, "output_tokens": 50},
    }


def get_gemini_assistant(content: list) -> dict:
    """Get realistic Gemini assistant message."""
    return {
        "type": "message",
        "role": "assistant",
        "content": content,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def get_gemini_user(content: list) -> dict:
    """Get realistic Gemini user message."""
    return {"type": "message", "role": "user", "content": content}


def get_openhand_entry() -> dict:
    """Get realistic OpenHands trajectory entry."""
    return {
        "id": 0,
        "timestamp": "2025-01-01T12:00:00.000000",
        "source": "agent",
        "message": "Test message",
        "action": "test",
        "args": {"content": "Test"},
        "tools": [],
    }

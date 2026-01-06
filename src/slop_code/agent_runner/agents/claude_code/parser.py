"""Claude Code trajectory parser."""

from __future__ import annotations

import json
from pathlib import Path

from slop_code.agent_runner.trajectory import (
    AgentStep,
    ThinkingStep,
    ToolUseStep,
    Trajectory,
    TrajectoryStep,
)
from slop_code.agent_runner.trajectory_parsing import ParseError, TrajectoryParser


class ClaudeCodeParser(TrajectoryParser):
    """Parser for Claude Code trajectory format."""

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if directory contains Claude Code trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            return False

        try:
            with open(jsonl_file) as f:
                first_line = f.readline()
                if not first_line:
                    return False
                data = json.loads(first_line)
                # Claude Code starts with system init event
                return data.get("type") == "system" and data.get("subtype") == "init"
        except (json.JSONDecodeError, OSError):
            return False

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse Claude Code trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            raise ParseError(f"No JSONL file found in {artifact_dir}")

        steps: list[TrajectoryStep] = []
        metadata: dict = {}
        pending_tool_uses: dict[str, int] = {}  # tool_use_id -> step index

        with open(jsonl_file) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError as e:
                    raise ParseError(f"Invalid JSON at line {line_num}: {e}")

                event_type = event.get("type")

                if event_type == "system" and event.get("subtype") == "init":
                    # Extract metadata from init event
                    metadata = {
                        "model": event.get("model"),
                        "tools": event.get("tools", []),
                        "session_id": event.get("session_id"),
                        "cwd": event.get("cwd"),
                    }

                elif event_type == "assistant":
                    # Process assistant message content blocks
                    message = event.get("message", {})
                    content_blocks = message.get("content", [])

                    for block in content_blocks:
                        block_type = block.get("type")

                        if block_type == "thinking":
                            thinking_text = block.get("thinking", "")
                            if thinking_text:
                                steps.append(ThinkingStep(content=thinking_text))

                        elif block_type == "text":
                            text = block.get("text", "")
                            if text:
                                steps.append(AgentStep(content=text))

                        elif block_type == "tool_use":
                            tool_id = block.get("id", "")
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})

                            step = ToolUseStep(
                                type=tool_name,
                                arguments=tool_input,
                                result=None,
                            )
                            steps.append(step)
                            # Track index for later result matching
                            if tool_id:
                                pending_tool_uses[tool_id] = len(steps) - 1

                elif event_type == "user":
                    # Process tool results
                    message = event.get("message", {})
                    content_blocks = message.get("content", [])

                    for block in content_blocks:
                        if block.get("type") == "tool_result":
                            tool_use_id = block.get("tool_use_id", "")
                            result_content = block.get("content", "")

                            # Match to pending tool use and update result
                            if tool_use_id in pending_tool_uses:
                                idx = pending_tool_uses.pop(tool_use_id)
                                old_step = steps[idx]
                                if isinstance(old_step, ToolUseStep):
                                    steps[idx] = ToolUseStep(
                                        type=old_step.type,
                                        arguments=old_step.arguments,
                                        result=result_content,
                                        timestamp=old_step.timestamp,
                                    )

        return Trajectory(
            agent_type="claude_code",
            steps=steps,
            metadata=metadata,
        )

    def _find_jsonl_file(self, artifact_dir: Path) -> Path | None:
        """Find the JSONL trajectory file."""
        # Check if artifact_dir itself is a file
        if artifact_dir.is_file() and artifact_dir.suffix == ".jsonl":
            return artifact_dir

        # Check for stdout.jsonl first (common location)
        stdout_file = artifact_dir / "stdout.jsonl"
        if stdout_file.exists():
            return stdout_file

        # Check for any .jsonl file
        jsonl_files = list(artifact_dir.glob("*.jsonl"))
        if jsonl_files:
            return jsonl_files[0]

        return None

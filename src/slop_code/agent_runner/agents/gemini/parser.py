"""Gemini trajectory parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slop_code.agent_runner.trajectory import (
    AgentStep,
    ToolUseStep,
    Trajectory,
    TrajectoryStep,
)
from slop_code.agent_runner.trajectory_parsing import (
    ParseError,
    TrajectoryParser,
)


class GeminiParser(TrajectoryParser):
    """Parser for Gemini trajectory format."""

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if directory contains Gemini trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            return False

        try:
            with open(jsonl_file) as f:
                first_line = f.readline().strip()
                if not first_line:
                    return False
                data = json.loads(first_line)
                # Gemini starts with init or has result events
                return data.get("type") in ("init", "result")
        except (json.JSONDecodeError, OSError):
            return False

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse Gemini trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            raise ParseError(f"No JSONL file found in {artifact_dir}")

        steps: list[TrajectoryStep] = []
        metadata: dict[str, Any] = {}

        # Track pending tool calls to match with results
        pending_tools: dict[str, ToolUseStep] = {}

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

                if event_type == "init":
                    if "model" in event:
                        metadata["model"] = event["model"]

                elif event_type == "message":
                    self._process_message(event, steps, pending_tools)

                elif event_type == "tool_use":
                    self._process_tool_use(event, steps, pending_tools)

                elif event_type == "tool_result":
                    self._process_tool_result(event, pending_tools)

        return Trajectory(
            agent_type="gemini",
            steps=steps,
            metadata=metadata,
        )

    def _process_message(
        self,
        event: dict[str, Any],
        steps: list[TrajectoryStep],
        pending_tools: dict[str, ToolUseStep],
    ) -> None:
        """Process message event."""
        role = event.get("role", "")
        content = event.get("content", {})

        if role == "assistant":
            # Check for tool_use in content
            tool_use = content.get("tool_use")
            if tool_use:
                tool_name = tool_use.get("name", "unknown")
                tool_input = tool_use.get("input", {})
                tool_id = tool_use.get("id", "")

                step = ToolUseStep(
                    type=tool_name,
                    arguments=tool_input,
                    result=None,
                )
                steps.append(step)
                if tool_id:
                    pending_tools[tool_id] = step
            else:
                # Text content
                text = content.get("text", "")
                if text:
                    steps.append(AgentStep(content=text))

        elif role == "user":
            # Check for tool_result in content
            tool_result = content.get("tool_result")
            if tool_result:
                tool_id = tool_result.get("tool_use_id", "")
                result_content = tool_result.get("content", "")
                if tool_id in pending_tools:
                    pending_tools[tool_id].result = result_content
                    del pending_tools[tool_id]

    def _process_tool_use(
        self,
        event: dict[str, Any],
        steps: list[TrajectoryStep],
        pending_tools: dict[str, ToolUseStep],
    ) -> None:
        """Process standalone tool_use event."""
        tool_name = event.get("name", "unknown")
        tool_input = event.get("input", {})
        tool_id = event.get("id", "")

        step = ToolUseStep(
            type=tool_name,
            arguments=tool_input,
            result=None,
        )
        steps.append(step)
        if tool_id:
            pending_tools[tool_id] = step

    def _process_tool_result(
        self,
        event: dict[str, Any],
        pending_tools: dict[str, ToolUseStep],
    ) -> None:
        """Process standalone tool_result event."""
        tool_id = event.get("tool_use_id", "")
        result_content = event.get("content", "")

        if tool_id in pending_tools:
            pending_tools[tool_id].result = result_content
            del pending_tools[tool_id]

    def _find_jsonl_file(self, artifact_dir: Path) -> Path | None:
        """Find the JSONL trajectory file."""
        if artifact_dir.is_file() and artifact_dir.suffix == ".jsonl":
            return artifact_dir

        # Check for stdout.jsonl (Gemini's common location)
        stdout_file = artifact_dir / "stdout.jsonl"
        if stdout_file.exists():
            return stdout_file

        # Check for messages.jsonl as fallback
        messages_file = artifact_dir / "messages.jsonl"
        if messages_file.exists():
            return messages_file

        # Check for any .jsonl file
        jsonl_files = list(artifact_dir.glob("*.jsonl"))
        if jsonl_files:
            return jsonl_files[0]

        return None

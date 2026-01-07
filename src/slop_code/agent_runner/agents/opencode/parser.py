"""OpenCode trajectory parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slop_code.agent_runner.trajectory import AgentStep
from slop_code.agent_runner.trajectory import ToolUseStep
from slop_code.agent_runner.trajectory import Trajectory
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.agent_runner.trajectory_parsing import ParseError
from slop_code.agent_runner.trajectory_parsing import TrajectoryParser


class OpenCodeParser(TrajectoryParser):
    """Parser for OpenCode trajectory format."""

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if directory contains OpenCode trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            return False

        try:
            with open(jsonl_file) as f:
                # Look for step_start or step_finish events in first few lines
                for i, line in enumerate(f):
                    if i > 10:  # Only check first 10 lines
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("type") in ("step_start", "step_finish"):
                            return True
                    except json.JSONDecodeError:
                        continue
                return False
        except OSError:
            return False

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse OpenCode trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            raise ParseError(f"No JSONL file found in {artifact_dir}")

        steps: list[TrajectoryStep] = []
        metadata: dict[str, Any] = {}

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

                if event_type == "text":
                    part = event.get("part", {})
                    text = part.get("text", "")
                    if text:
                        steps.append(AgentStep(content=text))

                elif event_type == "tool_use":
                    part = event.get("part", {})
                    tool_name = part.get("tool", "")
                    state = part.get("state", {})
                    tool_input = state.get("input", {})
                    tool_output = state.get("output", "")

                    steps.append(
                        ToolUseStep(
                            type=tool_name,
                            arguments=tool_input,
                            result=tool_output,
                        )
                    )

                # Extract session metadata from any event that has it
                if "sessionID" in event and "session_id" not in metadata:
                    metadata["session_id"] = event["sessionID"]

        return Trajectory(
            agent_type="opencode",
            steps=steps,
            metadata=metadata,
        )

    def _find_jsonl_file(self, artifact_dir: Path) -> Path | None:
        """Find the JSONL trajectory file."""
        # Check if artifact_dir itself is a file
        if artifact_dir.is_file() and artifact_dir.suffix == ".jsonl":
            return artifact_dir

        # Check for messages.jsonl first (OpenCode's common location)
        messages_file = artifact_dir / "messages.jsonl"
        if messages_file.exists():
            return messages_file

        # Check for stdout.jsonl as fallback
        stdout_file = artifact_dir / "stdout.jsonl"
        if stdout_file.exists():
            return stdout_file

        # Check for any .jsonl file
        jsonl_files = list(artifact_dir.glob("*.jsonl"))
        if jsonl_files:
            return jsonl_files[0]

        return None

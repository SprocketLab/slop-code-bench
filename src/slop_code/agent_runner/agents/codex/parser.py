"""Codex trajectory parser."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from slop_code.agent_runner.trajectory import (
    AgentStep,
    ThinkingStep,
    ToolUseStep,
    Trajectory,
    TrajectoryStep,
)
from slop_code.agent_runner.trajectory_parsing import (
    ParseError,
    TrajectoryParser,
)


class CodexParser(TrajectoryParser):
    """Parser for Codex trajectory format."""

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if directory contains Codex trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            return False

        try:
            with open(jsonl_file) as f:
                first_line = f.readline()
                if not first_line:
                    return False
                data = json.loads(first_line)
                # Codex starts with thread.started or turn.started
                return data.get("type") in ("thread.started", "turn.started")
        except (json.JSONDecodeError, OSError):
            return False

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse Codex trajectory."""
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

                if event_type == "thread.started":
                    # Extract metadata
                    metadata["thread_id"] = event.get("thread_id")
                    if "model" in event:
                        metadata["model"] = event["model"]

                elif event_type == "item.completed":
                    self._process_item(event, steps)

        return Trajectory(
            agent_type="codex",
            steps=steps,
            metadata=metadata,
        )

    def _process_item(
        self, event: dict[str, Any], steps: list[TrajectoryStep]
    ) -> None:
        """Process item.completed event."""
        item = event.get("item", {})
        item_type = item.get("type")

        if item_type == "reasoning":
            text = item.get("text", "")
            if text:
                steps.append(ThinkingStep(content=text))

        elif item_type == "command_execution":
            command = item.get("command", "")
            unwrapped = self._unwrap_bash_command(command)
            output = item.get("aggregated_output", "")
            exit_code = item.get("exit_code")

            steps.append(
                ToolUseStep(
                    type="bash",
                    arguments={"command": unwrapped, "exit_code": exit_code},
                    result=output,
                )
            )

        elif item_type == "file_change":
            changes = item.get("changes", [])
            steps.append(
                ToolUseStep(
                    type="file_change",
                    arguments={"changes": changes},
                    result=None,
                )
            )

        elif item_type == "agent_message":
            text = item.get("text", "")
            if text:
                steps.append(AgentStep(content=text))

    def _unwrap_bash_command(self, command: str) -> str:
        """Unwrap /bin/bash -lc wrapper from command."""
        if command.startswith("/bin/bash"):
            match = re.search(r"-[lc]+\s+['\"](.+)", command, re.DOTALL)
            if match:
                return match.group(1).rstrip("'\"")
            return re.sub(r"^/bin/bash\s+-[lc]+\s+", "", command)
        return command

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

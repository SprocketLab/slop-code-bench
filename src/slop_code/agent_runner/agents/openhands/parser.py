"""OpenHands trajectory parser."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from slop_code.agent_runner.trajectory import (
    AgentStep,
    ToolUseStep,
    Trajectory,
    TrajectoryStep,
    UserStep,
)
from slop_code.agent_runner.trajectory_parsing import ParseError, TrajectoryParser


class OpenHandsParser(TrajectoryParser):
    """Parser for OpenHands trajectory format.

    OpenHands uses trajectory.json (array) or events.jsonl formats.
    """

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if directory contains OpenHands trajectory."""
        # Check if artifact_dir is a JSON file
        if artifact_dir.is_file():
            if artifact_dir.suffix == ".json":
                return self._is_openhands_json(artifact_dir)
            return False

        if not artifact_dir.is_dir():
            return False

        # Check for trajectory.json
        trajectory_path = artifact_dir / "trajectory.json"
        if trajectory_path.exists():
            return self._is_openhands_json(trajectory_path)

        # Check for events.jsonl
        events_path = artifact_dir / "events.jsonl"
        if events_path.exists():
            return self._is_openhands_jsonl(events_path)

        return False

    def _is_openhands_json(self, path: Path) -> bool:
        """Check if JSON file is OpenHands format."""
        try:
            with open(path) as f:
                data = json.load(f)
            if not isinstance(data, list):
                return False
            # Check for OpenHands-specific fields
            for entry in data[:10]:  # Check first 10 entries
                if isinstance(entry, dict):
                    if "llm_metrics" in entry:
                        return True
                    if "source" in entry and entry.get("source") in (
                        "agent",
                        "user",
                        "environment",
                    ):
                        return True
        except (json.JSONDecodeError, OSError):
            pass
        return False

    def _is_openhands_jsonl(self, path: Path) -> bool:
        """Check if JSONL file is OpenHands format."""
        try:
            with open(path) as f:
                first_line = f.readline().strip()
                if not first_line:
                    return False
                data = json.loads(first_line)
                # OpenHands events have is_step or action fields
                return "is_step" in data or "action" in data
        except (json.JSONDecodeError, OSError):
            pass
        return False

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse OpenHands trajectory."""
        steps: list[TrajectoryStep] = []
        metadata: dict[str, Any] = {}

        # Determine path
        if artifact_dir.is_file() and artifact_dir.suffix == ".json":
            self._parse_trajectory_json(artifact_dir, steps, metadata)
        elif artifact_dir.is_dir():
            trajectory_path = artifact_dir / "trajectory.json"
            events_path = artifact_dir / "events.jsonl"

            if trajectory_path.exists():
                self._parse_trajectory_json(trajectory_path, steps, metadata)
            elif events_path.exists():
                self._parse_events_jsonl(events_path, steps, metadata)
            else:
                raise ParseError(f"No trajectory file found in {artifact_dir}")
        else:
            raise ParseError(f"Invalid artifact path: {artifact_dir}")

        return Trajectory(
            agent_type="openhands",
            steps=steps,
            metadata=metadata,
        )

    def _parse_trajectory_json(
        self,
        path: Path,
        steps: list[TrajectoryStep],
        metadata: dict[str, Any],
    ) -> None:
        """Parse trajectory.json format."""
        try:
            with open(path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise ParseError(f"Failed to parse trajectory.json: {e}")

        if not isinstance(data, list):
            raise ParseError("trajectory.json must be a list")

        for entry in data:
            if not isinstance(entry, dict):
                continue

            # Extract metadata from llm_metrics
            if "llm_metrics" in entry and "accumulated_cost" not in metadata:
                llm_metrics = entry.get("llm_metrics", {})
                metadata["accumulated_cost"] = llm_metrics.get("accumulated_cost", 0.0)
                accumulated_tokens = llm_metrics.get("accumulated_token_usage", {})
                metadata["total_tokens"] = {
                    "input": accumulated_tokens.get("prompt_tokens", 0),
                    "output": accumulated_tokens.get("completion_tokens", 0),
                }

            # Process based on source
            source = entry.get("source", "")
            action = entry.get("action", "")
            message = entry.get("message", "")
            args = entry.get("args", {})

            if source == "agent":
                if action == "message":
                    # Agent text output
                    content = args.get("content", "") or message
                    if content:
                        steps.append(AgentStep(content=content))
                elif action in ("run", "execute_bash"):
                    # Bash command
                    command = args.get("command", "")
                    steps.append(
                        ToolUseStep(
                            type="bash",
                            arguments={"command": command},
                            result=None,
                        )
                    )
                elif action in ("write", "edit", "str_replace_editor"):
                    # File edit
                    path_arg = args.get("path", "")
                    steps.append(
                        ToolUseStep(
                            type="edit",
                            arguments=args,
                            result=None,
                        )
                    )
                elif action == "read":
                    # File read
                    steps.append(
                        ToolUseStep(
                            type="read",
                            arguments=args,
                            result=None,
                        )
                    )
                elif action == "browse":
                    # Web browse
                    steps.append(
                        ToolUseStep(
                            type="browse",
                            arguments=args,
                            result=None,
                        )
                    )
                elif action and action != "system":
                    # Other tool use
                    steps.append(
                        ToolUseStep(
                            type=action,
                            arguments=args,
                            result=None,
                        )
                    )

            elif source == "user":
                content = args.get("content", "") or message
                if content and len(content) < 10000:
                    steps.append(UserStep(content=content))

            elif source == "environment":
                # Tool results - match with previous tool use
                content = args.get("content", "") or message
                if content:
                    for step in reversed(steps):
                        if isinstance(step, ToolUseStep) and step.result is None:
                            step.result = content
                            break

    def _parse_events_jsonl(
        self,
        path: Path,
        steps: list[TrajectoryStep],
        metadata: dict[str, Any],
    ) -> None:
        """Parse events.jsonl format."""
        try:
            with open(path) as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise ParseError(f"Invalid JSON at line {line_num}: {e}")

                    self._process_event(event, steps)
        except OSError as e:
            raise ParseError(f"Failed to read events.jsonl: {e}")

    def _process_event(
        self,
        event: dict[str, Any],
        steps: list[TrajectoryStep],
    ) -> None:
        """Process a single event from events.jsonl."""
        # Only process step events
        if not event.get("is_step", False):
            return

        line = event.get("line", "")
        action = event.get("action", "")

        # Detect command execution
        if "**CmdRunAction**" in line or action == "run":
            command = event.get("args", {}).get("command", line)
            steps.append(
                ToolUseStep(
                    type="bash",
                    arguments={"command": command},
                    result=None,
                )
            )

        # Detect file edit
        elif "**FileEditAction**" in line or action in ("write", "edit"):
            steps.append(
                ToolUseStep(
                    type="edit",
                    arguments=event.get("args", {}),
                    result=None,
                )
            )

        # Agent message
        elif action == "message":
            content = event.get("args", {}).get("content", "")
            if content:
                steps.append(AgentStep(content=content))

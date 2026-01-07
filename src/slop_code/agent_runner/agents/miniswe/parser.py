"""MiniSWE trajectory parser."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from slop_code.agent_runner.trajectory import AgentStep
from slop_code.agent_runner.trajectory import ThinkingStep
from slop_code.agent_runner.trajectory import ToolUseStep
from slop_code.agent_runner.trajectory import Trajectory
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.agent_runner.trajectory import UserStep
from slop_code.agent_runner.trajectory_parsing import ParseError
from slop_code.agent_runner.trajectory_parsing import TrajectoryParser


class MinisweParser(TrajectoryParser):
    """Parser for MiniSWE trajectory format."""

    def can_parse(self, artifact_dir: Path) -> bool:
        """Check if directory contains MiniSWE trajectory."""
        jsonl_file = self._find_jsonl_file(artifact_dir)
        if not jsonl_file:
            return False

        try:
            with open(jsonl_file) as f:
                first_line = f.readline().strip()
                if not first_line:
                    return False
                data = json.loads(first_line)
                # MiniSWE uses role field with system/user/assistant/environment
                return "role" in data and data.get("role") in (
                    "system",
                    "user",
                    "assistant",
                    "environment",
                )
        except (json.JSONDecodeError, OSError):
            return False

    def parse(self, artifact_dir: Path) -> Trajectory:
        """Parse MiniSWE trajectory."""
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

                role = event.get("role", "")

                if role == "system":
                    # Extract model info if present
                    content = event.get("content", "")
                    self._extract_metadata(content, metadata)

                elif role == "assistant":
                    self._process_assistant(event, steps)

                elif role in ("user", "environment"):
                    self._process_user(event, steps)

        return Trajectory(
            agent_type="miniswe",
            steps=steps,
            metadata=metadata,
        )

    def _extract_metadata(self, content: str, metadata: dict[str, Any]) -> None:
        """Extract metadata from system messages."""
        if "claude" in content.lower():
            model_match = re.search(
                r"claude[-\s]*(\S+)", content, re.IGNORECASE
            )
            if model_match:
                metadata["model"] = model_match.group(1)

    def _process_assistant(
        self,
        event: dict[str, Any],
        steps: list[TrajectoryStep],
    ) -> None:
        """Process assistant message."""
        content = event.get("content", "")

        # Extract THOUGHT blocks
        thought_match = re.search(
            r"THOUGHT:\s*(.*?)(?=```bash|$)",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            thinking_text = thought_match.group(1).strip()
            if thinking_text:
                steps.append(ThinkingStep(content=thinking_text))

        # Extract bash commands
        bash_match = re.search(
            r"```bash\s*\n(.*?)```",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        if bash_match:
            command = bash_match.group(1).strip()
            steps.append(
                ToolUseStep(
                    type="bash",
                    arguments={"command": command},
                    result=None,
                )
            )
        elif not thought_match:
            # Plain text response
            if content.strip():
                steps.append(AgentStep(content=content.strip()))

    def _process_user(
        self,
        event: dict[str, Any],
        steps: list[TrajectoryStep],
    ) -> None:
        """Process user/environment message (tool results)."""
        content = event.get("content", "")
        role = event.get("role", "")

        if not content or not content.strip():
            return

        # Environment messages are usually tool results
        if role == "environment":
            # Try to match with previous bash command
            for step in reversed(steps):
                if isinstance(step, ToolUseStep) and step.result is None:
                    step.result = content.strip()
                    return

        # User messages can be prompts
        if role == "user" and len(content) < 5000:
            steps.append(UserStep(content=content.strip()))

    def _find_jsonl_file(self, artifact_dir: Path) -> Path | None:
        """Find the JSONL trajectory file."""
        if artifact_dir.is_file() and artifact_dir.suffix == ".jsonl":
            return artifact_dir

        # Check for stdout.jsonl (common location)
        stdout_file = artifact_dir / "stdout.jsonl"
        if stdout_file.exists():
            return stdout_file

        # Check for any .jsonl file
        jsonl_files = list(artifact_dir.glob("*.jsonl"))
        if jsonl_files:
            return jsonl_files[0]

        return None

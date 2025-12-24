#!/usr/bin/env python3
"""Analyze agent trajectories from slop-code-bench runs.

Parses JSONL trajectory files and computes:
- Activity classification (exploration, implementation, bug fixing)
- Tool usage metrics and success rates
- Reasoning/thinking token analysis
- Tool sequence patterns
"""

from __future__ import annotations

import json
import re
import tarfile
from abc import ABC, abstractmethod
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from pydantic import BaseModel, Field, computed_field
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()
err_console = Console(stderr=True)


# =============================================================================
# Data Models
# =============================================================================


class AgentType(str, Enum):
    """Supported agent types."""

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class ActivityType(str, Enum):
    """Activity classification types."""

    EXPLORATION = "exploration"
    IMPLEMENTATION = "implementation"
    BUG_FIXING = "bug_fixing"
    UNKNOWN = "unknown"


class ThinkingMetrics(BaseModel):
    """Metrics for reasoning/thinking content."""

    total_tokens: int = 0
    block_count: int = 0
    total_chars: int = 0

    # Content analysis counts
    planning_words: int = 0  # "plan", "first", "then", "step"
    debugging_words: int = 0  # "error", "fix", "bug", "fail"
    exploration_words: int = 0  # "understand", "explore", "look", "read"

    @computed_field
    @property
    def avg_tokens_per_block(self) -> float:
        return self.total_tokens / self.block_count if self.block_count > 0 else 0.0


class ToolMetrics(BaseModel):
    """Aggregated tool usage metrics."""

    counts: dict[str, int] = Field(default_factory=dict)
    success_counts: dict[str, int] = Field(default_factory=dict)
    failure_counts: dict[str, int] = Field(default_factory=dict)

    @computed_field
    @property
    def total_uses(self) -> int:
        return sum(self.counts.values())

    def get_success_rate(self, tool: str) -> float:
        success = self.success_counts.get(tool, 0)
        failure = self.failure_counts.get(tool, 0)
        total = success + failure
        return success / total if total > 0 else 1.0


class ActivityMetrics(BaseModel):
    """Activity classification metrics."""

    exploration_count: int = 0
    implementation_count: int = 0
    bug_fixing_count: int = 0
    unknown_count: int = 0

    @computed_field
    @property
    def total(self) -> int:
        return (
            self.exploration_count
            + self.implementation_count
            + self.bug_fixing_count
            + self.unknown_count
        )

    @computed_field
    @property
    def exploration_ratio(self) -> float:
        return self.exploration_count / self.total if self.total > 0 else 0.0

    @computed_field
    @property
    def implementation_ratio(self) -> float:
        return self.implementation_count / self.total if self.total > 0 else 0.0

    @computed_field
    @property
    def bug_fixing_ratio(self) -> float:
        return self.bug_fixing_count / self.total if self.total > 0 else 0.0


class TokenUsageMetrics(BaseModel):
    """Token usage from trajectory."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class SequenceMetrics(BaseModel):
    """Tool sequence analysis metrics."""

    bigrams: dict[str, int] = Field(default_factory=dict)
    trigrams: dict[str, int] = Field(default_factory=dict)

    # Fixed pattern counts
    quick_fix_count: int = 0  # Read -> Edit
    exploratory_edit_count: int = 0  # Read -> Read -> Edit
    bug_fix_cycle_count: int = 0  # Bash(test) -> Edit -> Bash(test)
    exploration_run_count: int = 0  # Glob -> Read+


class CheckpointMetrics(BaseModel):
    """Complete metrics for a single checkpoint."""

    problem: str
    checkpoint: str
    agent_type: AgentType

    tools: ToolMetrics = Field(default_factory=ToolMetrics)
    thinking: ThinkingMetrics = Field(default_factory=ThinkingMetrics)
    activity: ActivityMetrics = Field(default_factory=ActivityMetrics)
    tokens: TokenUsageMetrics = Field(default_factory=TokenUsageMetrics)
    sequences: SequenceMetrics = Field(default_factory=SequenceMetrics)

    turn_count: int = 0
    step_count: int = 0

    # Evaluation result
    passed: bool | None = None

    @computed_field
    @property
    def thinking_density(self) -> float:
        """Thinking tokens per action step."""
        return self.thinking.total_tokens / self.step_count if self.step_count > 0 else 0.0


# =============================================================================
# Parsers
# =============================================================================


# Keywords for content analysis
PLANNING_WORDS = ["plan", "first", "then", "step", "next", "will", "should", "need to"]
DEBUGGING_WORDS = ["error", "fix", "bug", "fail", "wrong", "issue", "problem", "debug"]
EXPLORATION_WORDS = [
    "understand",
    "explore",
    "look",
    "read",
    "check",
    "see",
    "find",
    "examine",
]


def count_keywords(text: str) -> tuple[int, int, int]:
    """Count planning, debugging, and exploration keywords in text."""
    text_lower = text.lower()
    planning = sum(text_lower.count(word) for word in PLANNING_WORDS)
    debugging = sum(text_lower.count(word) for word in DEBUGGING_WORDS)
    exploration = sum(text_lower.count(word) for word in EXPLORATION_WORDS)
    return planning, debugging, exploration


def estimate_tokens(text: str) -> int:
    """Rough token estimation (~4 chars per token)."""
    return len(text) // 4


class TrajectoryParser(ABC):
    """Abstract base for trajectory parsers."""

    # Read-only tools for exploration classification
    EXPLORATION_TOOLS = {"Read", "Glob", "Grep", "WebFetch", "WebSearch", "LSP"}
    IMPLEMENTATION_TOOLS = {"Edit", "Write", "NotebookEdit"}

    # Bash commands for classification
    EXPLORATION_COMMANDS = {
        "cat",
        "head",
        "tail",
        "ls",
        "find",
        "grep",
        "rg",
        "git status",
        "git log",
        "git diff",
        "wc",
        "file",
        "pwd",
        "tree",
    }
    IMPLEMENTATION_COMMANDS = {"echo", "mkdir", "cp", "mv", "rm", "touch"}
    TEST_COMMANDS = {"pytest", "python -m pytest", "uv run pytest", "npm test", "cargo test"}

    @abstractmethod
    def parse(self, jsonl_path: Path, problem: str, checkpoint: str) -> CheckpointMetrics:
        """Parse a trajectory file and return metrics."""
        pass

    @staticmethod
    def detect_agent_type(jsonl_path: Path) -> AgentType:
        """Auto-detect agent type from JSONL content."""
        with open(jsonl_path) as f:
            first_line = f.readline()
            if not first_line:
                raise ValueError("Empty JSONL file")
            data = json.loads(first_line)

            # ClaudeCode starts with system init message
            if data.get("type") == "system" and data.get("subtype") == "init":
                return AgentType.CLAUDE_CODE

            # Codex starts with thread.started
            if data.get("type") == "thread.started":
                return AgentType.CODEX

            # Fallback: look for ClaudeCode patterns
            if "message" in data and "content" in data.get("message", {}):
                return AgentType.CLAUDE_CODE

            # Fallback: look for Codex patterns
            if data.get("type", "").startswith(("turn.", "item.")):
                return AgentType.CODEX

        raise ValueError("Unable to detect agent type")

    def classify_bash_command(self, command: str) -> ActivityType:
        """Classify a bash command into activity type."""
        cmd_lower = command.lower()

        # Check for test commands first (most specific)
        for test_cmd in self.TEST_COMMANDS:
            if test_cmd in cmd_lower:
                return ActivityType.BUG_FIXING

        # Check for exploration patterns
        for exp_cmd in self.EXPLORATION_COMMANDS:
            if re.search(rf"\b{exp_cmd}\b", cmd_lower):
                return ActivityType.EXPLORATION

        # Check for implementation patterns
        for impl_cmd in self.IMPLEMENTATION_COMMANDS:
            if re.search(rf"\b{impl_cmd}\b", cmd_lower):
                return ActivityType.IMPLEMENTATION

        # File redirects are implementation
        if ">" in command or ">>" in command:
            return ActivityType.IMPLEMENTATION

        return ActivityType.UNKNOWN

    def update_activity(self, metrics: CheckpointMetrics, activity: ActivityType) -> None:
        """Update activity counts in metrics."""
        if activity == ActivityType.EXPLORATION:
            metrics.activity.exploration_count += 1
        elif activity == ActivityType.IMPLEMENTATION:
            metrics.activity.implementation_count += 1
        elif activity == ActivityType.BUG_FIXING:
            metrics.activity.bug_fixing_count += 1
        else:
            metrics.activity.unknown_count += 1

    def analyze_sequences(self, tool_sequence: list[str], metrics: CheckpointMetrics) -> None:
        """Analyze tool sequences for patterns."""
        # Compute n-grams
        for i in range(len(tool_sequence) - 1):
            bigram = f"{tool_sequence[i]} -> {tool_sequence[i + 1]}"
            metrics.sequences.bigrams[bigram] = metrics.sequences.bigrams.get(bigram, 0) + 1

        for i in range(len(tool_sequence) - 2):
            trigram = f"{tool_sequence[i]} -> {tool_sequence[i + 1]} -> {tool_sequence[i + 2]}"
            metrics.sequences.trigrams[trigram] = metrics.sequences.trigrams.get(trigram, 0) + 1

        # Detect fixed patterns
        for i in range(len(tool_sequence) - 1):
            # Quick fix: Read -> Edit
            if tool_sequence[i] == "Read" and tool_sequence[i + 1] == "Edit":
                metrics.sequences.quick_fix_count += 1

        for i in range(len(tool_sequence) - 2):
            # Exploratory edit: Read -> Read -> Edit
            if (
                tool_sequence[i] == "Read"
                and tool_sequence[i + 1] == "Read"
                and tool_sequence[i + 2] == "Edit"
            ):
                metrics.sequences.exploratory_edit_count += 1

            # Bug fix cycle: Bash -> Edit -> Bash
            if (
                tool_sequence[i] == "Bash"
                and tool_sequence[i + 1] == "Edit"
                and tool_sequence[i + 2] == "Bash"
            ):
                metrics.sequences.bug_fix_cycle_count += 1

        # Exploration run: Glob followed by multiple Reads
        for i in range(len(tool_sequence) - 1):
            if tool_sequence[i] == "Glob" and tool_sequence[i + 1] == "Read":
                # Count consecutive Reads
                read_count = 0
                for j in range(i + 1, len(tool_sequence)):
                    if tool_sequence[j] == "Read":
                        read_count += 1
                    else:
                        break
                if read_count >= 2:
                    metrics.sequences.exploration_run_count += 1


class ClaudeCodeParser(TrajectoryParser):
    """Parser for ClaudeCode JSONL format."""

    def parse(self, jsonl_path: Path, problem: str, checkpoint: str) -> CheckpointMetrics:
        metrics = CheckpointMetrics(
            problem=problem,
            checkpoint=checkpoint,
            agent_type=AgentType.CLAUDE_CODE,
        )

        tool_sequence: list[str] = []
        pending_tool_uses: dict[str, str] = {}  # tool_use_id -> tool_name

        with open(jsonl_path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    self._process_event(data, metrics, tool_sequence, pending_tool_uses)
                except json.JSONDecodeError:
                    continue

        # Analyze sequences
        self.analyze_sequences(tool_sequence, metrics)

        return metrics

    def _process_event(
        self,
        data: dict[str, Any],
        metrics: CheckpointMetrics,
        tool_sequence: list[str],
        pending_tool_uses: dict[str, str],
    ) -> None:
        msg_type = data.get("type")

        if msg_type == "assistant":
            self._process_assistant_message(data, metrics, tool_sequence, pending_tool_uses)
        elif msg_type == "user":
            self._process_user_response(data, metrics, pending_tool_uses)

    def _process_assistant_message(
        self,
        data: dict[str, Any],
        metrics: CheckpointMetrics,
        tool_sequence: list[str],
        pending_tool_uses: dict[str, str],
    ) -> None:
        message = data.get("message", {})
        content = message.get("content", [])

        # Extract token usage
        usage = message.get("usage", {})
        if usage:
            metrics.tokens.input_tokens += usage.get("input_tokens", 0)
            metrics.tokens.output_tokens += usage.get("output_tokens", 0)
            metrics.tokens.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
            metrics.tokens.cache_write_tokens += usage.get("cache_creation_input_tokens", 0)

        for block in content:
            block_type = block.get("type")

            if block_type == "thinking":
                self._process_thinking(block, metrics)
            elif block_type == "tool_use":
                self._process_tool_use(block, metrics, tool_sequence, pending_tool_uses)

        # Track turns
        if message.get("stop_reason") in ("end_turn", "tool_use"):
            metrics.turn_count += 1

    def _process_thinking(self, block: dict[str, Any], metrics: CheckpointMetrics) -> None:
        thinking_text = block.get("thinking", "")
        token_estimate = estimate_tokens(thinking_text)

        metrics.thinking.total_tokens += token_estimate
        metrics.thinking.block_count += 1
        metrics.thinking.total_chars += len(thinking_text)

        # Content analysis
        planning, debugging, exploration = count_keywords(thinking_text)
        metrics.thinking.planning_words += planning
        metrics.thinking.debugging_words += debugging
        metrics.thinking.exploration_words += exploration

    def _process_tool_use(
        self,
        block: dict[str, Any],
        metrics: CheckpointMetrics,
        tool_sequence: list[str],
        pending_tool_uses: dict[str, str],
    ) -> None:
        tool_name = block.get("name", "unknown")
        tool_id = block.get("id", "")
        tool_input = block.get("input", {})

        metrics.step_count += 1
        metrics.tools.counts[tool_name] = metrics.tools.counts.get(tool_name, 0) + 1
        tool_sequence.append(tool_name)

        # Track pending tool use for success/failure tracking
        pending_tool_uses[tool_id] = tool_name

        # Classify activity
        activity = self._classify_tool(tool_name, tool_input)
        self.update_activity(metrics, activity)

    def _classify_tool(self, tool_name: str, tool_input: dict[str, Any]) -> ActivityType:
        if tool_name in self.EXPLORATION_TOOLS:
            return ActivityType.EXPLORATION
        if tool_name in self.IMPLEMENTATION_TOOLS:
            return ActivityType.IMPLEMENTATION

        if tool_name == "Bash":
            command = tool_input.get("command", "")
            return self.classify_bash_command(command)

        if tool_name == "Task":
            # Task delegation - classify based on subagent type
            subagent = tool_input.get("subagent_type", "")
            if subagent in ("Explore", "explore"):
                return ActivityType.EXPLORATION
            if subagent in ("Plan", "plan"):
                return ActivityType.EXPLORATION

        if tool_name == "TodoWrite":
            return ActivityType.EXPLORATION  # Planning activity

        return ActivityType.UNKNOWN

    def _process_user_response(
        self,
        data: dict[str, Any],
        metrics: CheckpointMetrics,
        pending_tool_uses: dict[str, str],
    ) -> None:
        """Process user messages (tool results)."""
        message = data.get("message", {})
        content = message.get("content", [])
        tool_use_result = data.get("tool_use_result")

        for block in content:
            if block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id", "")
                is_error = block.get("is_error", False)
                tool_name = pending_tool_uses.get(tool_id, "unknown")

                if is_error:
                    metrics.tools.failure_counts[tool_name] = (
                        metrics.tools.failure_counts.get(tool_name, 0) + 1
                    )
                else:
                    metrics.tools.success_counts[tool_name] = (
                        metrics.tools.success_counts.get(tool_name, 0) + 1
                    )

                # Check for bash failures in result
                if tool_name == "Bash" and tool_use_result:
                    stderr = ""
                    if isinstance(tool_use_result, dict):
                        stderr = tool_use_result.get("stderr", "")
                    if stderr and "error" in stderr.lower():
                        # Retroactively mark as bug fixing context
                        pass


class CodexParser(TrajectoryParser):
    """Parser for Codex JSONL format."""

    def parse(self, jsonl_path: Path, problem: str, checkpoint: str) -> CheckpointMetrics:
        metrics = CheckpointMetrics(
            problem=problem,
            checkpoint=checkpoint,
            agent_type=AgentType.CODEX,
        )

        tool_sequence: list[str] = []

        with open(jsonl_path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    self._process_event(data, metrics, tool_sequence)
                except json.JSONDecodeError:
                    continue

        # Analyze sequences
        self.analyze_sequences(tool_sequence, metrics)

        return metrics

    def _process_event(
        self, data: dict[str, Any], metrics: CheckpointMetrics, tool_sequence: list[str]
    ) -> None:
        event_type = data.get("type")

        if event_type == "turn.started":
            metrics.turn_count += 1

        elif event_type == "turn.completed":
            usage = data.get("usage", {})
            metrics.tokens.input_tokens += usage.get("input_tokens", 0)
            metrics.tokens.output_tokens += usage.get("output_tokens", 0)
            metrics.tokens.cache_read_tokens += usage.get("cached_input_tokens", 0)

        elif event_type == "item.completed":
            item = data.get("item", {})
            self._process_item(item, metrics, tool_sequence)

    def _process_item(
        self, item: dict[str, Any], metrics: CheckpointMetrics, tool_sequence: list[str]
    ) -> None:
        item_type = item.get("type")

        if item_type == "reasoning":
            text = item.get("text", "")
            token_estimate = estimate_tokens(text)

            metrics.thinking.total_tokens += token_estimate
            metrics.thinking.block_count += 1
            metrics.thinking.total_chars += len(text)

            planning, debugging, exploration = count_keywords(text)
            metrics.thinking.planning_words += planning
            metrics.thinking.debugging_words += debugging
            metrics.thinking.exploration_words += exploration

        elif item_type == "command_execution":
            metrics.step_count += 1
            command = item.get("command", "")
            exit_code = item.get("exit_code")
            status = item.get("status", "")

            # Extract tool name from command
            tool_name = self._extract_tool_from_command(command)
            metrics.tools.counts[tool_name] = metrics.tools.counts.get(tool_name, 0) + 1
            tool_sequence.append(tool_name)

            # Track success/failure
            success = exit_code == 0 or status == "completed"
            if success:
                metrics.tools.success_counts[tool_name] = (
                    metrics.tools.success_counts.get(tool_name, 0) + 1
                )
            elif exit_code is not None:
                metrics.tools.failure_counts[tool_name] = (
                    metrics.tools.failure_counts.get(tool_name, 0) + 1
                )

            # Classify activity
            activity = self.classify_bash_command(command)
            self.update_activity(metrics, activity)

        elif item_type == "file_change":
            metrics.step_count += 1
            # Map to Edit for sequence tracking
            metrics.tools.counts["Edit"] = metrics.tools.counts.get("Edit", 0) + 1
            tool_sequence.append("Edit")
            self.update_activity(metrics, ActivityType.IMPLEMENTATION)

        elif item_type == "todo_list":
            metrics.thinking.planning_words += 1

    def _extract_tool_from_command(self, command: str) -> str:
        """Extract primary tool name from bash command."""
        # Strip /bin/bash -lc wrapper if present
        if command.startswith("/bin/bash"):
            # Match both single and double quotes
            match = re.search(r"-[lc]+\s+['\"](.+)", command, re.DOTALL)
            if match:
                command = match.group(1).rstrip("'\"")
            else:
                # Fall back to just stripping the prefix
                command = re.sub(r"^/bin/bash\s+-[lc]+\s+", "", command)

        # Get first word as tool name
        parts = command.strip().split()
        if not parts:
            return "Bash"

        tool = parts[0]

        # Normalize common patterns
        if tool in ("python", "python3"):
            return "python"
        if tool == "uv" and len(parts) > 1:
            if parts[1] == "run" and len(parts) > 2:
                return parts[2]  # uv run pytest -> pytest
            return parts[1]  # uv pip -> pip
        if tool in ("pip", "pip3"):
            return "pip"
        if tool == "git":
            return "git"
        if "pytest" in command:
            return "pytest"

        # Map read-only commands to Read for sequence analysis
        if tool in ("cat", "head", "tail", "less", "more"):
            return "Read"
        if tool in ("ls", "find", "tree"):
            return "Glob"
        if tool in ("grep", "rg", "ag"):
            return "Grep"

        return tool


# =============================================================================
# Aggregation
# =============================================================================


def aggregate_checkpoints(checkpoints: list[CheckpointMetrics]) -> dict[str, Any]:
    """Aggregate checkpoint metrics into problem-level summary."""
    if not checkpoints:
        return {}

    pass_count = sum(1 for c in checkpoints if c.passed is True)
    fail_count = sum(1 for c in checkpoints if c.passed is False)
    total_with_result = pass_count + fail_count

    return {
        "checkpoint_count": len(checkpoints),
        "total_steps": sum(c.step_count for c in checkpoints),
        "total_turns": sum(c.turn_count for c in checkpoints),
        "total_thinking_tokens": sum(c.thinking.total_tokens for c in checkpoints),
        "avg_thinking_density": sum(c.thinking_density for c in checkpoints) / len(checkpoints),
        "pass_rate": pass_count / total_with_result if total_with_result > 0 else None,
        "tool_counts": merge_counts([c.tools.counts for c in checkpoints]),
        "activity_breakdown": {
            "exploration": sum(c.activity.exploration_count for c in checkpoints),
            "implementation": sum(c.activity.implementation_count for c in checkpoints),
            "bug_fixing": sum(c.activity.bug_fixing_count for c in checkpoints),
            "unknown": sum(c.activity.unknown_count for c in checkpoints),
        },
        "tokens": {
            "input": sum(c.tokens.input_tokens for c in checkpoints),
            "output": sum(c.tokens.output_tokens for c in checkpoints),
            "cache_read": sum(c.tokens.cache_read_tokens for c in checkpoints),
            "thinking": sum(c.thinking.total_tokens for c in checkpoints),
        },
        "content_analysis": {
            "planning_words": sum(c.thinking.planning_words for c in checkpoints),
            "debugging_words": sum(c.thinking.debugging_words for c in checkpoints),
            "exploration_words": sum(c.thinking.exploration_words for c in checkpoints),
        },
        "sequences": {
            "quick_fix": sum(c.sequences.quick_fix_count for c in checkpoints),
            "exploratory_edit": sum(c.sequences.exploratory_edit_count for c in checkpoints),
            "bug_fix_cycle": sum(c.sequences.bug_fix_cycle_count for c in checkpoints),
            "exploration_run": sum(c.sequences.exploration_run_count for c in checkpoints),
        },
    }


def aggregate_problems(problems: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate problem metrics into run-level summary."""
    if not problems:
        return {}

    total_checkpoints = sum(p["checkpoint_count"] for p in problems.values())
    total_steps = sum(p["total_steps"] for p in problems.values())

    # Calculate pass rate across all problems
    pass_rates = [p["pass_rate"] for p in problems.values() if p["pass_rate"] is not None]
    avg_pass_rate = sum(pass_rates) / len(pass_rates) if pass_rates else None

    return {
        "problem_count": len(problems),
        "checkpoint_count": total_checkpoints,
        "total_steps": total_steps,
        "mean_steps_per_checkpoint": total_steps / total_checkpoints if total_checkpoints > 0 else 0,
        "avg_pass_rate": avg_pass_rate,
        "avg_thinking_density": (
            sum(p["avg_thinking_density"] for p in problems.values()) / len(problems)
        ),
        "tool_counts": merge_counts([p["tool_counts"] for p in problems.values()]),
        "activity_breakdown": {
            "exploration": sum(p["activity_breakdown"]["exploration"] for p in problems.values()),
            "implementation": sum(
                p["activity_breakdown"]["implementation"] for p in problems.values()
            ),
            "bug_fixing": sum(p["activity_breakdown"]["bug_fixing"] for p in problems.values()),
            "unknown": sum(p["activity_breakdown"]["unknown"] for p in problems.values()),
        },
        "tokens": {
            "input": sum(p["tokens"]["input"] for p in problems.values()),
            "output": sum(p["tokens"]["output"] for p in problems.values()),
            "cache_read": sum(p["tokens"]["cache_read"] for p in problems.values()),
            "thinking": sum(p["tokens"]["thinking"] for p in problems.values()),
        },
        "content_analysis": {
            "planning_words": sum(p["content_analysis"]["planning_words"] for p in problems.values()),
            "debugging_words": sum(
                p["content_analysis"]["debugging_words"] for p in problems.values()
            ),
            "exploration_words": sum(
                p["content_analysis"]["exploration_words"] for p in problems.values()
            ),
        },
        "sequences": {
            "quick_fix": sum(p["sequences"]["quick_fix"] for p in problems.values()),
            "exploratory_edit": sum(p["sequences"]["exploratory_edit"] for p in problems.values()),
            "bug_fix_cycle": sum(p["sequences"]["bug_fix_cycle"] for p in problems.values()),
            "exploration_run": sum(p["sequences"]["exploration_run"] for p in problems.values()),
        },
    }


def merge_counts(count_dicts: list[dict[str, int]]) -> dict[str, int]:
    """Merge multiple count dictionaries."""
    merged: dict[str, int] = {}
    for d in count_dicts:
        for k, v in d.items():
            merged[k] = merged.get(k, 0) + v
    return merged


# =============================================================================
# Discovery and Loading
# =============================================================================


def get_run_name(run_dir: Path) -> str:
    """Extract a readable run name from config.yaml."""
    config_path = run_dir / "config.yaml"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)

            model = config.get("model", {}).get("name", "?")
            prompt = Path(config.get("prompt_path", "?")).stem
            thinking = config.get("thinking", "none")

            return f"{model}/{prompt}/{thinking}"
        except Exception:
            pass
    return run_dir.name


def discover_trajectories(run_dir: Path) -> dict[str, dict[str, Path]]:
    """Discover all trajectory files in a run directory.

    Returns: {problem_name: {checkpoint_name: jsonl_path}}
    """
    trajectories: dict[str, dict[str, Path]] = {}

    for problem_dir in sorted(run_dir.iterdir()):
        if not problem_dir.is_dir():
            continue

        problem_name = problem_dir.name
        if problem_name.startswith(".") or problem_name == "config.yaml":
            continue

        trajectories[problem_name] = {}

        for checkpoint_dir in sorted(problem_dir.iterdir()):
            if not checkpoint_dir.is_dir():
                continue
            if not checkpoint_dir.name.startswith("checkpoint_"):
                continue

            checkpoint_name = checkpoint_dir.name
            agent_dir = checkpoint_dir / "agent"

            # Check for stdout.jsonl or agent.tar.gz
            jsonl_path = agent_dir / "stdout.jsonl"
            tar_path = agent_dir / "agent.tar.gz"

            if jsonl_path.exists():
                trajectories[problem_name][checkpoint_name] = jsonl_path
            elif tar_path.exists():
                extracted = extract_from_tar(tar_path)
                if extracted:
                    trajectories[problem_name][checkpoint_name] = extracted

    return trajectories


def extract_from_tar(tar_path: Path) -> Path | None:
    """Extract stdout.jsonl from agent.tar.gz."""
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("stdout.jsonl"):
                    tar.extract(member, tar_path.parent)
                    return tar_path.parent / member.name
    except Exception as e:
        err_console.print(f"[yellow]Warning: Failed to extract {tar_path}: {e}[/yellow]")
    return None


def load_evaluation_result(checkpoint_dir: Path) -> bool | None:
    """Load pass/fail from evaluation.json."""
    eval_path = checkpoint_dir / "evaluation.json"
    if not eval_path.exists():
        return None

    try:
        with open(eval_path) as f:
            data = json.load(f)
        return data.get("passed_policy", None)
    except Exception:
        return None


# =============================================================================
# Output Rendering
# =============================================================================


def render_summary_table(summary: dict[str, Any], title: str) -> Table:
    """Render run summary as a Rich table."""
    table = Table(title=title, expand=True)

    table.add_column("Metric", style="cyan", width=25)
    table.add_column("Value", justify="right", width=15)

    table.add_row("Problems", str(summary["problem_count"]))
    table.add_row("Checkpoints", str(summary["checkpoint_count"]))
    table.add_row("Total Steps", str(summary["total_steps"]))
    table.add_row("Mean Steps/Checkpoint", f"{summary['mean_steps_per_checkpoint']:.1f}")
    table.add_row("Mean Thinking Density", f"{summary['avg_thinking_density']:.1f}")

    if summary.get("avg_pass_rate") is not None:
        table.add_row("Pass Rate", f"{100 * summary['avg_pass_rate']:.1f}%")

    table.add_section()

    # Activity breakdown
    activities = summary["activity_breakdown"]
    total_activities = sum(activities.values())
    if total_activities > 0:
        table.add_row(
            "Exploration %", f"{100 * activities['exploration'] / total_activities:.1f}%"
        )
        table.add_row(
            "Implementation %", f"{100 * activities['implementation'] / total_activities:.1f}%"
        )
        table.add_row(
            "Bug Fixing %", f"{100 * activities['bug_fixing'] / total_activities:.1f}%"
        )

    table.add_section()

    # Sequence patterns
    seqs = summary["sequences"]
    table.add_row("Quick Fix (Read→Edit)", str(seqs["quick_fix"]))
    table.add_row("Exploratory Edit", str(seqs["exploratory_edit"]))
    table.add_row("Bug Fix Cycles", str(seqs["bug_fix_cycle"]))
    table.add_row("Exploration Runs", str(seqs["exploration_run"]))

    table.add_section()

    # Top tools
    tool_counts = sorted(summary["tool_counts"].items(), key=lambda x: -x[1])[:8]
    for tool, count in tool_counts:
        table.add_row(f"  {tool}", str(count))

    return table


def render_comparison_table(runs: dict[str, dict[str, Any]]) -> Table:
    """Render side-by-side comparison of multiple runs."""
    table = Table(title="Run Comparison", expand=True)

    table.add_column("Metric", style="cyan", width=25)
    for run_name in runs.keys():
        # Truncate long names
        short_name = run_name[:20] + "..." if len(run_name) > 23 else run_name
        table.add_column(short_name, justify="right", width=18)

    def add_metric_row(label: str, key_path: list[str], fmt: str = "{}"):
        values = []
        for summary in runs.values():
            val = summary
            for k in key_path:
                val = val.get(k, 0) if isinstance(val, dict) else 0
            if fmt == "pct":
                values.append(f"{100 * val:.1f}%" if val else "-")
            elif fmt == "float":
                values.append(f"{val:.1f}" if val else "-")
            else:
                values.append(str(val) if val else "-")
        table.add_row(label, *values)

    add_metric_row("Problems", ["problem_count"])
    add_metric_row("Checkpoints", ["checkpoint_count"])
    add_metric_row("Total Steps", ["total_steps"])
    add_metric_row("Steps/Checkpoint", ["mean_steps_per_checkpoint"], "float")
    add_metric_row("Thinking Density", ["avg_thinking_density"], "float")

    # Add pass rate if available
    if any(s.get("avg_pass_rate") is not None for s in runs.values()):
        add_metric_row("Pass Rate", ["avg_pass_rate"], "pct")

    table.add_section()

    # Activity ratios
    for summary in runs.values():
        total = sum(summary["activity_breakdown"].values())
        if total > 0:
            summary["_exp_pct"] = summary["activity_breakdown"]["exploration"] / total
            summary["_impl_pct"] = summary["activity_breakdown"]["implementation"] / total
            summary["_bug_pct"] = summary["activity_breakdown"]["bug_fixing"] / total
        else:
            summary["_exp_pct"] = summary["_impl_pct"] = summary["_bug_pct"] = 0

    add_metric_row("Exploration %", ["_exp_pct"], "pct")
    add_metric_row("Implementation %", ["_impl_pct"], "pct")
    add_metric_row("Bug Fixing %", ["_bug_pct"], "pct")

    table.add_section()

    # Sequences
    add_metric_row("Quick Fix", ["sequences", "quick_fix"])
    add_metric_row("Bug Fix Cycles", ["sequences", "bug_fix_cycle"])

    table.add_section()

    # Token usage
    add_metric_row("Thinking Tokens", ["tokens", "thinking"])
    add_metric_row("Output Tokens", ["tokens", "output"])

    return table


def render_checkpoint_table(metrics: CheckpointMetrics) -> Table:
    """Render per-checkpoint metrics."""
    table = Table(title=f"{metrics.problem} / {metrics.checkpoint}")

    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Steps", str(metrics.step_count))
    table.add_row("Turns", str(metrics.turn_count))
    table.add_row("Thinking Tokens", f"{metrics.thinking.total_tokens:,}")
    table.add_row("Thinking Density", f"{metrics.thinking_density:.1f}")

    if metrics.passed is not None:
        status = "[green]PASS[/green]" if metrics.passed else "[red]FAIL[/red]"
        table.add_row("Result", status)

    table.add_section()
    table.add_row("Exploration", str(metrics.activity.exploration_count))
    table.add_row("Implementation", str(metrics.activity.implementation_count))
    table.add_row("Bug Fixing", str(metrics.activity.bug_fixing_count))

    return table


# =============================================================================
# CLI
# =============================================================================


@app.command()
def main(
    run_dirs: Annotated[list[Path], typer.Argument(help="Run directories to analyze")],
    agent: Annotated[
        str | None, typer.Option(help="Force agent type: claude_code or codex")
    ] = None,
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Output JSON file")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Show per-checkpoint details")
    ] = False,
    problems: Annotated[
        list[str] | None, typer.Option("--problem", help="Filter to specific problems")
    ] = None,
    compare: Annotated[
        bool, typer.Option("--compare", help="Show side-by-side comparison")
    ] = False,
):
    """Analyze agent trajectories from slop-code-bench runs.

    Parses JSONL trajectory files and computes:
    - Activity classification (exploration, implementation, bug fixing)
    - Tool usage metrics and success rates
    - Reasoning/thinking token analysis
    - Tool sequence patterns
    """
    all_results: dict[str, dict[str, Any]] = {}
    all_summaries: dict[str, dict[str, Any]] = {}

    for run_dir in run_dirs:
        if not run_dir.exists():
            err_console.print(f"[yellow]Warning: {run_dir} does not exist[/yellow]")
            continue

        # Skip hidden directories and non-directories
        if run_dir.name.startswith("."):
            continue

        run_name = get_run_name(run_dir)
        if not run_name:
            continue

        err_console.print(f"[dim]Analyzing {run_name}...[/dim]")

        trajectories = discover_trajectories(run_dir)

        if not trajectories:
            err_console.print(f"[yellow]Warning: No trajectories in {run_dir}[/yellow]")
            continue

        # Filter problems if specified
        if problems:
            trajectories = {k: v for k, v in trajectories.items() if k in problems}

        if not trajectories:
            err_console.print(f"[yellow]Warning: No matching problems in {run_dir}[/yellow]")
            continue

        run_results: dict[str, Any] = {"problems": {}, "checkpoints": []}

        for problem_name, checkpoints in sorted(trajectories.items()):
            checkpoint_metrics: list[CheckpointMetrics] = []

            for checkpoint_name, jsonl_path in sorted(checkpoints.items()):
                try:
                    # Auto-detect or use specified agent type
                    if agent:
                        agent_type = AgentType(agent)
                    else:
                        agent_type = TrajectoryParser.detect_agent_type(jsonl_path)

                    # Get appropriate parser
                    parser: TrajectoryParser
                    if agent_type == AgentType.CLAUDE_CODE:
                        parser = ClaudeCodeParser()
                    else:
                        parser = CodexParser()

                    metrics = parser.parse(jsonl_path, problem_name, checkpoint_name)

                    # Load evaluation result
                    checkpoint_dir = jsonl_path.parent.parent
                    metrics.passed = load_evaluation_result(checkpoint_dir)

                    checkpoint_metrics.append(metrics)
                    run_results["checkpoints"].append(metrics.model_dump())

                    if verbose:
                        console.print(render_checkpoint_table(metrics))

                except Exception as e:
                    err_console.print(
                        f"[red]Error parsing {problem_name}/{checkpoint_name}: {e}[/red]"
                    )

            if checkpoint_metrics:
                run_results["problems"][problem_name] = aggregate_checkpoints(checkpoint_metrics)

        run_results["summary"] = aggregate_problems(run_results["problems"])

        # Only add results if we have actual data
        if run_results["problems"] and run_name:
            all_results[run_name] = run_results
            all_summaries[run_name] = run_results["summary"]

    # Output
    if output:
        output.write_text(json.dumps(all_results, indent=2, default=str))
        err_console.print(f"[green]Results written to {output}[/green]")

    # Display
    if not all_results:
        err_console.print("[yellow]No trajectories found to analyze[/yellow]")
        raise typer.Exit(1)

    if len(all_summaries) > 1 and compare:
        console.print(render_comparison_table(all_summaries))
    else:
        for run_name, results in all_results.items():
            if results.get("summary"):
                console.print()
                console.print(render_summary_table(results["summary"], run_name))


if __name__ == "__main__":
    app()

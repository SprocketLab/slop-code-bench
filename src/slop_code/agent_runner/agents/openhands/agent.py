"""OpenHands agent implementation."""

from __future__ import annotations

import json
import re
import shlex
import tempfile
import typing as tp
from pathlib import Path

from jinja2 import Template
from pydantic import Field

from slop_code.agent_runner.agent import Agent, AgentConfigBase
from slop_code.agent_runner.agents.cli_utils import (AgentCommandResult,
                                                     stream_cli_command)
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.credentials import (CredentialSpec,
                                                ProviderCredential)
from slop_code.agent_runner.models import AgentCostLimits, AgentError
from slop_code.agent_runner.registry import register_agent
from slop_code.common.llms import APIPricing, TokenUsage
from slop_code.execution import EnvironmentSpec, Session, StreamingRuntime
from slop_code.logging import get_logger

log = get_logger(__name__)

# OpenHands binary path - installed in /openhands/.venv
OPENHANDS_BINARY = "/openhands/.venv/bin/python"
OPENHANDS_MODULE = "openhands.core.main"

# Patterns for agent actions in stderr - CmdRunAction, FileEditAction, etc.
# These match lines from agent_controller logging like:
# [92m03:29:37 - openhands:INFO[0m: agent_controller.py:1007 - [...] **CmdRunAction**
ACTION_PATTERNS = [
    re.compile(r"\*\*CmdRunAction"),
    re.compile(r"\*\*FileEditAction"),
    re.compile(r"TaskTrackingAction\("),
]

# Provider to base URL mapping
PROVIDER_BASE_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
}


class OpenHandsConfig(AgentConfigBase):
    """Configuration for ``OpenHandsAgent`` instances."""

    type: tp.Literal["openhands"] = "openhands"
    version: str = Field(
        description="PyPI version of openhands-ai (e.g., '0.62')"
    )
    model: str | None = Field(
        default=None,
        description="LLM model identifier (e.g., 'anthropic/claude-sonnet-4-20250514')",
    )
    base_url: str | None = Field(
        default=None,
        description="LLM API base URL (auto-set for openrouter provider)",
    )
    timeout: int | None = Field(
        default=None,
        description="Optional timeout (in seconds) for the CLI invocation.",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Additional environment variable overrides.",
    )

    docker_template: Path = Path(__file__).parent / "docker.j2"

    def get_docker_file(self, base_image: str) -> str | None:
        """Render the Docker template with version."""
        if self.docker_template is None:
            return None
        template = self.docker_template.read_text()
        return Template(template).render(
            base_image=base_image, version=self.version
        )


class OpenHandsAgent(Agent):
    """Agent implementation for OpenHands."""

    PROMPT_FILENAME = "prompt.txt"
    STDOUT_FILENAME = "stdout.log"
    STDERR_FILENAME = "stderr.log"
    EVENTS_FILENAME = "events.jsonl"
    TRAJECTORY_FILENAME = "trajectory.json"

    def __init__(
        self,
        problem_name: str,
        verbose: bool,
        image: str,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credentials: CredentialSpec | None,
        resolved_credential: ProviderCredential | None,
        # OpenHands specific
        model: str | None,
        base_url: str | None,
        timeout: int | None,
        env: dict[str, str],
    ) -> None:
        super().__init__(
            agent_name="openhands",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )

        # Store config values
        self.credentials = credentials
        self.resolved_credential = resolved_credential
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.env = env

        self._image = image
        self._session: Session | None = None
        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None
        self._tmp_dir: tempfile.TemporaryDirectory | None = None

        self._last_prompt: str = ""
        self._last_command: AgentCommandResult | None = None
        self._events: list[dict] = []
        self._stdout_lines: list[str] = []

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        problem_name: str,
        verbose: bool,
        image: str | None,
    ) -> Agent:
        """Create an OpenHandsAgent from an OpenHandsConfig."""
        if not isinstance(config, OpenHandsConfig):
            raise TypeError(
                f"Expected OpenHandsConfig, got {type(config).__name__}"
            )
        if image is None:
            raise ValueError("OpenHandsAgent requires an image")

        # Resolve base_url from provider if credentials specify openrouter
        base_url = config.base_url
        if base_url is None and config.credentials is not None:
            provider = config.credentials.provider
            if provider in PROVIDER_BASE_URLS:
                base_url = PROVIDER_BASE_URLS[provider]

        return cls(
            problem_name=problem_name,
            verbose=verbose,
            image=image,
            cost_limits=config.cost_limits,
            pricing=config.pricing,
            credentials=config.credentials,
            resolved_credential=config.get_resolved_credential(),
            # Use internal_name for API calls (falls back to model if not set)
            model=config.internal_name or config.model,
            base_url=base_url,
            timeout=config.timeout,
            env=config.env,
        )

    def parse_line(
        self,
        line: str,
        pricing: APIPricing | None = None,
    ) -> tuple[float | None, TokenUsage | None, dict | None]:
        """Parse a single line from OpenHands output.

        OpenHands outputs log lines to stderr. We look for action patterns
        to count steps. Returns (cost, tokens, payload).

        Payload contains:
        - 'is_step': True if this line represents an agent action/step
        - 'line': The original line for logging
        """

        # Check if this is an agent action line (step)
        is_step = any(p.search(line) for p in ACTION_PATTERNS)

        # Return payload with step indicator
        return None, None, {"is_step": is_step, "line": line}

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError(
                "OpenHandsAgent has not been set up with a session"
            )
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError(
                "OpenHandsAgent has not been set up with a session"
            )
        return self._environment

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError(
                "OpenHandsAgent has not been set up with a runtime"
            )
        return self._runtime

    @property
    def tmp_dir(self) -> Path:
        if self._tmp_dir is None:
            raise AgentError("OpenHandsAgent tmp_dir accessed before setup")
        return Path(self._tmp_dir.name)

    def _make_config_toml(self) -> Path:
        """Create OpenHands config.toml with default settings."""
        config_path = self.tmp_dir / "config.toml"
        config_content = """\
[core]
disable_color = true
"""
        config_path.write_text(config_content)
        return config_path

    def _get_output_dir(self) -> Path:
        """Get/create the output directory for trajectory and other outputs."""
        output_dir = self.tmp_dir / "output"
        output_dir.mkdir(exist_ok=True)
        return output_dir

    def _get_volumes(self) -> dict[str, dict[str, str]]:
        """Get volume mounts for the OpenHands agent."""
        volumes: dict[str, dict[str, str]] = {}

        # Mount config.toml
        config_path = self._make_config_toml()
        volumes[str(config_path.absolute())] = {
            "bind": "/openhands/config.toml",
            "mode": "ro",
        }

        # Mount output directory for trajectory
        output_dir = self._get_output_dir()
        volumes[str(output_dir.absolute())] = {
            "bind": "/openhands/output",
            "mode": "rw",
        }

        return volumes

    def _extract_trajectory_usage(self) -> tuple[float, TokenUsage]:
        """Extract usage from trajectory.json's llm_metrics field.

        Reads the trajectory file and finds the last entry with llm_metrics
        to extract accumulated_cost and accumulated_token_usage.

        Returns:
            Tuple of (cost, TokenUsage) from the trajectory, or defaults
            if the file doesn't exist or has no llm_metrics.
        """
        if self._tmp_dir is None:
            return 0.0, TokenUsage()

        trajectory_path = (
            Path(self._tmp_dir.name) / "output" / "trajectory.json"
        )
        if not trajectory_path.exists():
            self.log.debug(
                "Trajectory file not found", path=str(trajectory_path)
            )
            return 0.0, TokenUsage()

        try:
            trajectory_data = json.loads(trajectory_path.read_text())
            if not isinstance(trajectory_data, list):
                self.log.warning("Trajectory is not a list")
                return 0.0, TokenUsage()

            # Find the last entry with llm_metrics
            for entry in reversed(trajectory_data):
                if not isinstance(entry, dict):
                    continue
                llm_metrics = entry.get("llm_metrics")
                if llm_metrics is None:
                    continue

                accumulated_cost = llm_metrics.get("accumulated_cost", 0.0)
                token_usage_data = llm_metrics.get(
                    "accumulated_token_usage", {}
                )

                tokens = TokenUsage(
                    input=token_usage_data.get("prompt_tokens", 0),
                    output=token_usage_data.get("completion_tokens", 0),
                    cache_read=token_usage_data.get("cache_read_tokens", 0),
                    cache_write=token_usage_data.get("cache_write_tokens", 0),
                )

                self.log.debug(
                    "Extracted usage from trajectory",
                    cost=accumulated_cost,
                    input_tokens=tokens.input,
                    output_tokens=tokens.output,
                    cache_read=tokens.cache_read,
                )
                return accumulated_cost, tokens

            self.log.debug("No llm_metrics found in trajectory")
            return 0.0, TokenUsage()

        except json.JSONDecodeError as e:
            self.log.warning("Failed to parse trajectory.json", error=str(e))
            return 0.0, TokenUsage()
        except (KeyError, TypeError, OSError) as e:
            self.log.warning(
                "Error extracting usage from trajectory", error=str(e)
            )
            return 0.0, TokenUsage()

    def setup(self, session: Session) -> None:
        """Set up the agent with a session."""
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._session = session
        self._environment = session.spec

        self._runtime = session.spawn(
            mounts=self._get_volumes(),
            env_vars={
                "HOME": HOME_PATH,
            },
            image=self._image,
            user="agent",
            disable_setup=True,
        )

    def run(self, task: str) -> None:
        """Execute a task through OpenHands."""
        self._last_prompt = task
        self._last_command = None

        log_kwargs: dict[str, tp.Any] = {
            "workspace": str(self.session.working_dir),
            "prompt_chars": len(task),
            "environment": self.session.spec.type,
            "max_iterations": self.cost_limits.step_limit,
        }
        log.info("agent.openhands.start", **log_kwargs)

        command_result = self._run_invocation(task)
        self._last_command = command_result

        runtime_result = command_result.result
        if runtime_result is None:
            log.error(
                "OpenHands process failed to start",
                error_message=command_result.error_message,
            )
            log.error("STDOUT", stdout=command_result.stdout)
            log.error("STDERR", stderr=command_result.stderr)
            raise AgentError("OpenHands process failed to start")

        if runtime_result.timed_out:
            message = (
                f"OpenHands process timed out after {self.timeout}s."
                if self.timeout is not None
                else "OpenHands process timed out."
            )
            log.error("agent.openhands.timeout", timeout=self.timeout)
            raise AgentError(message)

        # Note: OpenHands may exit with non-zero for various reasons
        # We don't treat this as a fatal error since the agent may have
        # completed useful work before hitting an issue
        if runtime_result.exit_code != 0:
            log.warning(
                "agent.openhands.nonzero_exit",
                exit_code=runtime_result.exit_code,
            )

        # Extract final usage from trajectory.json llm_metrics
        cost, tokens = self._extract_trajectory_usage()
        self.usage.cost = cost
        self.usage.net_tokens = tokens

    def _run_invocation(self, task: str) -> AgentCommandResult:
        """Execute an OpenHands CLI invocation and return results."""
        command, env_overrides = self._prepare_runtime_execution(task)

        if self._session is None:
            raise AgentError(
                "OpenHandsAgent has not been set up with a session"
            )
        if isinstance(command, list):
            command = " ".join(command)

        step_count = 0
        runtime_result = None
        self._stdout_lines = []

        for item in stream_cli_command(
            runtime=self.runtime,
            command=command,
            parser=self.parse_line,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
            parse_stderr=True,  # OpenHands logs actions to stderr
        ):
            # Final item is RuntimeResult
            if not isinstance(item, tuple):
                runtime_result = item
                break

            cost, tokens, payload = item

            if payload is not None:
                # Check if this line represents a step (agent action)
                if payload.get("is_step"):
                    step_count += 1
                    self.usage.steps = step_count
                    self.log.debug(
                        "Counted step",
                        step=step_count,
                        line=payload.get("line", "")[:80],
                        verbose=True,
                    )

                # Store raw lines for output log
                line = payload.get("line")
                if line:
                    self._stdout_lines.append(line)

                # Structured JSON payloads go to events
                if "line" not in payload and "is_step" in payload:
                    # This is a JSON payload with is_step added
                    event_payload = {
                        k: v for k, v in payload.items() if k != "is_step"
                    }
                    if event_payload:
                        self._events.append(event_payload)

        stdout = runtime_result.stdout if runtime_result else ""
        stderr = runtime_result.stderr if runtime_result else ""

        return AgentCommandResult(
            result=runtime_result,
            steps=[],
            usage_totals={
                "steps": step_count,
            },
            stdout=stdout,
            stderr=stderr,
        )

    def _prepare_runtime_execution(
        self,
        task: str,
    ) -> tuple[list[str], dict[str, str]]:
        """Prepare command and environment overrides for runtime execution."""
        # Build environment variables - FORCE SET all required settings
        # Note: disable_color is set in config.toml, not as env var
        env_overrides: dict[str, str] = {
            # Runtime mode - CLI since we're inside Docker already
            "RUNTIME": "cli",
            # Disable jupyter (not needed for coding tasks)
            "AGENT_ENABLE_JUPYTER": "false",
            # Mount workspace
            "SANDBOX_VOLUMES": "/workspace:/workspace:rw",
            # Disable browsing and prompt extensions
            "AGENT_ENABLE_PROMPT_EXTENSIONS": "false",
            "AGENT_ENABLE_BROWSING": "false",
            "ENABLE_BROWSER": "false",
            # Sandbox settings
            "SANDBOX_ENABLE_AUTO_LINT": "false",
            # Disable dependency check
            "SKIP_DEPENDENCY_CHECK": "1",
            # We're running in a sandboxed environment
            "RUN_AS_OPENHANDS": "false",
            # Enable event logging
            "LOG_ALL_EVENTS": "true",
            # Skip VSCode build
            "SKIP_VSCODE_BUILD": "true",
            # Set trajectory save path (mounted from tmp_dir/output)
            "SAVE_TRAJECTORY_PATH": "/openhands/output/trajectory.json",
        }

        # Credentials - use LLM_API_KEY
        if self.resolved_credential is not None:
            env_overrides["LLM_API_KEY"] = self.resolved_credential.value
        else:
            raise AgentError("OpenHandsAgent requires a credential")

        # Model
        if self.model:
            if self.resolved_credential.provider == "openrouter":
                env_overrides["LLM_MODEL"] = f"openrouter/{self.model}"
            else:
                env_overrides["LLM_MODEL"] = self.model
        else:
            raise AgentError("OpenHandsAgent requires a model")

        # Base URL for OpenRouter or custom endpoints
        if self.base_url:
            env_overrides["LLM_BASE_URL"] = self.base_url
        # Base URL for OpenRouter or custom endpoints
        if self.base_url:
            env_overrides["LLM_BASE_URL"] = self.base_url

        # Max iterations
        if self.cost_limits.step_limit > 0:
            env_overrides["MAX_ITERATIONS"] = str(self.cost_limits.step_limit)

        # Budget limit
        if self.cost_limits.cost_limit > 0:
            env_overrides["MAX_BUDGET_PER_TASK"] = str(
                self.cost_limits.cost_limit
            )

        # Merge with user-provided env overrides (user wins)
        env_overrides.update(self.env)

        command = self._build_command(task)
        return command, env_overrides

    def _build_command(self, task: str) -> list[str]:
        """Build CLI command arguments for OpenHands."""
        command = [OPENHANDS_BINARY, "-u", "-m", OPENHANDS_MODULE]
        command.extend(["--config-file", "/openhands/config.toml"])
        command.extend(["--task", shlex.quote(task)])
        return command

    @classmethod
    def _write_artifacts(
        cls,
        output_dir: Path,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        """Write stdout and stderr to artifact files."""
        (output_dir / cls.STDOUT_FILENAME).write_text(stdout_text)
        if stderr_text:
            (output_dir / cls.STDERR_FILENAME).write_text(stderr_text)

    def reset(self) -> None:
        """Reset agent state between runs."""
        self._last_prompt = ""
        self._last_command = None
        self._events = []
        self._stdout_lines = []

    def save_artifacts(self, path: Path) -> None:
        """Save agent execution artifacts to the specified directory."""
        path.mkdir(parents=True, exist_ok=True)

        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(self._last_prompt)

        stdout_text = ""
        stderr_text = ""
        if self._last_command is not None:
            stdout_text = self._last_command.stdout or ""
            stderr_text = self._last_command.stderr or ""

        self._write_artifacts(path, stdout_text, stderr_text)

        # Write collected stdout lines (contains the log output)
        if self._stdout_lines:
            (path / "output.log").write_text("\n".join(self._stdout_lines))

        # Write collected JSON events
        if self._events:
            with (path / self.EVENTS_FILENAME).open("w") as f:
                for event in self._events:
                    f.write(json.dumps(event) + "\n")

        # Copy trajectory file from mounted output directory
        if self._tmp_dir is not None:
            trajectory_src = (
                Path(self._tmp_dir.name) / "output" / "trajectory.json"
            )
            if trajectory_src.exists():
                trajectory_dst = path / self.TRAJECTORY_FILENAME
                trajectory_dst.write_text(trajectory_src.read_text())
                self.log.debug(
                    "Saved trajectory file",
                    src=str(trajectory_src),
                    dst=str(trajectory_dst),
                )

    def cleanup(self) -> None:
        """Clean up resources held by the OpenHands agent."""
        self.log.debug("agent.openhands.cleanup")

        if self._runtime is not None:
            self._runtime.cleanup()
            self._runtime = None

        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None

        self._session = None


# Register this agent type with the agent registry
register_agent("openhands", OpenHandsAgent)

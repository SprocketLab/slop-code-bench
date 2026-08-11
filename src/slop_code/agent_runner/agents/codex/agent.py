"Codex agent implementation."

from __future__ import annotations

import functools
import json
import os
import shlex
import shutil
import tempfile
import typing as tp
from pathlib import Path

from jinja2 import Template
from pydantic import Field
from pydantic import model_validator

from slop_code.agent_runner.agent import RETRY_PROMPT
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.agents.cli_utils import AgentCommandResult
from slop_code.agent_runner.agents.cli_utils import stream_cli_command
from slop_code.agent_runner.agents.codex.workflow import WorkflowConfig
from slop_code.agent_runner.agents.utils import HOME_PATH
from slop_code.agent_runner.agents.utils import copy_jsonl_files
from slop_code.agent_runner.agents.utils import find_jsonl_files
from slop_code.agent_runner.credentials import CredentialType
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.agent_runner.registry import register_agent
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import StreamingRuntime
from slop_code.execution.docker_runtime import DockerContextEntry
from slop_code.logging import get_logger

log = get_logger(__name__)


class CodexConfig(AgentConfigBase):
    """Configuration for ``CodexAgent`` instances."""

    type: tp.Literal["codex"] = "codex"
    version: str
    binary: str = "codex"
    docker_template: Path = Path(__file__).parent / "docker.j2"
    extra_args: list[str] = Field(
        default_factory=list,
        description="Additional arguments appended to the CLI invocation.",
    )
    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variable overrides applied to the invocation.",
    )
    timeout: int | None = Field(
        default=None,
        description="Optional timeout (in seconds) for the CLI invocation.",
    )
    workflow: WorkflowConfig | None = Field(
        default=None,
        description="Optional single-turn skill workflow.",
    )

    @model_validator(mode="after")
    def _reject_interactive_workflow_args(self) -> CodexConfig:
        if self.workflow is None:
            return self
        arguments = " ".join(self.extra_args)
        enables_user_input = "default_mode_request_user_input" in arguments and (
            "--enable" in arguments or "=true" in arguments.lower()
        )
        if enables_user_input:
            raise ValueError(
                "workflow extra_args cannot enable "
                "default_mode_request_user_input"
            )
        if any(arg in {"resume", "--last"} for arg in self.extra_args):
            raise ValueError(
                "workflow extra_args cannot select a resumed session"
            )
        return self

    def get_image(self, env_name: str) -> str:
        """Use a distinct image tag for each configured workflow."""
        base = super().get_image(env_name)
        if self.workflow is None:
            return base
        workflow_version = self.workflow.version
        if local_hash := self.workflow.local_packages_hash():
            workflow_version = f"{workflow_version}-local-{local_hash}"
        return (
            f"{self.type}-{self.version}-{self.workflow.type}-"
            f"{workflow_version}-{env_name}"
        )

    def get_docker_file(self, base_image: str) -> str | None:
        """Render the Docker template with configured dependencies."""
        if self.docker_template is None:
            return None
        template = self.docker_template.read_text()
        return Template(template).render(
            base_image=base_image,
            version=self.version,
            workflow_install_commands=(
                tuple(
                    shlex.join(command)
                    for command in self.workflow.install_commands
                )
                if self.workflow is not None
                else ()
            ),
            workflow_local_packages=(
                self.workflow.local_packages
                if self.workflow is not None
                else ()
            ),
        )

    def get_docker_context(self) -> dict[str, DockerContextEntry]:
        """Add configured local workflow packages to the image context."""
        if self.workflow is None:
            return {}
        return {
            package.context_path: DockerContextEntry(
                source=package.resolved_source(),
                excluded_names=frozenset(package.exclude),
            )
            for package in self.workflow.local_packages
        }

    def allocate_problem_resources(
        self,
        problem_names: list[str],
    ) -> CodexConfig:
        """Assign configured workflow resources before workers are spawned."""
        if self.workflow is None:
            return self
        workflow = self.workflow.allocate_problem_resources(problem_names)
        return self.model_copy(update={"workflow": workflow})


class CodexAgent(Agent):
    """Agent implementation built on top of the Codex CLI executor."""

    PROMPT_FILENAME = "prompt.txt"
    STDOUT_FILENAME = "stdout.jsonl"
    STDERR_FILENAME = "stderr.log"

    def __init__(
        self,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        image: str,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        credential: ProviderCredential | None,
        # Codex specific
        binary: str,
        model: str,
        timeout: int | None,
        thinking: ThinkingPreset | None,
        max_thinking_tokens: int | None,
        extra_args: list[str],
        env: dict[str, str],
        workflow: WorkflowConfig | None = None,
    ) -> None:
        super().__init__(
            agent_name="codex",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )

        # Store all config values as instance attributes
        self.credential = credential
        self.binary = binary
        self.model = model
        self.timeout = timeout
        self.thinking = thinking
        self.max_thinking_tokens = max_thinking_tokens
        self.extra_args = extra_args
        self.env = env
        self.workflow = workflow

        self._image = image
        self._session: Session | None = None

        self._environment: EnvironmentSpec | None = None
        self._runtime: StreamingRuntime | None = None
        self._trace_tmp: tempfile.TemporaryDirectory | None = None
        self._trace_dir: Path | None = None
        self._saved_trace_paths: set[Path] = set()
        self._workflow_initialized = False
        self._workflow_runtime_env: dict[str, str] | None = None

        # Get auth file from credential if it's a file credential
        self._auth_file: Path | None = None
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.FILE
        ):
            candidate = Path(self.credential.source)
            self._auth_file = candidate if candidate.exists() else None

        self._last_prompt: str = ""
        self._last_command: AgentCommandResult | None = None

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        verbose: bool,  # noqa: FBT001
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> Agent:
        """Create a CodexAgent from a CodexConfig."""
        if not isinstance(config, CodexConfig):
            raise TypeError(
                f"Expected CodexConfig, got {type(config).__name__}"
            )
        if image is None:
            raise ValueError("CodexAgent requires an image")

        # Get model slug for API calls
        model_slug = model.get_model_slug(credential.provider)

        # Resolve thinking: CLI/config override > model default
        thinking: ThinkingPreset | None = thinking_preset
        max_thinking_tokens: int | None = thinking_max_tokens
        if thinking is None and max_thinking_tokens is None:
            thinking, max_thinking_tokens = model.get_thinking_config("codex")

        return cls(
            problem_name=problem_name,
            verbose=verbose,
            image=image,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            credential=credential,
            binary=config.binary,
            model=model_slug,
            timeout=config.timeout,
            thinking=thinking,
            max_thinking_tokens=max_thinking_tokens,
            extra_args=config.extra_args,
            env=config.env,
            workflow=config.workflow,
        )

    @staticmethod
    def parse_line(
        line: str,
        pricing: APIPricing | None = None,
    ) -> tuple[float | None, TokenUsage | None, dict | None]:
        """Parse a single JSONL line from Codex output.

        Returns (cost, tokens, payload) matching Claude's pattern.
        """
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None, None, None

        if payload.get("type") == "event_msg":
            event_payload = payload.get("payload")
            if not isinstance(event_payload, dict):
                return None, None, payload
            if event_payload.get("type") != "token_count":
                return None, None, payload
            info = event_payload.get("info")
            if not isinstance(info, dict):
                return None, None, payload
            usage = info.get("total_token_usage")
            if not isinstance(usage, dict):
                return None, None, payload
            tokens = TokenUsage(
                input=int(usage.get("input_tokens") or 0),
                output=int(usage.get("output_tokens") or 0),
                cache_read=int(usage.get("cached_input_tokens") or 0),
                cache_write=0,
                reasoning=int(usage.get("reasoning_output_tokens") or 0),
            )
            raw_cost = info.get("total_cost") or info.get("cost_usd")
            cost = (
                float(raw_cost) if isinstance(raw_cost, int | float) else None
            )
            return cost, tokens, payload

        if payload.get("type") != "turn.completed":
            return None, None, payload

        usage = payload.get("usage") or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cached_tokens = usage.get("cached_input_tokens", 0)

        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cached_tokens,
            cache_write=0,
            reasoning=0,
        )

        cost = pricing.get_cost(tokens) if pricing else 0.0
        return (cost, tokens, payload)

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentError("CodexAgent has not been set up with a session")
        return self._session

    @property
    def spec(self) -> EnvironmentSpec:
        if self._environment is None:
            raise AgentError("CodexAgent has not been set up with a session")
        return self._environment

    @property
    def runtime(self) -> StreamingRuntime:
        if self._runtime is None:
            raise AgentError("CodexAgent has not been set up with a runtime")
        return self._runtime

    def setup(
        self,
        session: Session,
    ) -> None:
        workflow_env = self._resolve_workflow_environment()
        self._session = session
        self._environment = session.spec
        self._saved_trace_paths = set()
        mounts: dict[str, dict[str, str] | str] = {}
        if isinstance(session.spec, DockerEnvironmentSpec):
            workspace_base = os.environ.get("SCB_WORKSPACE_DIR")
            if workspace_base:
                Path(workspace_base).mkdir(parents=True, exist_ok=True)
            self._trace_tmp = tempfile.TemporaryDirectory(dir=workspace_base or None)
            self._trace_dir = Path(self._trace_tmp.name)
            self._trace_dir.mkdir(parents=True, exist_ok=True)
            self._trace_dir.chmod(0o777)
            if self._auth_file is not None:
                shutil.copy2(self._auth_file, self._trace_dir / "auth.json")
            mounts[str(self._trace_dir)] = {
                "bind": f"{HOME_PATH}/.codex",
                "mode": "rw",
            }

        env_vars = {"HOME": HOME_PATH}
        env_vars.update(workflow_env)
        self._runtime = session.spawn(
            mounts=mounts,
            env_vars=env_vars,
            image=self._image,
            user="agent",
            disable_setup=True,
        )

    def _resolve_workflow_environment(self) -> dict[str, str]:
        """Resolve configured workflow environment without persisting values."""
        if self.workflow is None:
            return {}
        if self._workflow_runtime_env is not None:
            return dict(self._workflow_runtime_env)

        missing = [
            name
            for name in self.workflow.env_from_host
            if name not in os.environ
        ]
        if missing:
            names = ", ".join(missing)
            raise AgentError(
                "Missing host environment variables required by workflow: "
                f"{names}"
            )

        resolved = dict(self.workflow.env)
        resolved.update(
            {name: os.environ[name] for name in self.workflow.env_from_host}
        )
        try:
            resolved.update(
                self.workflow.resource_environment(self.problem_name)
            )
        except ValueError as exc:
            raise AgentError(str(exc)) from exc
        self._workflow_runtime_env = resolved
        return dict(resolved)

    def _workflow_workspace(self) -> Path:
        if isinstance(self.spec, DockerEnvironmentSpec):
            return Path(self.spec.docker.workdir)
        return self.session.working_dir

    def _ensure_workflow_initialized(self) -> None:
        workflow = self.workflow
        if workflow is None or self._workflow_initialized:
            return

        command_env = dict(self.env)
        command_env.update(self._resolve_workflow_environment())
        for argv in workflow.init_commands:
            command = shlex.join(argv)
            for event in self.runtime.stream(
                command=command,
                env=command_env,
                timeout=(
                    float(self.timeout) if self.timeout is not None else None
                ),
            ):
                if event.kind == "finished":
                    result = event.result
                    break
            else:
                result = None
            if result is None:
                raise AgentError(f"Workflow init command did not finish: {command}")
            if result.timed_out:
                raise AgentError(f"Workflow init command timed out: {command}")
            if result.exit_code != 0:
                message = (
                    f"Workflow init command failed with exit code "
                    f"{result.exit_code}: {command}"
                )
                if result.stderr.strip():
                    message = (
                        f"{message}\n--- Stderr ---\n{result.stderr.strip()}"
                    )
                raise AgentError(message)

        workspace = self._workflow_workspace()
        for skill_path in workflow.required_skill_paths(workspace):
            relative = skill_path.relative_to(workspace)
            if not (self.session.working_dir / relative).is_file():
                raise AgentError(
                    f"Workflow initialization did not create {skill_path}"
                )
        self._workflow_initialized = True

    def _active_change_id(self) -> str:
        changes_dir = self.session.working_dir / "openspec" / "changes"
        candidates = sorted(
            path.name
            for path in changes_dir.iterdir()
            if path.is_dir() and path.name != "archive"
        ) if changes_dir.is_dir() else []
        if len(candidates) != 1:
            found = ", ".join(candidates) or "none"
            raise AgentError(
                "Expected exactly one active OpenSpec change for a workflow "
                f"node requiring change_id; found: {found}"
            )
        return candidates[0]

    def _workflow_prompts(self, task: str) -> tp.Iterator[str]:
        workflow = tp.cast("WorkflowConfig", self.workflow)
        for node in workflow.skills:
            change_id = (
                self._active_change_id()
                if node.needs_change_id
                else None
            )
            yield workflow.build_prompt(node, task, change_id)

    def run(self, task: str) -> None:
        self._last_prompt = task
        self._last_command = None

        execution_tasks: tp.Iterable[str] = (task,)
        invocation_count = 1
        if self.workflow is not None:
            self._ensure_workflow_initialized()
            execution_tasks = self._workflow_prompts(task)
            invocation_count = len(self.workflow.skills)

        log_kwargs: dict[str, tp.Any] = {
            "workspace": str(self.session.working_dir),
            "prompt_chars": len(task),
            "environment": self.session.spec.type,
            "extra_args": self.extra_args,
            "invocations": invocation_count,
        }
        if isinstance(self.session.spec, DockerEnvironmentSpec):
            log_kwargs["image"] = self.session.spec.docker.image
        self.log.info("agent.codex.start", **log_kwargs)

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        for execution_task in execution_tasks:
            command_result = self._run_invocation(execution_task)
            if command_result.stdout:
                stdout_parts.append(command_result.stdout.rstrip("\n") + "\n")
            if command_result.stderr:
                stderr_parts.append(command_result.stderr.rstrip("\n") + "\n")
            command_result.stdout = "".join(stdout_parts)
            command_result.stderr = "".join(stderr_parts)
            self._last_command = command_result
            self._sync_usage(command_result.usage_totals)
            self._raise_for_run_error(command_result)

    def _raise_for_run_error(
        self,
        command_result: AgentCommandResult,
    ) -> None:
        runtime_result = command_result.result
        if runtime_result is None:
            message = "Codex process failed to start"
            self.log.error(
                "agent.codex.start_failed",
                error_message=message,
                agent_message=command_result.error_message,
                stdout=command_result.stdout,
                stderr=command_result.stderr,
            )
            raise AgentError(message)
        if runtime_result.timed_out:
            message = (
                f"Codex process timed out after {self.timeout}s."
                if self.timeout is not None
                else "Codex process timed out."
            )
            self.log.error(
                "agent.codex.timeout",
                error_message=message,
                timeout=self.timeout,
            )
            raise AgentError(message)
        if runtime_result.exit_code != 0:
            message = f"Codex process failed with exit code {runtime_result.exit_code}"
            if runtime_result.stderr:
                message = f"{message}\n--- Stderr ---\n{runtime_result.stderr.strip()}"
            self.log.error(
                "agent.codex.exit",
                error_message=message,
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

    def retry(self) -> None:
        self._last_prompt = RETRY_PROMPT
        self._last_command = None

        self.log.info(
            "agent.codex.retry",
            workspace=str(self.session.working_dir),
            environment=self.session.spec.type,
        )

        command_result = self._run_invocation(RETRY_PROMPT, resume=True)
        self._last_command = command_result

        self._sync_usage(command_result.usage_totals)

        runtime_result = command_result.result
        if runtime_result is None:
            message = "Codex retry process failed to start"
            self.log.error(
                "agent.codex.retry.start_failed",
                error_message=message,
                agent_message=command_result.error_message,
            )
            raise AgentError(message)
        if runtime_result.timed_out:
            message = (
                f"Codex retry process timed out after {self.timeout}s."
                if self.timeout is not None
                else "Codex retry process timed out."
            )
            self.log.error(
                "agent.codex.retry.timeout",
                error_message=message,
                timeout=self.timeout,
            )
            raise AgentError(message)

        if runtime_result.exit_code != 0:
            message = (
                "Codex retry process failed with exit code "
                f"{runtime_result.exit_code}"
            )
            if runtime_result.stderr:
                message = f"{message}\n--- Stderr ---\n{runtime_result.stderr.strip()}"
            self.log.error(
                "agent.codex.retry.exit",
                error_message=message,
                exit_code=runtime_result.exit_code,
            )
            raise AgentError(message)

    def _run_invocation(
        self,
        task: str,
        *,
        resume: bool = False,
    ) -> AgentCommandResult:
        """Execute a Codex CLI invocation and return results."""
        command, env_overrides = self._prepare_runtime_execution(
            task,
            resume=resume,
        )

        if self._session is None:
            raise AgentError("CodexAgent has not been set up with a session")
        command_str = " ".join(command)

        # Use partial to bind pricing to parse_line
        parser = tp.cast(
            "tp.Callable[[str], tuple[float | None, TokenUsage | None, dict]]",
            functools.partial(self.parse_line, pricing=self.pricing),
        )

        total_tokens = TokenUsage()
        reported_total_tokens: TokenUsage | None = None
        reported_cost_micros = 0
        has_reported_cost = False
        step_count = 0
        runtime_result = None

        for item in stream_cli_command(
            runtime=self.runtime,
            command=command_str,
            parser=parser,
            env=env_overrides,
            timeout=(float(self.timeout) if self.timeout is not None else None),
        ):
            # Final item is RuntimeResult
            if not isinstance(item, tuple):
                runtime_result = item
                break

            cost, tokens, payload = item
            self.log.debug("Received item", item=item, verbose=True)

            # Count steps from turn.started and item.completed events
            if payload is not None:
                event_type = payload.get("type")
                if event_type == "event_msg":
                    event_payload = payload.get("payload")
                    if (
                        isinstance(event_payload, dict)
                        and event_payload.get("type") == "token_count"
                    ):
                        if tokens is not None:
                            reported_total_tokens = tokens
                            has_reported_cost = cost is not None
                            reported_cost_micros = (
                                int(round(float(cost) * 1_000_000))
                                if cost is not None
                                else 0
                            )
                        continue
                if event_type in ("turn.started", "item.completed"):
                    step_count += 1
                    self.usage.steps += 1

            if tokens is not None:
                total_tokens = total_tokens + tokens

        stdout = runtime_result.stdout if runtime_result else ""
        stderr = runtime_result.stderr if runtime_result else ""
        trace_cost, trace_tokens = self._read_latest_trace_usage()
        if trace_tokens is not None:
            reported_total_tokens = trace_tokens
            if trace_cost is not None:
                has_reported_cost = True
                reported_cost_micros = int(round(float(trace_cost) * 1_000_000))
        final_tokens = reported_total_tokens or total_tokens

        return AgentCommandResult(
            result=runtime_result,
            steps=[],
            usage_totals={
                "input_tokens": final_tokens.input,
                "output_tokens": final_tokens.output,
                "cached_input_tokens": final_tokens.cache_read,
                "reasoning_tokens": final_tokens.reasoning,
                "total_tokens": final_tokens.input + final_tokens.output,
                "steps": step_count,
                "reported_cost_present": int(has_reported_cost),
                "reported_cost_micros": reported_cost_micros,
            },
            stdout=stdout,
            stderr=stderr,
        )

    def _read_latest_trace_usage(
        self,
    ) -> tuple[float | None, TokenUsage | None]:
        if self._trace_dir is None:
            return None, None

        latest_cost: float | None = None
        latest_tokens: TokenUsage | None = None
        for path in self._new_trace_files():
            for line in path.read_text(encoding="utf-8").splitlines():
                cost, tokens, payload = self.parse_line(
                    line, pricing=self.pricing
                )
                if tokens is None or payload is None:
                    continue
                if payload.get("type") != "event_msg":
                    continue
                event_payload = payload.get("payload")
                if not isinstance(event_payload, dict):
                    continue
                if event_payload.get("type") != "token_count":
                    continue
                latest_tokens = tokens
                latest_cost = cost
        return latest_cost, latest_tokens

    def _new_trace_files(self) -> list[Path]:
        if self._trace_dir is None:
            return []
        return sorted(
            path
            for path in find_jsonl_files(self._trace_dir)
            if path.relative_to(self._trace_dir) not in self._saved_trace_paths
        )

    def _sync_usage(self, totals: dict[str, int]) -> None:
        totals = totals or {}
        input_tokens = int(totals.get("input_tokens") or 0)
        output_tokens = int(totals.get("output_tokens") or 0)
        cache_read_tokens = int(totals.get("cached_input_tokens") or 0)
        reasoning_tokens = int(totals.get("reasoning_tokens") or 0)
        tokens = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cache_read_tokens,
            reasoning=reasoning_tokens,
        )
        if int(totals.get("reported_cost_present") or 0):
            cost = (
                float(int(totals.get("reported_cost_micros") or 0)) / 1_000_000
            )
        else:
            cost = self.pricing.get_cost(tokens) if self.pricing else 0.0
        # Update tokens and cost without incrementing steps (already done during streaming)
        self.usage.cost += cost
        self.usage.net_tokens += tokens
        self.usage.current_tokens = tokens

        if self.cost_limits.is_above_limits(
            self.usage,
            prior_cost=self.prior_cost,
        ):
            raise AgentError("CodexAgent exceeded configured usage limits")

    def _prepare_runtime_execution(
        self,
        task: str,
        *,
        resume: bool = False,
    ) -> tuple[list[str], dict[str, str]]:
        """Prepare command and environment overrides for runtime execution."""
        env_overrides = {key: str(value) for key, value in self.env.items()}
        env_overrides.update(self._resolve_workflow_environment())

        # Set credential in environment if it's an env var credential
        if (
            self.credential is not None
            and self.credential.credential_type == CredentialType.ENV_VAR
        ):
            env_overrides[self.credential.destination_key] = (
                self.credential.value
            )
        command = self._build_command(task, resume=resume)

        return command, env_overrides

    def _build_command(
        self,
        prompt: str,
        *,
        resume: bool = False,
    ) -> list[str]:
        command = [self.binary, "exec"]
        if resume:
            command.extend(["resume", "--last"])
        command.extend(
            [
                shlex.quote(prompt),
                "--skip-git-repo-check",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
            ]
        )
        if self.model:
            command.extend(["--model", self.model])
            if self.model == "gpt-5.2-codex":
                command.extend(["--config", "model_verbosity='medium'"])

        # Handle thinking configuration
        if self.thinking in {"disabled", "none"}:
            # Disabled: omit model_reasoning_effort, set output tokens to 0
            command.extend(["--config", "model_max_output_tokens=0"])
        elif self.thinking:
            # Preset (low/medium/high): set reasoning effort
            command.extend(
                [
                    "--config",
                    f'model_reasoning_effort="{self.thinking}"',
                ]
            )

        elif self.max_thinking_tokens is not None:
            # Explicit token limit
            command.extend(
                [
                    "--config",
                    f"model_max_output_tokens={self.max_thinking_tokens}",
                ]
            )

        command.extend(self.extra_args)
        if self.workflow is not None:
            command.extend(["--disable", "default_mode_request_user_input"])
        return command

    @classmethod
    def _write_artifacts(
        cls,
        output_dir: Path,
        stdout_text: str,
        stderr_text: str,
    ) -> None:
        (output_dir / cls.STDOUT_FILENAME).write_text(stdout_text)
        (output_dir / cls.STDERR_FILENAME).write_text(stderr_text)

    def reset(self) -> None:
        self._last_prompt = ""
        self._last_command = None

    def save_artifacts(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        if self._last_prompt:
            (path / self.PROMPT_FILENAME).write_text(self._last_prompt)

        stdout_text = ""
        stderr_text = ""
        if self._last_command is not None:
            stdout_text = self._last_command.stdout or ""
            stderr_text = self._last_command.stderr or ""

        self._write_artifacts(path, stdout_text, stderr_text)
        self._save_codex_traces(path)

    def _save_codex_traces(self, output_dir: Path) -> None:
        if self._trace_dir is None:
            self.log.debug("agent.codex.traces.skipped", reason="no_trace_dir")
            return
        jsonl_files = find_jsonl_files(self._trace_dir)
        new_jsonl_files = [
            path
            for path in jsonl_files
            if path.relative_to(self._trace_dir) not in self._saved_trace_paths
        ]
        self.log.debug(
            "agent.codex.traces.found",
            trace_dir=str(self._trace_dir),
            files=len(jsonl_files),
        )
        copied = copy_jsonl_files(new_jsonl_files, output_dir)
        for path in new_jsonl_files:
            self._saved_trace_paths.add(path.relative_to(self._trace_dir))
        self.log.debug(
            "agent.codex.traces.saved",
            output_dir=str(output_dir),
            saved=len(copied),
        )

    def cleanup(self) -> None:
        """Clean up resources held by the Codex agent."""
        self._session = None
        if self._trace_tmp is not None:
            self._trace_tmp.cleanup()
            self._trace_tmp = None
            self._trace_dir = None
            self._saved_trace_paths = set()
        self._workflow_initialized = False
        self._workflow_runtime_env = None
        self.log.debug("agent.codex.cleanup")


# Register this agent type with the agent registry
register_agent("codex", CodexAgent)

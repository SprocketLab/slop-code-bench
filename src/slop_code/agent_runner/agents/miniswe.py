"""MiniSWE agent implementation."""

from __future__ import annotations

import os
import re
import subprocess
import time
import typing as tp
from pathlib import Path

from jinja2 import StrictUndefined
from jinja2 import Template

from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.credentials import ProviderCredential
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.registry import register_agent
from slop_code.agent_runner.trajectory import StepRole
from slop_code.agent_runner.trajectory import TrajectoryStep
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage
from slop_code.execution import DockerEnvironmentSpec
from slop_code.execution import EnvironmentSpecType
from slop_code.execution import LocalEnvironmentSpec
from slop_code.execution import Session

# This needs to be done before the imports to avoid logging startup messages
os.environ["MSWEA_SILENT_STARTUP"] = "1"
from minisweagent.agents import (
    default as miniswe_default,  # pylint: disable=C0413
)
from minisweagent.environments.docker import (
    DockerEnvironment,  # pylint: disable=C0413
)
from minisweagent.environments.local import (
    LocalEnvironment,  # pylint: disable=C0413
)
from minisweagent.models import get_model  # pylint: disable=C0413
from minisweagent.models import litellm_model  # pylint: disable=C0413
from minisweagent.models import openrouter_model  # pylint: disable=C0413
from minisweagent.models.utils.cache_control import (
    set_cache_control,
)  # pylint: disable=C0413

if tp.TYPE_CHECKING:
    from minisweagent import Model


def _or_query_no_cost_error(self, messages, **kwargs):
    # call the original _query (not the original query!) to get the raw API response
    response = self._query(messages, **kwargs)

    usage = response.get("usage") or {}
    # if cost is missing or falsy, treat it as 0.0 instead of raising
    cost = usage.get("cost")
    try:
        cost = float(cost) if cost is not None else 0.0
    except (TypeError, ValueError):
        cost = 0.0

    # update counters without erroring
    self.n_calls += 1
    self.cost += cost
    try:
        openrouter_model.GLOBAL_MODEL_STATS.add(cost)
    except NameError:
        # if GLOBAL_MODEL_STATS doesn't exist in this runtime, just ignore
        pass

    reasoning = response["choices"][0]["message"].pop("reasoning", None)

    return {
        "content": response["choices"][0]["message"].pop("content", "") or "",
        "reasoning": reasoning,
        "extra": response,
    }


def _litellm_query(self, messages: list[dict[str, str]], **kwargs) -> dict:
    import litellm

    if self.config.set_cache_control:
        messages = set_cache_control(messages, mode=self.config.set_cache_control)
    response = self._query(messages, **kwargs)
    try:
        cost = litellm.cost_calculator.completion_cost(response)
    except Exception as e:
        print(f"Error calculating cost for model {self.config.model_name}: {e}. ")
        raise
    self.n_calls += 1

    self.cost += cost
    return {
        "content": response.choices[0].message.content or "",  # type: ignore
        "extra": {
            "response": response.model_dump(),
        },
    }


openrouter_model.OpenRouterModel.query = _or_query_no_cost_error
litellm_model.LitellmModel.query = _litellm_query


def _default_model_config() -> dict[str, tp.Any]:
    """Return the default MiniSWE model configuration."""
    return {"model_name": "claude-3-5-sonnet-20241022"}


DEFAULT_SYSTEM_TEMPLATE = """You are a helpful assistant that can interact with a computer.

Your response must contain **EXACTLY ONE** bash code block with **ONE** command (or commands connected with && or ||).
Include a **THOUGHT** section before your command where you explain your reasoning process.
Format your response as shown in <format_example>.

<format_example>
Your reasoning and analysis here. Explain why you want to perform the action.

```bash
your_command_here
```
</format_example>

**Failure to follow these rules will cause your response to be rejected.**"""

DEFAULT_INSTANCE_TEMPLATE = """Please solve this issue: {{task}}

You can execute bash commands and edit files to implement the necessary changes.

## Recommended Workflow

This workflows should be done step-by-step so that you can iterate on your changes and any possible problems.

1. Analyze the codebase by finding and reading relevant files
2. Create a script to reproduce the issue
3. Edit the source code to resolve the issue
4. Verify your fix works by running your script again
5. Test edge cases to ensure your fix is robust
6. Submit your changes and finish your work by issuing the following command: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`.
    Do not combine it with any other command. <important>After this command, you cannot continue working on this task.</important>

## Important Rules

1. Every response must contain exactly one action
2. The action must be enclosed in triple backticks
3. Directory or environment variable changes are not persistent. Every action is executed in a new subshell.
    However, you can prefix any action with `MY_ENV_VAR=MY_VALUE cd /path/to/working/dir && ...` or write/load environment variables from files

## Formatting your response

Here is an example of a correct response:

<example_response>
THOUGHT: I need to understand the structure of the repository first. Let me check what files are in the current directory to get a better understanding of the codebase.

```bash
ls -la
```
</example_response>

## Useful command examples

### Create a new file:

```bash
cat <<'EOF' > newfile.py
import numpy as np
hello = "world"
print(hello)
EOF
```

### Edit files with sed:

```bash
# Replace all occurrences
sed -i 's/old_string/new_string/g' filename.py

# Replace only first occurrence
sed -i 's/old_string/new_string/' filename.py

# Replace first occurrence on line 1
sed -i '1s/old_string/new_string/' filename.py

# Replace all occurrences in lines 1-10
sed -i '1,10s/old_string/new_string/g' filename.py
```

### View file content:

```bash
# View specific lines with numbers
nl -ba filename.py | sed -n '10,20p'
```

### Any other command you want to run

```bash
anything
```"""

ACTION_OBSERVATION_TEMPLATE = """<returncode>{{output.returncode}}</returncode>
{% if output.output | length < 10000 -%}
<output>
{{ output.output -}}
</output>
{%- else -%}
<warning>
The output of your last command was too long.
Please try a different command that produces less output.
If you're looking at a file you can try use head, tail or sed to view a smaller number of lines selectively.
If you're using grep or find and it produced too much output, you can use a more selective search pattern.
If you really need to see something from the full command's output, you can redirect output to a file and then search in that file.
</warning>
{%- set elided_chars = output.output | length - 10000 -%}
<output_head>
{{ output.output[:5000] }}
</output_head>
<elided_chars>
{{ elided_chars }} characters elided
</elided_chars>
<output_tail>
{{ output.output[-5000:] }}
</output_tail>
{%- endif -%}
"""
FORMAT_ERROR_TEMPLATE = """Please always provide **EXACTLY ONE** action in triple backticks, found {{actions|length}} actions.
If you want to end the task, please issue the following command: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
without any other command.
Else, please format your response exactly as follows:

<response_example>
Here are some thoughts about why you want to perform the action.

```bash
<action>
```
</response_example>

Note: In rare cases, if you need to reference a similar format in your command, you might have
to proceed in two steps, first writing TRIPLEBACKTICKSBASH, then replacing them with ```bash."""


class MiniSWEAgentConfig(AgentConfigBase):
    """Configuration for ``MiniSWEAgent`` instances.

    Model is provided via ModelDefinition at agent creation time.
    """

    model_config = {"extra": "allow"}
    type: tp.Literal["mini_swe"] = "mini_swe"
    system_template: str = DEFAULT_SYSTEM_TEMPLATE
    instance_template: str = DEFAULT_INSTANCE_TEMPLATE
    timeout_template: str = (
        "The last command <command>{{action['action']}}</command> timed out and has been killed.\n"
        "The output of the command was:\n <output>\n{{output}}\n</output>\n"
        "Please try another command and make sure to avoid those requiring interactive input."
    )
    format_error_template: str = FORMAT_ERROR_TEMPLATE
    action_observation_template: str = ACTION_OBSERVATION_TEMPLATE

    def get_template_vars(self) -> dict:
        return {
            k: getattr(self, k)
            for k in {
                "system_template",
                "instance_template",
                "timeout_template",
                "action_observation_template",
            }
        }


class MiniSWEAgent(Agent):
    """Agent that wraps the default mini-swe-agent behaviour."""

    def __init__(
        self,
        problem_name: str,
        verbose: bool,
        # From base config
        cost_limits: AgentCostLimits,
        pricing: APIPricing | None,
        # MiniSWE specific
        model: Model,
        resolved_model_config: dict[str, tp.Any],
        system_template: str,
        instance_template: str,
        timeout_template: str,
        format_error_template: str,
        action_observation_template: str,
    ) -> None:
        super().__init__(
            agent_name="MiniSWE",
            problem_name=problem_name,
            cost_limits=cost_limits,
            pricing=pricing,
            verbose=verbose,
        )

        # Store all config values as instance attributes
        self.model = model
        self.resolved_model_config = resolved_model_config
        self.system_template = system_template
        self.instance_template = instance_template
        self.timeout_template = timeout_template
        self.format_error_template = format_error_template
        self.action_observation_template = action_observation_template

        self._finished = False
        self._steps = []
        self._messages = []
        self.extra_template_vars = {}
        self._env: DockerEnvironment | LocalEnvironment | None = None

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        model: ModelDefinition,
        credential: ProviderCredential,
        problem_name: str,
        verbose: bool,
        image: str | None,
        thinking_preset: ThinkingPreset | None = None,
        thinking_max_tokens: int | None = None,
    ) -> Agent:
        """Create a MiniSWEAgent from a MiniSWEAgentConfig."""
        if not isinstance(config, MiniSWEAgentConfig):
            raise TypeError(
                f"Expected MiniSWEAgentConfig, got {type(config).__name__}"
            )

        # Build model config from ModelDefinition
        model_cfg = cls._build_model_config(
            model, credential, thinking_preset, thinking_max_tokens
        )

        miniswe_model = get_model(None, model_cfg)
        # image is not used by MiniSWEAgent
        _ = image
        return cls(
            problem_name=problem_name,
            verbose=verbose,
            cost_limits=config.cost_limits,
            pricing=model.pricing,
            model=miniswe_model,
            resolved_model_config=model_cfg,
            system_template=config.system_template,
            instance_template=config.instance_template,
            timeout_template=config.timeout_template,
            format_error_template=config.format_error_template,
            action_observation_template=config.action_observation_template,
        )

    @classmethod
    def _build_model_config(
        cls,
        model: ModelDefinition,
        credential: ProviderCredential,
        thinking_preset: ThinkingPreset | None,
        thinking_max_tokens: int | None,
    ) -> dict[str, tp.Any]:
        """Build MiniSWE model config dict from ModelDefinition.

        Model name resolution (in order of priority):
            1. agent_specific.mini_swe.model_name (explicit override)
            2. provider_slugs[model_class] (e.g., provider_slugs.openrouter)
            3. internal_name (fallback)

        Optional settings from agent_specific.mini_swe:
            model_name: str - explicit model name override
            model_class: str - "litellm" | "openrouter" (default: "openrouter")
            api_base: str - API endpoint URL
            model_kwargs: dict - Additional kwargs for model constructor
        """
        settings = model.get_agent_settings("mini_swe") or {}
        model_class = settings.get("model_class", "openrouter")

        # Resolve model_name: explicit > provider_slugs > internal_name
        if "model_name" in settings:
            model_name = settings["model_name"]
        else:
            model_name = model.get_model_slug(model_class)

        model_cfg: dict[str, tp.Any] = {
            "model_name": model_name,
            "model_class": model_class,
        }

        # Build model_kwargs
        model_kwargs: dict[str, tp.Any] = {}

        # api_base -> model_kwargs.api_base
        if "api_base" in settings:
            model_kwargs["api_base"] = settings["api_base"]

        # Copy any explicit model_kwargs from settings
        if "model_kwargs" in settings:
            model_kwargs.update(settings["model_kwargs"])

        # Apply thinking configuration
        cls._apply_thinking_to_model_kwargs(
            model_kwargs, model_class, thinking_preset, thinking_max_tokens
        )

        # litellm models need API key and pricing
        if model_class == "litellm":
            model_kwargs["api_key"] = credential.value
            if model.pricing is not None:
                model_kwargs.update(
                    {
                        "input_cost_per_token": model.pricing.input / 1_000_000,
                        "output_cost_per_token": model.pricing.output / 1_000_000,
                    }
                )

        if model_kwargs:
            model_cfg["model_kwargs"] = model_kwargs

        return model_cfg

    @staticmethod
    def _apply_thinking_to_model_kwargs(
        model_kwargs: dict[str, tp.Any],
        model_class: str,
        thinking_preset: ThinkingPreset | None,
        thinking_max_tokens: int | None,
    ) -> None:
        """Apply thinking preset to model_kwargs based on model_class."""
        # max_thinking_tokens is not used by MiniSWE
        _ = thinking_max_tokens

        if thinking_preset is None or thinking_preset == "none":
            return

        if thinking_preset == "disabled":
            if model_class == "openrouter":
                model_kwargs["reasoning"] = {"enabled": False}
            return

        # For low/medium/high presets
        if model_class == "openrouter":
            model_kwargs["reasoning"] = {
                "effort": thinking_preset,
                "enabled": True,
                "exclude": False,
            }
        elif model_class == "litellm":
            model_kwargs["reasoning_effort"] = thinking_preset

    def supports_replay(self) -> bool:
        return True

    def add_message(self, role: str, content: str, **kwargs):
        self._messages.append({"role": role, "content": content, **kwargs})

    def _get_template_vars(self) -> dict[str, str]:
        """Return template variables from stored config values."""
        return {
            "system_template": self.system_template,
            "instance_template": self.instance_template,
            "timeout_template": self.timeout_template,
            "action_observation_template": self.action_observation_template,
        }

    def render_template(self, template: str, **kwargs) -> str:
        template_vars = (
            self._get_template_vars()
            | self.env.get_template_vars()
            | self.model.get_template_vars()
        )
        template_vars["step_limit"] = self.cost_limits.step_limit
        template_vars["cost_limit"] = self.cost_limits.cost_limit
        template_vars["net_cost_limit"] = self.cost_limits.net_cost_limit
        return Template(template, undefined=StrictUndefined).render(
            **kwargs, **template_vars, **self.extra_template_vars
        )

    def get_observation(self, response: dict):
        """Execute the action and return the observation."""
        t0 = time.time()
        output = {}
        try:
            output = self.execute_action(self.parse_action(response))
            observation = self.render_template(
                self.action_observation_template, output=output
            )
        except (
            miniswe_default.TerminatingException,
            miniswe_default.NonTerminatingException,
        ) as e:
            observation = str(e)
            if isinstance(e, miniswe_default.TerminatingException):
                self._finished = True
        finally:
            wall_clock_time = time.time() - t0
        self.record_non_agent_step(
            role=StepRole.ENVIRONMENT,
            content=observation,
            wall_clock_time=wall_clock_time,
            meta=output,
        )

    def parse_action(self, response: dict) -> dict:
        """Parse the action from the message. Returns the action."""
        actions = re.findall(r"```bash\s*\n(.*?)\n```", response["content"], re.DOTALL)

        self.log.debug(
            "Parsed actions",
            num_actions=len(actions),
            first_action=actions[0].strip()[:100] if actions else "",
            response=response["content"][:100],
        )
        if len(actions) == 1:
            return {"action": actions[0].strip(), **response}
        raise miniswe_default.FormatError(
            self.render_template(self.format_error_template, actions=actions)
        )

    def execute_action(self, action: dict) -> dict:
        try:
            output = self.env.execute(action["action"])
        except subprocess.TimeoutExpired as e:
            output = e.output.decode("utf-8", errors="replace") if e.output else ""
            raise miniswe_default.ExecutionTimeoutError(
                self.render_template(
                    self.timeout_template, action=action, output=output
                )
            )
        except TimeoutError as e:
            raise miniswe_default.ExecutionTimeoutError(
                self.render_template(
                    self.timeout_template, action=action, output=""
                )
            ) from e

        self.log.debug(
            "Executing an action",
            action=action["action"][:100],
            output=output.get("output", "N/A")[:100],
        )
        self.has_finished(output)
        return output

    def has_finished(self, output: dict[str, str]):
        """Raises Submitted exception with final output if the agent has finished its task."""
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() in [
            "MINI_SWE_AGENT_FINAL_OUTPUT",
            "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
        ]:
            raise miniswe_default.Submitted("".join(lines[1:]))

    @property
    def env(self) -> DockerEnvironment | LocalEnvironment:
        if self._env is None:
            raise ValueError("Environment not set")
        return self._env

    def setup(self, session: Session) -> None:
        self._env = self.build_environment(session.working_dir, session.spec)
        for command in session.spec.setup.commands:
            self._env.execute(command)

    @staticmethod
    def build_environment(
        workspace: Path,
        env_spec: EnvironmentSpecType,
    ) -> DockerEnvironment | LocalEnvironment:
        if isinstance(env_spec, LocalEnvironmentSpec):
            env_vars = {str(k): str(v) for k, v in env_spec.environment.env.items()}
            return LocalEnvironment(cwd=str(workspace), env=env_vars)

        if isinstance(env_spec, DockerEnvironmentSpec):
            run_args = ["--rm"]
            if env_spec.docker.mount_workspace:
                host_path = workspace.resolve()
                run_args.extend(["-v", f"{host_path}:{env_spec.docker.workdir}"])
            for host, container in env_spec.docker.extra_mounts.items():
                host_path = Path(host)
                if not host_path.is_absolute():
                    host_path = (workspace / host_path).resolve()
                run_args.extend(["-v", f"{host_path}:{str(container)}"])

            if env_spec.docker.network:
                run_args.extend(["--network", env_spec.docker.network])
            user = env_spec.get_actual_user()
            if user:
                run_args.extend(["--user", user])
            env_vars = {str(k): str(v) for k, v in env_spec.environment.env.items()}
            return DockerEnvironment(
                image=env_spec.get_base_image(),
                cwd=env_spec.docker.workdir,
                env=env_vars,
                run_args=run_args,
            )

        raise NotImplementedError(
            f"Unsupported environment spec type: {env_spec.type!r}"
        )

    def record_non_agent_step(
        self, role: StepRole, content: str, wall_clock_time: float, **kwargs
    ):
        self._steps.append(
            TrajectoryStep(
                role=role,
                content=content,
                wall_clock_time=wall_clock_time,
                **kwargs,
            )
        )
        self.add_message("system" if role == StepRole.SYSTEM else "user", content)

    def agent_step(self) -> dict | None:
        if self.cost_limits.is_above_limits(self.usage, prior_cost=self.prior_cost):
            self.log.debug(
                "Hit agent limits",
                cost=self.usage.cost,
                steps=self.usage.steps,
                total_cost=self.usage.cost,
                step_limit=self.cost_limits.step_limit,
                cost_limit=self.cost_limits.cost_limit,
                net_cost_limit=self.cost_limits.net_cost_limit,
            )
            self._finished = True
            raise miniswe_default.LimitsExceeded("Agent hit cost or step limits")
        self.log.debug(
            "Querying model",
            calls=self.usage.steps,
            cost=self.usage.cost,
            input_tokens=self.usage.net_tokens.input,
            output_tokens=self.usage.net_tokens.output,
            cache_read_tokens=self.usage.net_tokens.cache_read,
            cache_write_tokens=self.usage.net_tokens.cache_write,
            reasoning_tokens=self.usage.net_tokens.reasoning,
        )
        t0 = time.time()
        try:
            query = self.model.query(self._messages)
        except Exception as e:
            self.log.error(
                "Error querying model",
                error=e,
                messages=self._messages,
                error_type=type(e).__name__,
            )
            self.log.exception(e, exc_info=True)
            return None
        wall_clock_time = time.time() - t0

        response_dict = query.get("extra", {})
        cache_read_tokens = cache_write_tokens = reasoning_tokens = None
        if "usage" in response_dict:
            usage = response_dict["usage"]
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            cache_read_tokens = usage.get("prompt_tokens_details", {}).get(
                "cached_tokens", 0
            )
            cache_write_tokens = usage.get("prompt_tokens_details", {}).get(
                "cache_creation_tokens", 0
            )
            reasoning_tokens = usage.get("completion_tokens_details", {}).get(
                "reasoning_tokens", 0
            )
        else:
            input_tokens = getattr(self.model, "input_tokens", 0)
            output_tokens = getattr(self.model, "output_tokens", 0)

        step_cost = self.model.cost
        token_usage = TokenUsage(
            input=input_tokens,
            output=output_tokens,
            cache_read=cache_read_tokens or 0,
            cache_write=cache_write_tokens or 0,
            reasoning=reasoning_tokens or 0,
        )
        if self.pricing is not None:
            step_cost = self.pricing.get_cost(token_usage)

        step = TrajectoryStep(
            role=StepRole.ASSISTANT,
            content=query["content"],
            wall_clock_time=wall_clock_time,
            cost=step_cost,
            tokens=token_usage,
            meta=query["extra"],
        )
        self.usage.step(
            cost=step_cost,
            tokens=token_usage,
        )

        self._steps.append(step)
        self.add_message(
            "assistant", content=step.content, reasoning=query.get("reasoning")
        )
        return query

    def run(self, task: str):
        self.log.debug("Running MiniSWE agent", prior_steps=len(self._steps))
        self.extra_template_vars = {"task": task}
        if not self._messages:
            if self._steps:
                raise ValueError("No messages but steps is not empty!")
            if self.model.cost != 0 or self.model.n_calls != 0:
                raise ValueError("No messages but model has a cost or calls")
            self.log.debug("Adding system message")
            system_content = self.render_template(self.system_template)
            self.record_non_agent_step(
                role=StepRole.SYSTEM,
                content=system_content,
                wall_clock_time=0.0,
            )

        task_content = self.render_template(self.instance_template)
        self.record_non_agent_step(
            role=StepRole.USER, content=task_content, wall_clock_time=0.0
        )

        while not self._finished:
            try:
                response = self.agent_step()
                if response is None:
                    break
                self.get_observation(response)
                self.log.info(
                    "Finished a step",
                    step=self.usage.steps,
                    cost=self.usage.cost,
                    input_tokens=self.usage.current_tokens.input,
                    reasoning_tokens=self.usage.net_tokens.reasoning,
                    total_tokens=self.usage.current_tokens.total,
                    generated_tokens=self.usage.current_tokens.output,
                )
            except miniswe_default.LimitsExceeded:
                # Limits hit, exit gracefully
                break

        self.log.debug(
            "Finished",
            model_calls=self.usage.steps,
            cost=self.usage.cost,
            num_steps=self.usage.steps,
        )
        return self._steps

    def reset(self):
        self.log.debug(
            "Resetting agent state",
            num_calls=self.model.n_calls,
            cost=self.model.n_calls,
            num_steps=len(self._steps),
        )

        # Use resolved model config to create a fresh model instance
        new_model = get_model(None, self.resolved_model_config)
        del self.model
        self.model = new_model
        del self._steps
        del self._messages
        self._finished = False
        self._messages = []
        self._steps = []

    def save_artifacts(self, path: Path) -> None:
        with (path / "trajectory.jsonl").open("w", encoding="utf-8") as f:
            for step in self._steps:
                f.write(step.model_dump_json() + "\n")

    def cleanup(self) -> None:
        """Clean up the environment resources."""
        self.log.debug("Cleaning up MiniSWE agent resources")
        if hasattr(self.env, "cleanup"):
            self.env.cleanup()
        self.log.debug("Cleanup completed")


# Register this agent type with the agent registry
register_agent("mini_swe", MiniSWEAgent)

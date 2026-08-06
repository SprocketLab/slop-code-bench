"""Tests for the minimal Codex workflow integration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from slop_code.agent_runner.agents.cli_utils import AgentCommandResult
from slop_code.agent_runner.agents.codex import CodexAgent
from slop_code.agent_runner.agents.codex.workflow import WorkflowConfig
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentError
from slop_code.execution import LocalEnvironmentSpec
from slop_code.execution.runtime import RuntimeEvent
from slop_code.execution.runtime import RuntimeResult


def _success() -> RuntimeResult:
    return RuntimeResult(
        exit_code=0,
        stdout="",
        stderr="",
        setup_stdout="",
        setup_stderr="",
        elapsed=0.01,
        timed_out=False,
    )


class FakeRuntime:
    def __init__(self, results: list[RuntimeResult]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def stream(
        self,
        command: str,
        env: dict[str, str],
        timeout: float | None,
        stdin: str | list[str] | None = None,
    ) -> Iterable[RuntimeEvent]:
        self.calls.append(
            {
                "command": command,
                "env": env,
                "timeout": timeout,
                "stdin": stdin,
            }
        )
        yield RuntimeEvent(kind="finished", result=self.results.pop(0))

    def cleanup(self) -> None:
        pass


@dataclass
class FakeSession:
    runtime: FakeRuntime
    working_dir: Path
    spec: LocalEnvironmentSpec
    spawn_env: dict[str, str] | None = None

    def spawn(self, **kwargs: object) -> FakeRuntime:
        self.spawn_env = dict(kwargs.get("env_vars", {}))
        return self.runtime


def _workflow(**overrides: object) -> WorkflowConfig:
    values: dict[str, object] = {
            "type": "openspec",
            "version": "1.7.0",
            "install_commands": [
                ["npm", "install", "-g", "@fission-ai/openspec@1.7.0"]
            ],
            "init_commands": [
                ["openspec", "config", "set", "delivery", "skills"],
                ["openspec", "init", ".", "--tools", "codex", "--force"],
            ],
            "env": {"CI": "true", "OPENSPEC_TELEMETRY": "0"},
            "skills": [
                {"name": "openspec-propose", "arguments": ["{task}"]},
                {
                    "name": "openspec-apply-change",
                    "arguments": ["{change_id}"],
                },
                {
                    "name": "openspec-sync-specs",
                    "arguments": ["{change_id}"],
                },
                {
                    "name": "openspec-archive-change",
                    "arguments": ["{change_id}"],
                },
            ],
        }
    values.update(overrides)
    return WorkflowConfig.model_validate(values)


def _agent(
    tmp_path: Path,
    runtime: FakeRuntime,
    workflow: WorkflowConfig | None = None,
) -> tuple[CodexAgent, FakeSession]:
    workflow = workflow or _workflow()
    for path in workflow.required_skill_paths(tmp_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Test skill\n")

    session = FakeSession(
        runtime=runtime,
        working_dir=tmp_path,
        spec=LocalEnvironmentSpec(name="test"),
    )
    agent = CodexAgent(
        problem_name="test-problem",
        verbose=False,
        image="test-image",
        cost_limits=AgentCostLimits(
            step_limit=0,
            cost_limit=0,
            net_cost_limit=0,
        ),
        pricing=None,
        credential=None,
        binary="codex",
        model="gpt-test",
        timeout=60,
        thinking=None,
        max_thinking_tokens=None,
        extra_args=[],
        env={"EXISTING": "yes"},
        workflow=workflow,
    )
    agent.setup(session)  # type: ignore[arg-type]
    return agent, session


def test_host_environment_is_passed_without_entering_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_API_KEY", "host-secret")
    workflow = _workflow(env_from_host=["EMBEDDING_API_KEY"])
    agent, session = _agent(tmp_path, FakeRuntime([]), workflow)

    _, invocation_env = agent._prepare_runtime_execution("task")

    assert session.spawn_env is not None
    assert session.spawn_env["EMBEDDING_API_KEY"] == "host-secret"
    assert invocation_env["EMBEDDING_API_KEY"] == "host-secret"
    assert "host-secret" not in str(workflow.model_dump())


def test_missing_host_environment_fails_before_container_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    workflow = _workflow(env_from_host=["EMBEDDING_API_KEY"])
    runtime = FakeRuntime([])

    with pytest.raises(AgentError, match="EMBEDDING_API_KEY"):
        _agent(tmp_path, runtime, workflow)


def test_problem_resource_is_injected_into_init_and_codex_environment(
    tmp_path: Path,
) -> None:
    workflow = _workflow(
        resource_pool={
            "env_var": "ARTNET_NEO4J_URI",
            "values": ["bolt://neo4j-exp1:7687"],
        }
    ).allocate_problem_resources(["test-problem"])
    agent, session = _agent(tmp_path, FakeRuntime([]), workflow)

    _, invocation_env = agent._prepare_runtime_execution("task")

    expected = "bolt://neo4j-exp1:7687"
    assert session.spawn_env is not None
    assert session.spawn_env["ARTNET_NEO4J_URI"] == expected
    assert invocation_env["ARTNET_NEO4J_URI"] == expected


def _command_result() -> AgentCommandResult:
    return AgentCommandResult(
        result=_success(),
        steps=[],
        usage_totals={},
        stdout='{"type":"turn.completed"}\n',
        stderr="",
    )


def test_init_precedes_independent_node_execs_and_runs_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime([_success(), _success()])
    agent, session = _agent(tmp_path, runtime)
    invocations: list[tuple[str, bool]] = []

    def fake_invocation(task: str, *, resume: bool = False) -> AgentCommandResult:
        invocations.append((task, resume))
        if task.startswith("$openspec-propose\n"):
            change = tmp_path / "openspec" / "changes" / "test-change"
            change.mkdir(parents=True, exist_ok=True)
        return _command_result()

    monkeypatch.setattr(agent, "_run_invocation", fake_invocation)

    agent.run("checkpoint one")
    agent.reset()
    agent.run("checkpoint two")

    assert [call["command"] for call in runtime.calls] == [
        "openspec config set delivery skills",
        "openspec init . --tools codex --force",
    ]
    assert all(call["env"]["CI"] == "true" for call in runtime.calls)
    assert len(invocations) == 8
    assert all(resume is False for _, resume in invocations)
    expected_skills = [
        "openspec-propose",
        "openspec-apply-change",
        "openspec-sync-specs",
        "openspec-archive-change",
    ]
    for index, skill in enumerate(expected_skills):
        prompt = invocations[index][0]
        assert skill in prompt
        assert all(other not in prompt for other in expected_skills if other != skill)
        if skill == "openspec-propose":
            assert "checkpoint one" in prompt
        else:
            assert "checkpoint one" not in prompt
        if skill != "openspec-propose":
            assert "test-change" in prompt
    for index, skill in enumerate(expected_skills, start=4):
        prompt = invocations[index][0]
        assert skill in prompt
        if skill == "openspec-propose":
            assert "checkpoint two" in prompt
        else:
            assert "checkpoint two" not in prompt
            assert "test-change" in prompt
    assert session.spawn_env is not None
    assert session.spawn_env["OPENSPEC_TELEMETRY"] == "0"


def test_workflow_command_disables_interactive_questions(tmp_path: Path) -> None:
    agent, _ = _agent(tmp_path, FakeRuntime([]))

    command = agent._build_command("workflow prompt")

    assert command.count("exec") == 1
    assert "resume" not in command
    assert command[-2:] == [
        "--disable",
        "default_mode_request_user_input",
    ]


def test_init_failure_prevents_codex_exec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = _success().model_copy(update={"exit_code": 2, "stderr": "bad init"})
    agent, _ = _agent(tmp_path, FakeRuntime([failure]))
    invoked = False

    def fake_invocation(task: str, *, resume: bool = False) -> AgentCommandResult:
        nonlocal invoked
        invoked = True
        return _command_result()

    monkeypatch.setattr(agent, "_run_invocation", fake_invocation)

    with pytest.raises(AgentError, match="Workflow init command failed"):
        agent.run("checkpoint")

    assert invoked is False


def test_artifacts_keep_original_checkpoint_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, _ = _agent(tmp_path, FakeRuntime([_success(), _success()]))
    change = tmp_path / "openspec" / "changes" / "test-change"
    change.mkdir(parents=True)
    monkeypatch.setattr(agent, "_run_invocation", lambda task: _command_result())

    agent.run("original checkpoint markdown")
    output_dir = tmp_path / "artifacts"
    agent.save_artifacts(output_dir)

    assert (output_dir / "prompt.txt").read_text() == (
        "original checkpoint markdown"
    )

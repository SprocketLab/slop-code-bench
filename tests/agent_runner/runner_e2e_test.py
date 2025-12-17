import json
import queue
from pathlib import Path

import pytest

from slop_code.agent_runner import runner
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import AgentConfigBase
from slop_code.agent_runner.models import AgentCostLimits
from slop_code.agent_runner.models import AgentRunSpec
from slop_code.common.llms import TokenUsage
from slop_code.evaluation import PassPolicy
from slop_code.evaluation import ProblemConfig
from slop_code.execution import LocalEnvironmentSpec
from slop_code.execution import Session
from slop_code.execution.models import CommandConfig
from slop_code.execution.models import EnvironmentConfig
from slop_code.execution.models import SetupConfig
from slop_code.execution.session import Session


class DummyAgent(Agent):
    def __init__(
        self,
        checkpoint_solutions: list[dict[str, str]],
        num_steps: int,
        step_tokens: int,
        step_cost: float,
        agent_name: str,
        problem_name: str,
        cost_limits: AgentCostLimits,
        verbose: bool,
    ):
        super().__init__(agent_name, problem_name, cost_limits, None, verbose)
        self.checkpoint_solutions = checkpoint_solutions
        self.working_dir: Path | None = None
        self.num_steps = num_steps
        self.step_tokens = step_tokens
        self.step_cost = step_cost
        self._chkpt_num = 0
        self.context: list[str] = []

    def setup(self, session: Session) -> None:
        self.working_dir = session.working_dir

    def run(self, task: str):
        if self.working_dir is None:
            raise ValueError("Working directory not set")
        for i in range(self.num_steps):
            cur = self.usage.current_tokens

            self.usage.step(
                cost=self.step_cost,
                tokens=TokenUsage(
                    input=cur.input + self.step_tokens,
                    output=cur.output + self.step_tokens + 1,
                    cache_read=cur.cache_read + self.step_tokens + 2,
                    cache_write=cur.cache_write + self.step_tokens + 3,
                    reasoning=cur.reasoning + self.step_tokens + 4,
                ),
            )
        self._finalize_checkpoint(task, is_replay=False)

    def supports_replay(self) -> bool:
        return True

    def reset(self) -> None:
        self.context = []

    def save_artifacts(self, path: Path) -> None:
        with (path / "context.json").open("w") as f:
            json.dump(self.context, f)

    def cleanup(self) -> None:
        return

    @classmethod
    def _from_config(
        cls,
        config: AgentConfigBase,
        problem_name: str,
        verbose: bool,
        image: str | None,
    ) -> Agent:
        raise NotImplementedError("DummyAgent is for testing only")

    def _finalize_checkpoint(self, task: str, *, is_replay: bool) -> None:
        label = f"replay:{task}" if is_replay else task
        self.context.append(label)
        self._write_checkpoint_solution()

    def _write_checkpoint_solution(self) -> None:
        assert self.working_dir is not None
        for file, content in self.checkpoint_solutions[self._chkpt_num].items():
            (self.working_dir / file).write_text(content)
        self._chkpt_num += 1


def build_dummy_agent(
    checkpoint_solutions: list[dict[str, str]],
) -> DummyAgent:
    return DummyAgent(
        checkpoint_solutions=checkpoint_solutions,
        num_steps=3,
        step_tokens=100,
        step_cost=1.0,
        agent_name="dummy",
        problem_name="dummy",
        cost_limits=AgentCostLimits(
            step_limit=10,
            cost_limit=100,
            net_cost_limit=100,
        ),
        verbose=True,
    )


@pytest.fixture()
def resources_path() -> Path:
    return Path(__file__).parent / "resources"


@pytest.fixture()
def solutions_path(resources_path: Path) -> Path:
    return resources_path / "solutions"


@pytest.fixture(params=["inventory_cli_debug_problem"])
def problem_info(
    resources_path: Path, solutions_path: Path, request: pytest.FixtureRequest
) -> tuple[ProblemConfig, list[dict[str, str]]]:
    problem = ProblemConfig.from_yaml(resources_path / request.param)
    solutions = []
    problem_solutions = solutions_path / request.param
    for checkpoint_name, _ in problem.iterate_checkpoint_items():
        solutions.append(
            {
                f"{problem.entry_file}.py": (
                    problem_solutions / f"{checkpoint_name}.py"
                ).read_text(),
            }
        )
    return problem, solutions


@pytest.fixture()
def local_environment() -> LocalEnvironmentSpec:
    return LocalEnvironmentSpec(
        name="local",
        type="local",
        setup=SetupConfig(eval_commands=[]),
        environment=EnvironmentConfig(include_os_env=True),
        commands=CommandConfig(command="uv run", entry_file="{entry_file}.py"),
    )


@pytest.fixture()
def session(local_environment: LocalEnvironmentSpec) -> Session:
    return Session.from_environment_spec(
        spec=local_environment,
        base_dir=None,
        static_assets={},
        is_agent_infer=True,
    )


@pytest.fixture()
def output_dir(tmpdir: Path) -> Path:
    out = Path(tmpdir) / "agent_result"
    out.mkdir(parents=True, exist_ok=True)
    return out


@pytest.fixture()
def run_spec(
    problem_info: tuple[ProblemConfig, list[dict[str, str]]],
    local_environment: LocalEnvironmentSpec,
) -> AgentRunSpec:
    problem, _ = problem_info
    return AgentRunSpec(
        seed=67,
        template="This is a test template: {{task}}",
        problem=problem,
        environment=local_environment,
        image="test-local-image",
        pass_policy=PassPolicy.ANY,
        skip_evaluation=False,
        verbose=True,
    )


def test_agent_run_problem(
    problem_info: tuple[ProblemConfig, list[dict[str, str]]],
    output_dir: Path,
    run_spec: AgentRunSpec,
) -> None:
    problem, solutions = problem_info
    agent = build_dummy_agent(solutions)
    run_spec.problem = problem
    progress_queue = queue.Queue()
    result = runner.run_agent(
        run_spec=run_spec,
        agent=agent,
        output_path=output_dir,
        progress_queue=progress_queue,
    )
    assert not progress_queue.empty()
    summary = result["summary"]
    assert summary["passed_policy"]
    assert summary["state"] == "completed"
    assert summary["total_usage"]["net_tokens"] == {
        "input": 1200,
        "output": 1212,
        "cache_read": 1224,
        "cache_write": 1236,
        "reasoning": 1248,
    }
    assert summary["total_usage"]["current_tokens"] == {
        "input": 600,
        "output": 606,
        "cache_read": 612,
        "cache_write": 618,
        "reasoning": 624,
    }
    assert summary["total_steps"] == 6
    assert summary["total_cost"] == pytest.approx(6.0)


def test_checkpoint_snapshots_exclude_tar_archives(
    problem_info: tuple[ProblemConfig, list[dict[str, str]]],
    output_dir: Path,
    run_spec: AgentRunSpec,
) -> None:
    problem, solutions = problem_info
    run_spec.problem = problem

    agent = build_dummy_agent(solutions)
    progress_queue = queue.Queue()

    runner.run_agent(
        run_spec=run_spec,
        agent=agent,
        output_path=output_dir,
        progress_queue=progress_queue,
    )

    for checkpoint_index, (checkpoint_name, _) in enumerate(
        problem.iterate_checkpoint_items()
    ):
        snapshot_dir = output_dir / checkpoint_name / "snapshot"
        assert snapshot_dir.exists() and snapshot_dir.is_dir()

        tar_candidates = [
            path
            for path in snapshot_dir.rglob("*")
            if path.is_file()
            and (path.name.endswith(".tar") or ".tar." in path.name)
        ]
        assert not tar_candidates, "Snapshot directory contains tar archive"

        expected_files = solutions[checkpoint_index].keys()
        for relative_path in expected_files:
            snapshot_file = snapshot_dir / relative_path
            assert snapshot_file.exists(), (
                f"Expected snapshot to contain {relative_path} for {checkpoint_name}"
            )

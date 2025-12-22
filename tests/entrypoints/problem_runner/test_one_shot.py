from __future__ import annotations

from pathlib import Path

from slop_code.entrypoints.config.run_config import OneShotConfig
from slop_code.entrypoints.problem_runner.one_shot import apply_one_shot_mode
from slop_code.evaluation import ProblemConfig


def test_apply_one_shot_mode_combines_specs():
    tests_root = Path(__file__).resolve().parents[2]
    problem_path = (
        tests_root / "agent_runner/resources/inventory_cli_debug_problem"
    )
    problem_config = ProblemConfig.from_yaml(problem_path)

    combined = apply_one_shot_mode(
        problem_config=problem_config,
        one_shot=OneShotConfig(enabled=True, prefix="PREFIX"),
    )

    checkpoints = list(combined.iterate_checkpoint_items())
    assert len(checkpoints) == 1
    checkpoint_name, checkpoint = checkpoints[0]

    spec1 = (problem_path / "checkpoint_1.md").read_text()
    spec2 = (problem_path / "checkpoint_2.md").read_text()

    assert checkpoint_name == "checkpoint_2"
    assert checkpoint.order == 1
    assert (
        combined.get_checkpoint_spec(checkpoint_name)
        == f"{spec1}PREFIX\n{spec2}"
    )


def test_apply_one_shot_prefix_template_renders_idx():
    tests_root = Path(__file__).resolve().parents[2]
    problem_path = (
        tests_root / "agent_runner/resources/inventory_cli_debug_problem"
    )
    problem_config = ProblemConfig.from_yaml(problem_path)

    combined = apply_one_shot_mode(
        problem_config=problem_config,
        one_shot=OneShotConfig(enabled=True, prefix="--- {{ idx }} ---"),
    )

    spec1 = (problem_path / "checkpoint_1.md").read_text()
    spec2 = (problem_path / "checkpoint_2.md").read_text()

    checkpoint = next(combined.iterate_checkpoints())
    assert (
        combined.get_checkpoint_spec(checkpoint.name)
        == f"{spec1}--- 2 ---\n{spec2}"
    )


def test_apply_one_shot_prefix_on_first_checkpoint():
    tests_root = Path(__file__).resolve().parents[2]
    problem_path = (
        tests_root / "agent_runner/resources/inventory_cli_debug_problem"
    )
    problem_config = ProblemConfig.from_yaml(problem_path)

    combined = apply_one_shot_mode(
        problem_config=problem_config,
        one_shot=OneShotConfig(
            enabled=True,
            prefix="::: {{ idx }} :::",
            include_first_prefix=True,
        ),
    )

    spec1 = (problem_path / "checkpoint_1.md").read_text()
    spec2 = (problem_path / "checkpoint_2.md").read_text()

    checkpoint = next(combined.iterate_checkpoints())
    assert (
        combined.get_checkpoint_spec(checkpoint.name)
        == f"::: 1 :::\n{spec1}::: 2 :::\n{spec2}"
    )

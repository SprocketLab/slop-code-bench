from __future__ import annotations

from pathlib import Path

import yaml

from slop_code.common import CHECKPOINT_CONFIG_NAME
from slop_code.common import PROBLEM_CONFIG_NAME
from slop_code.entrypoints.commands import eval_run_dir
from slop_code.evaluation import ProblemConfig


def test_write_problem_and_checkpoint_configs_overwrites(tmp_path: Path) -> None:
    source_problem = ProblemConfig.from_yaml(
        Path("tests/agent_runner/resources/tiny_settings_cli_debug_problem")
    )

    problem_dir = tmp_path / source_problem.name
    problem_dir.mkdir()
    for checkpoint_name in source_problem.checkpoints:
        (problem_dir / checkpoint_name).mkdir(parents=True)

    # Seed a stale config to verify overwrite behavior.
    with (problem_dir / PROBLEM_CONFIG_NAME).open("w") as f:
        yaml.safe_dump(
            {"name": source_problem.name, "version": 0, "checkpoints": {}},
            f,
            sort_keys=True,
        )

    eval_run_dir._write_problem_and_checkpoint_configs(problem_dir, source_problem)

    with (problem_dir / PROBLEM_CONFIG_NAME).open("r") as f:
        saved_problem = yaml.safe_load(f)
    assert saved_problem["name"] == source_problem.name
    assert saved_problem["version"] == source_problem.version

    for checkpoint_name, checkpoint in source_problem.iterate_checkpoint_items():
        checkpoint_yaml = problem_dir / checkpoint_name / CHECKPOINT_CONFIG_NAME
        assert checkpoint_yaml.exists()
        with checkpoint_yaml.open("r") as f:
            saved_checkpoint = yaml.safe_load(f)
        assert saved_checkpoint["version"] == checkpoint.version
        assert Path(saved_checkpoint["path"]).name == checkpoint_name


import json
import shutil
from pathlib import Path

import pytest

from slop_code.evaluation import run_checkpoint
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.report import CorrectnessResults
from slop_code.execution import EnvironmentSpecType


@pytest.fixture(params=["local", "docker"])
def environment(
    request, local_environment_spec, docker_environment_spec
) -> EnvironmentSpecType:
    if request.param == "local":
        return local_environment_spec
    if request.param == "docker":
        return docker_environment_spec
    raise ValueError(f"Invalid environment: {request.param}")


@pytest.fixture()
def example_directory() -> Path:
    return Path(__file__).parents[2] / "examples"


def get_yaml_correct_submission(
    root_path, checkpoint: str
) -> tuple[Path, Path, CorrectnessResults]:
    yaml_path = root_path / "yaml_joiner"
    problem_path = yaml_path / "problem"
    submission_path = yaml_path / "submission"
    correct_submission = submission_path / "correct"
    expected_path = submission_path / "expected" / "correct.json"
    with expected_path.open("r") as f:
        expected = json.load(f)
        expected = {
            k: CorrectnessResults.model_validate(v) for k, v in expected.items()
        }
    return problem_path, correct_submission, expected[checkpoint]


@pytest.fixture(
    params=[["yaml_joiner", "checkpoint_1"], ["yaml_joiner", "checkpoint_2"]],
    ids=["yaml_joiner-checkpoint_1", "yaml_joiner-checkpoint_2"],
)
def correct_submission(
    example_directory, request, tmpdir
) -> tuple[Path, str, Path, CorrectnessResults]:
    problem_name, checkpoint = request.param
    match problem_name:
        case "yaml_joiner":
            loader = get_yaml_correct_submission
        case _:
            raise ValueError(f"Invalid submission: {request.param}")

    problem_path, submission_path, expected = loader(example_directory, checkpoint)
    submission_dir = Path(tmpdir) / "submission"
    shutil.copytree(submission_path, submission_dir)
    return problem_path, checkpoint, submission_dir, expected


@pytest.fixture()
def ran_checkpoint(
    correct_submission, environment
) -> tuple[CorrectnessResults, CorrectnessResults]:
    problem_path, checkpoint, submission_path, expected = correct_submission
    problem_config = ProblemConfig.from_yaml(problem_path)
    checkpoint_config = problem_config.load_checkpoint(checkpoint)
    result = run_checkpoint(
        checkpoint=checkpoint_config,
        problem=problem_config,
        submission_path=submission_path,
        env_spec=environment,
    )
    return result, expected


def test_overall_report_correct(ran_checkpoint):
    actual, expected = ran_checkpoint

    def make_check_dict(r):
        out = {
            k: v
            for k, v in r.items()
            if k not in {"environment", "reports", "duration", "timestamp"}
        }
        for v in out["group_outcomes"].values():
            v.pop("duration")
        return out

    actual = make_check_dict(actual.model_dump())
    expected = make_check_dict(expected.model_dump())

    assert actual == expected

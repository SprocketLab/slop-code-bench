import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from slop_code.evaluation.config import ProblemConfig


@dataclass(frozen=True)
class ToyProblem:
    path: Path
    config: ProblemConfig
    checkpoint_names: tuple[str, ...]
    group_name: str
    case_name: str
    expected_outputs: dict[str, str]


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _write_case(directory: Path, *, expected_output: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "EXPECTED").write_text(
        f"{expected_output}\n", encoding="utf-8"
    )
    (directory / "STATUS_CODE").write_text("0\n", encoding="utf-8")
    (directory / "META.yaml").write_text("{}\n", encoding="utf-8")


@pytest.fixture
def toy_problem(tmp_path_factory: pytest.TempPathFactory) -> ToyProblem:
    root = Path(tmp_path_factory.mktemp("toy_problem"))
    problem_dir = root / "toy_problem"
    checkpoint_names = ("checkpoint_1", "checkpoint_2")
    group_name = "group_ok"
    case_name = "case_one"

    expected_outputs = {
        checkpoint_names[0]: "CHECKPOINT_ONE_PASS",
        checkpoint_names[1]: "CHECKPOINT_TWO_PASS",
    }

    # Problem-level config
    problem_payload = {
        "name": problem_dir.name,
        "version": 1,
        "description": "Toy problem for task runner integration tests.",
        "tags": ["test"],
        "category": "internal",
        "difficulty": "Easy",
        "checkpoints": list(checkpoint_names),
        "constant_files": ["constants/global.txt"],
    }
    _write_yaml(problem_dir / "config.yaml", problem_payload)
    problem_config = ProblemConfig.model_validate(problem_payload)
    constant_dir = problem_dir / "constants"
    constant_dir.mkdir(parents=True, exist_ok=True)
    (constant_dir / "global.txt").write_text(
        "GLOBAL_CONSTANT\n", encoding="utf-8"
    )
    (problem_dir / "design_doc.md").write_text(
        "Toy design doc\n", encoding="utf-8"
    )

    for checkpoint in checkpoint_names:
        checkpoint_dir = problem_dir / checkpoint
        _write_yaml(
            checkpoint_dir / "config.yaml",
            {
                "version": 1,
                "groups": [group_name],
                "adapter": {"type": "cli", "entry_file": "main.py"},
                "specification": "spec.md",
                "timeout": 60,
            },
        )
        (checkpoint_dir / "spec.md").write_text(
            textwrap.dedent(
                f"""
                # {checkpoint}

                Minimal specification content.
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        group_dir = checkpoint_dir / group_name
        _write_yaml(
            group_dir / "config.yaml",
            {
                "loader": {
                    "type": "nested",
                    "include": "case_*",
                    "patterns": ["**/*"],
                },
                "verifiers": {
                    "status": {
                        "type": "status_code",
                        "value": 0,
                    },
                    "output_match": {
                        "type": "exact_match",
                        "result_attr": "output",
                    },
                },
                "normalizers": [],
                "expected_normalizers": [],
                "group_files": [],
                "constant_files": [],
                "constants": {},
                "case_overrides": {},
            },
        )
        _write_case(
            group_dir / case_name,
            expected_output=expected_outputs[checkpoint],
        )

    return ToyProblem(
        path=problem_dir,
        config=problem_config,
        checkpoint_names=checkpoint_names,
        group_name=group_name,
        case_name=case_name,
        expected_outputs=expected_outputs,
    )


@pytest.fixture(scope="session")
def debug_problem_path() -> Path:
    """Filesystem location of the manual debug problem for agent-runner smoke tests."""
    return (
        Path(__file__).resolve().parent
        / "resources"
        / "inventory_api_debug_problem"
    )

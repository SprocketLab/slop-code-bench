import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from slop_code.evaluation.adapters import cli
from slop_code.execution import Session
from slop_code.execution import Snapshot
from slop_code.execution import Workspace


@pytest.fixture(params=["main", "arg_main"])
def submission_files(request) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Parametrize basic CLI cases: simple print and argument echo."""
    match request.param:
        case "main":
            case = {
                "id": "main",
                "group_type": "Functionality",
                "group": "test_group",
                "checkpoint": "test_checkpoint",
                "expected": {
                    "output": "Hello, world!",
                },
            }
            files = {
                "main.py": b"print('Hello, world!')",
            }
        case "arg_main":
            case = {
                "id": "arg_main",
                "group_type": "Functionality",
                "group": "test_group",
                "checkpoint": "test_checkpoint",
                "arguments": ["1", "2", "3"],
                "expected": {
                    "output": "1",
                },
            }
            files = {
                "main.py": b"import sys\nprint(sys.argv[1])",
            }
        case _:
            raise ValueError(f"Invalid entry file: {request.param}")
    return case, files


@pytest.fixture
def submission(tmpdir, submission_files) -> tuple[Path, dict[str, bytes]]:
    """Create a temporary submission directory with provided case files."""
    _, files = submission_files
    tmpdir = Path(tmpdir)
    sub_dir = tmpdir / "sub"
    sub_dir.mkdir()
    for file, content in files.items():
        with (sub_dir / file).open("wb") as f:
            f.write(content)
    return sub_dir, files


@pytest.fixture
def adapter(submission, local_environment_spec):
    """Return a `CLIAdapter` initialized with a local execution manager."""
    sub_dir, _ = submission
    spec = local_environment_spec

    def snapshot_fn(cwd: Path) -> Snapshot:
        return Snapshot.from_directory(cwd, env=os.environ.copy())

    initial_snapshot = snapshot_fn(sub_dir)
    workspace = Workspace(
        initial_snapshot=initial_snapshot,
        snapshot_fn=snapshot_fn,
        is_agent_infer=False,
    )
    session = Session(spec, workspace)
    yield cli.CLIAdapter(
        session=session,
        env=os.environ.copy(),
        cfg=cli.CLIAdapterConfig(),
        command=f"{shutil.which('python3') or shutil.which('python')} main.py",
        timeout=10,
    )


def test_adapter_run(adapter: cli.CLIAdapter, submission_files):
    """Run a CLI case and assert status/output match expectations."""
    case_dict, _ = submission_files
    case = cli.CLICase.model_validate(case_dict)
    expected_output = case_dict["expected"]["output"]
    with adapter:
        result = adapter.run_case(case)
    assert result.status_code == 0
    assert result.output.strip() == expected_output.strip()

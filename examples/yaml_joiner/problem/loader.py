from __future__ import annotations

import shlex
from collections.abc import Generator
from pathlib import Path

import yaml

from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import GroupConfig
from slop_code.evaluation.adapters import CLICase
from slop_code.evaluation.adapters import CLIResult
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.loaders import CaseStore
from slop_code.evaluation.loaders import helpers
from slop_code.evaluation.loaders.loader_protocol import NoOpStore
from slop_code.execution.file_ops import InputFile


def load_case_dir(
    case_dir: Path, group_config: GroupConfig, checkpoint_name: str
) -> tuple[CLICase, CLIResult]:
    input_files = helpers.get_files_from_globs(
        case_dir, ["*.yaml", "**/*.yaml"], exclude={"result.yaml", "ARGS"}
    )
    args = shlex.split((case_dir / "ARGS").read_text())
    with (case_dir / "result.yaml").open("r") as f:
        result = yaml.safe_load(f)

    input_files = [
        InputFile.from_path(relative_to=case_dir, path=file)
        for file in input_files
    ]

    input_files.extend(
        InputFile.from_path(relative_to=case_dir.parent, path=Path(group_file))
        for group_file in group_config.group_files
    )

    case = CLICase(
        id=case_dir.name,
        group=group_config.name,
        group_type=group_config.type,
        checkpoint=checkpoint_name,
        original_group=group_config.original_group,
        original_checkpoint=group_config.original_checkpoint,
        arguments=args,
        input_files=input_files,
        tracked_files=["result.yaml"],
    )
    result_obj = CLIResult(
        id=case_dir.name,
        group=group_config.name,
        group_type=group_config.type,
        status_code=0,
        files={"result.yaml": result},
    )
    return case, result_obj


class Loader:
    def __init__(
        self,
        problem: ProblemConfig,
        checkpoint: CheckpointConfig,
        *,
        use_placeholders: bool = False,
    ):
        self.problem = problem
        self.checkpoint = checkpoint
        self.use_placeholders = use_placeholders

    def initialize_store(self) -> CaseStore:
        """Initialize the case store."""
        return NoOpStore()

    def __call__(
        self, group: GroupConfig, store: CaseStore
    ) -> Generator[tuple[CLICase, CLIResult], None, None]:
        _ = store
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)

        for case_dir in helpers.discover_dir_cases(group, group_dir):
            yield load_case_dir(case_dir, group, self.checkpoint.name)

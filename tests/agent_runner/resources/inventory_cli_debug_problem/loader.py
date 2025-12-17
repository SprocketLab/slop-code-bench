from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import yaml

from slop_code.evaluation import GroupConfig
from slop_code.evaluation.adapters import CLICase
from slop_code.evaluation.adapters import CLIResult
from slop_code.evaluation.loaders import BaseLoader
from slop_code.evaluation.loaders import CaseStore
from slop_code.evaluation.loaders import helpers


def _load_case(
    case_dir: Path,
    group_config: GroupConfig,
    checkpoint_name: str,
    order: int,
) -> tuple[CLICase, CLIResult]:
    meta_path = case_dir / "META.yaml"
    meta = (yaml.safe_load(meta_path.read_text()) if meta_path.exists() else {}) or {}

    case_id = meta.get("id", case_dir.name)
    expected_meta = meta.get("expected", {}) or {}

    expected_path = case_dir / "EXPECTED.json"
    expected_output = (
        json.loads(expected_path.read_text()) if expected_path.exists() else None
    )

    case = CLICase(
        id=case_id,
        group=group_config.name,
        group_type=group_config.type,
        checkpoint=checkpoint_name,
        order=order,
        arguments=[str(arg) for arg in meta.get("arguments", []) or []],
        stdin=meta.get("stdin"),
        timeout_s=meta.get("timeout_s"),
        tracked_files=meta.get("tracked_files", []) or [],
    )

    expected = CLIResult(
        id=case_id,
        group=group_config.name,
        group_type=group_config.type,
        status_code=expected_meta.get("status_code", 0),
        output=expected_output,
    )

    return case, expected


class Loader(BaseLoader):
    def __call__(
        self, group: GroupConfig, store: CaseStore
    ) -> Generator[tuple[CLICase, CLIResult], None, None]:
        _ = store
        group_dir = helpers.get_group_path(group, self.problem, self.checkpoint)
        for order, case_dir in enumerate(helpers.discover_dir_cases(group, group_dir)):
            yield _load_case(case_dir, group, self.checkpoint.name, order)

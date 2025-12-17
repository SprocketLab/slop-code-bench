from __future__ import annotations

from pathlib import Path

import pytest

from slop_code.evaluation.adapters.cli import CLIAdapterConfig
from slop_code.evaluation.adapters.models import GroupType
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.loaders import helpers
from slop_code.evaluation.loaders.loader_protocol import LoaderError


def _build_problem_and_checkpoint(
    tmp_path: Path,
    group: GroupConfig,
) -> tuple[ProblemConfig, CheckpointConfig]:
    problem_dir = tmp_path / "sample-problem"
    checkpoint_dir = problem_dir / "checkpoint-current"
    problem_dir.mkdir()
    checkpoint_dir.mkdir(parents=True)

    loader_path = problem_dir / "loader.py"
    loader_path.write_text("class Loader:\n    ...\n")
    entry_file = problem_dir / "entry.py"
    entry_file.write_text("print('hello')\n")

    checkpoint_config = CheckpointConfig(
        version=1,
        order=1,
        path=checkpoint_dir,
        groups={group.name: group},
        constant_files=set(),
        specification="spec.md",
        state="Draft",
    )

    problem_config = ProblemConfig(
        name="Sample",
        path=problem_dir,
        version=1,
        description="demo",
        tags=["demo"],
        checkpoints={"checkpoint-current": checkpoint_config},
        entry_file=entry_file.name,
        loader_script=loader_path.name,
        loader_entrypoint="Loader",
        adapter=CLIAdapterConfig(),
    )

    return problem_config, checkpoint_config


def test_expand_pattern_handles_globs_and_directories(tmp_path: Path) -> None:
    base = tmp_path
    (base / "root.txt").write_text("root\n")
    nested = base / "nested"
    nested.mkdir()
    (nested / "a.txt").write_text("a\n")
    (nested / "b.log").write_text("b\n")

    glob_matches = helpers._expand_pattern(base, "*.txt")
    assert {p.relative_to(base).as_posix() for p in glob_matches} == {"root.txt"}

    dir_matches = helpers._expand_pattern(base, "nested")
    assert {
        p.relative_to(base).as_posix() for p in dir_matches
    } == {"nested/a.txt", "nested/b.log"}

    literal_match = helpers._expand_pattern(base, "nested/a.txt")
    assert {p.relative_to(base).as_posix() for p in literal_match} == {"nested/a.txt"}

    assert helpers._expand_pattern(base, "missing.txt") == set()


def test_should_include_file_respects_literal_excludes(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("data\n")

    include_patterns: list[str | Path] = ["*.txt"]
    exclude_patterns: list[str | Path] = ["data.txt"]
    excluded_files = {target}

    assert not helpers._should_include_file(
        target, excluded_files, include_patterns, exclude_patterns, tmp_path
    )


def test_should_include_file_allows_reinclusion_with_specific_glob(tmp_path: Path) -> None:
    base = tmp_path / "dir"
    base.mkdir()
    target = base / "keep.txt"
    nested_target = base / "nested" / "keep.txt"
    nested_target.parent.mkdir(parents=True)
    target.write_text("keep\n")
    nested_target.write_text("nested\n")

    include_patterns = ["dir", "**/keep.txt"]
    exclude_patterns = ["dir/**/*.txt"]

    excluded_files = {target, nested_target}

    assert helpers._should_include_file(
        target, excluded_files, include_patterns, exclude_patterns, tmp_path
    )
    assert helpers._should_include_file(
        nested_target, excluded_files, include_patterns, exclude_patterns, tmp_path
    )


def test_should_include_file_handles_invalid_include_patterns(tmp_path: Path) -> None:
    base = tmp_path / "dir"
    base.mkdir()
    target = base / "skip.txt"
    target.write_text("skip\n")

    include_patterns = ["[invalid"]
    exclude_patterns = ["dir/*.txt"]
    excluded_files = {target}

    assert not helpers._should_include_file(
        target, excluded_files, include_patterns, exclude_patterns, tmp_path
    )


def test_get_files_from_globs_applies_include_and_exclude(tmp_path: Path) -> None:
    base = tmp_path
    (base / "root.txt").write_text("root\n")

    dir1 = base / "dir1"
    dir1.mkdir()
    (dir1 / "common.txt").write_text("common\n")
    (dir1 / "keep.txt").write_text("keep\n")
    (dir1 / "keep.log").write_text("log\n")

    sub = dir1 / "sub"
    sub.mkdir()
    (sub / "exclude.txt").write_text("exclude\n")
    (sub / "keep.txt").write_text("nested\n")

    result = helpers.get_files_from_globs(base, ["*.txt", "dir1"])
    assert set(result) == {
        Path("root.txt"),
        Path("dir1/common.txt"),
        Path("dir1/keep.log"),
        Path("dir1/keep.txt"),
        Path("dir1/sub/exclude.txt"),
        Path("dir1/sub/keep.txt"),
    }

    result_with_exclude = helpers.get_files_from_globs(
        base, ["dir1"], exclude={"dir1/sub"}
    )
    assert set(result_with_exclude) == {
        Path("dir1/common.txt"),
        Path("dir1/keep.txt"),
        Path("dir1/keep.log"),
    }

    result_with_reinclude = helpers.get_files_from_globs(
        base,
        ["dir1", "**/keep.txt"],
        exclude={"dir1/**/*.txt"},
    )
    assert set(result_with_reinclude) == {
        Path("dir1/keep.txt"),
        Path("dir1/sub/keep.txt"),
        Path("dir1/keep.log"),
    }


def test_discover_dir_cases_skips_group_directories(tmp_path: Path) -> None:
    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "groupA").mkdir()
    (checkpoint_dir / "groupB").mkdir()
    (checkpoint_dir / "unrelated").mkdir()
    (checkpoint_dir / "not_a_dir").write_text("file\n")

    group_config = GroupConfig(name="groupA", group_files={"groupA/case.json"})

    discovered = list(helpers.discover_dir_cases(group_config, checkpoint_dir))
    assert {path.name for path in discovered} == {"groupB", "unrelated"}


def test_get_group_path_returns_checkpoint_directory(tmp_path: Path) -> None:
    group = GroupConfig(name="groupA")
    problem, checkpoint = _build_problem_and_checkpoint(tmp_path, group)

    group_dir = checkpoint.path / group.name
    group_dir.mkdir()

    resolved = helpers.get_group_path(group, problem, checkpoint)
    assert resolved == group_dir


def test_get_group_path_resolves_regression_source(tmp_path: Path) -> None:
    regression_group = GroupConfig(
        name="regression",
        type=GroupType.REGRESSION,
        original_checkpoint="checkpoint-previous",
        original_group="group-original",
    )
    problem, checkpoint = _build_problem_and_checkpoint(tmp_path, regression_group)

    original_dir = problem.path / regression_group.original_checkpoint / regression_group.original_group
    original_dir.mkdir(parents=True)

    resolved = helpers.get_group_path(regression_group, problem, checkpoint)
    assert resolved == original_dir


def test_get_group_path_raises_for_missing_regression_metadata(tmp_path: Path) -> None:
    regression_group = GroupConfig(name="regression", type=GroupType.REGRESSION)
    problem, checkpoint = _build_problem_and_checkpoint(tmp_path, regression_group)

    with pytest.raises(LoaderError):
        helpers.get_group_path(regression_group, problem, checkpoint)


def test_get_group_path_raises_when_directory_missing(tmp_path: Path) -> None:
    group = GroupConfig(name="group-missing")
    problem, checkpoint = _build_problem_and_checkpoint(tmp_path, group)

    with pytest.raises(LoaderError):
        helpers.get_group_path(group, problem, checkpoint)

"""Checkpoint test collection helpers for pytest-based evaluation."""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from slop_code.common import WORKSPACE_TEST_DIR
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult
from slop_code.execution.assets import resolve_static_assets
from slop_code.execution.models import EnvironmentSpec
from slop_code.execution.session import Session
from slop_code.logging import get_logger

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_NOTESTSCOLLECTED = 5
VALID_COLLECTION_EXIT_CODES = {EXIT_OK, EXIT_NOTESTSCOLLECTED}

TEST_DEPENDENCIES = [
    "pytest",
    "pytest-json-ctrf",
    "pytest-json-report",
    "pytest-timeout",
    "jsonschema",
    "deepdiff",
]


@dataclass(frozen=True)
class CollectedTestCase:
    nodeid: str
    test_id: str
    file_path: str
    checkpoint: str
    group_type: GroupType


@dataclass(frozen=True)
class CheckpointTestCollection:
    tests: list[CollectedTestCase]
    by_nodeid: dict[str, CollectedTestCase]
    grouped_test_ids: dict[str, list[str]]
    total_collected: int
    test_collection_hash: str
    infrastructure_failure: bool = False


def _as_test_id(nodeid: str) -> str:
    if "::" not in nodeid:
        return nodeid
    return nodeid.split("::", 1)[-1]


def _as_file_path(nodeid: str) -> str:
    if "::" not in nodeid:
        return ""
    return nodeid.split("::", 1)[0]


def _infer_checkpoint_from_file(
    file_path: str,
    fallback: str,
) -> str:
    name = Path(file_path).name
    if not name.startswith("test_") or not name.endswith(".py"):
        return fallback
    return name.removeprefix("test_").removesuffix(".py")


def _copy_tests_from_problem(
    *,
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    workspace_path: Path,
) -> None:
    import shutil

    workspace_tests = workspace_path / WORKSPACE_TEST_DIR
    problem_tests = problem.path / "tests"

    if workspace_tests.exists():
        return

    if not problem_tests.exists():
        raise RuntimeError(
            f"No tests directory found."
            f" workspace={workspace_tests} problem={problem_tests}"
        )

    checkpoint_files: set[str] = set()
    if checkpoint.include_prior_tests:
        for checkpoint_name, _ in problem.iterate_checkpoint_items():
            checkpoint_files.add(f"test_{checkpoint_name}.py")
            if checkpoint_name == checkpoint.name:
                break
    else:
        checkpoint_files.add(f"test_{checkpoint.name}.py")

    workspace_tests.mkdir(parents=True, exist_ok=True)

    for item in problem_tests.iterdir():
        if item.is_file():
            is_checkpoint_test = (
                item.name.startswith("test_")
                and item.name.endswith(".py")
                and item.name != "conftest.py"
            )
            if item.name == "conftest.py":
                shutil.copy2(item, workspace_tests / item.name)
            elif is_checkpoint_test:
                if item.name in checkpoint_files:
                    shutil.copy2(item, workspace_tests / item.name)
            else:
                shutil.copy2(item, workspace_tests / item.name)
            continue

        if item.is_dir() and item.name != "__pycache__":
            shutil.copytree(item, workspace_tests / item.name)


def _generate_pytest_ini(problem: ProblemConfig, workspace_path: Path) -> None:
    markers_lines = [
        "    error: error-handling / edge-case tests",
        "    functionality: non-core / nice-to-have tests",
        "    regression: regression tests",
    ]
    for marker_name, marker_config in problem.markers.items():
        if marker_name in {"error", "functionality", "regression"}:
            continue
        markers_lines.append(f"    {marker_name}: {marker_config.description}")

    markers_section = "\n".join(markers_lines)
    content = f"""[pytest]
testpaths = tests
markers =
{markers_section}
"""
    (workspace_path / "pytest.ini").write_text(content)


def _build_with_flags(problem: ProblemConfig) -> list[str]:
    deps = list(TEST_DEPENDENCIES) + list(problem.test_dependencies or [])
    return [f"--with={dep}" for dep in deps]


def _quote_args(extra_args: list[str] | None) -> list[str]:
    return [shlex.quote(arg) for arg in extra_args or []]


def _build_collect_cmd(
    *,
    problem: ProblemConfig,
    checkpoint_name: str,
    entrypoint: str,
    marker: str | None,
    pytest_args: list[str] | None,
) -> str:
    parts = [
        "uvx",
        *_build_with_flags(problem),
        "pytest",
        "--collect-only",
        "-q",
        # Exclude an agent-authored conftest.py at the workspace root from
        # collection (SCBench's own conftest lives inside WORKSPACE_TEST_DIR).
        f"--confcutdir={WORKSPACE_TEST_DIR}",
        f"--entrypoint={shlex.quote(entrypoint)}",
        f"--checkpoint={shlex.quote(checkpoint_name)}",
    ]

    if marker is not None:
        parts.extend(["-m", shlex.quote(marker)])

    parts.extend(["-k", shlex.quote(checkpoint_name)])
    parts.extend(_quote_args(pytest_args))
    parts.append(WORKSPACE_TEST_DIR)
    return " ".join(parts)


def _parse_collect_stdout(stdout: str) -> list[str]:
    nodeids: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("=") or stripped.startswith("collected "):
            continue
        if "::" not in stripped:
            continue
        if " " in stripped:
            continue
        nodeids.append(stripped)
    return nodeids


def _group_key(checkpoint: str, group_type: GroupType) -> str:
    return f"{checkpoint}-{group_type.value}"


def compute_tc_hash(grouped_test_ids: dict[str, list[str]]) -> str:
    """Compute deterministic hash from grouped test identifiers."""
    canonical: list[dict[str, Any]] = []
    for key in sorted(grouped_test_ids.keys()):
        canonical.append(
            {
                "group": key,
                "ids": sorted(set(grouped_test_ids[key])),
            }
        )

    encoded = json.dumps(
        canonical,
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def collect_checkpoint_tc(
    *,
    submission_path: Path,
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    env_spec: EnvironmentSpec,
    pytest_args: list[str] | None = None,
) -> CheckpointTestCollection:
    """Collect checkpoint tests via marker passes and return classification."""
    resolved_assets = resolve_static_assets(
        base_path=problem.path,
        assets=problem.static_assets,
    )

    session = Session.from_environment_spec(
        spec=env_spec,
        base_dir=submission_path,
        static_assets=resolved_assets,
        is_agent_infer=False,
    )

    try:
        session.prepare()
        workspace_path = session.workspace.working_dir
        _copy_tests_from_problem(
            problem=problem,
            checkpoint=checkpoint,
            workspace_path=workspace_path,
        )

        materialized_assets = (
            session.workspace.materialize_static_assets_for_tests()
        )
        asset_env_vars: dict[str, str] = {}
        if materialized_assets:
            assets_dir = Path(WORKSPACE_TEST_DIR, "assets")
            asset_env_vars["SCBENCH_ASSETS_DIR"] = str(assets_dir)
            for name in materialized_assets:
                asset_env_vars[f"SCBENCH_ASSET_{name.upper()}"] = str(
                    assets_dir / name
                )

        _generate_pytest_ini(problem, workspace_path)

        entrypoint = env_spec.get_command(
            problem.entry_file, is_agent_run=False
        )
        full_env = {
            **env_spec.get_full_env(checkpoint.env),
            **asset_env_vars,
        }

        marker_map: dict[str | None, set[str]] = {
            "error": set(),
            "functionality": set(),
            "regression": set(),
            None: set(),
        }

        infrastructure_failure = False

        for marker in ("error", "functionality", "regression", None):
            cmd = _build_collect_cmd(
                problem=problem,
                checkpoint_name=checkpoint.name,
                entrypoint=entrypoint,
                marker=marker,
                pytest_args=pytest_args,
            )
            runtime = session.exec(command=cmd)
            try:
                result = runtime.execute(full_env, None, None)
            finally:
                runtime.cleanup()

            if result.exit_code not in VALID_COLLECTION_EXIT_CODES:
                infrastructure_failure = True
                logger.error(
                    "Checkpoint collection pass failed",
                    checkpoint=checkpoint.name,
                    marker=marker,
                    exit_code=result.exit_code,
                )
                continue

            marker_map[marker].update(_parse_collect_stdout(result.stdout))

        if checkpoint.include_prior_tests:
            for prior_name, _ in problem.iterate_checkpoint_items():
                if prior_name == checkpoint.name:
                    break
                cmd = _build_collect_cmd(
                    problem=problem,
                    checkpoint_name=prior_name,
                    entrypoint=entrypoint,
                    marker=None,
                    pytest_args=pytest_args,
                )
                runtime = session.exec(command=cmd)
                try:
                    result = runtime.execute(full_env, None, None)
                finally:
                    runtime.cleanup()

                if result.exit_code not in VALID_COLLECTION_EXIT_CODES:
                    infrastructure_failure = True
                    logger.error(
                        "Prior checkpoint collection pass failed",
                        checkpoint=checkpoint.name,
                        prior_checkpoint=prior_name,
                        exit_code=result.exit_code,
                    )
                    continue

                marker_map[None].update(_parse_collect_stdout(result.stdout))

        by_nodeid: dict[str, CollectedTestCase] = {}

        for nodeid in sorted(marker_map[None]):
            file_path = _as_file_path(nodeid)
            source_checkpoint = _infer_checkpoint_from_file(
                file_path,
                fallback=checkpoint.name,
            )

            if source_checkpoint != checkpoint.name:
                group_type = GroupType.REGRESSION
            elif nodeid in marker_map["error"]:
                group_type = GroupType.ERROR
            elif nodeid in marker_map["regression"]:
                group_type = GroupType.REGRESSION
            elif nodeid in marker_map["functionality"]:
                group_type = GroupType.FUNCTIONALITY
            else:
                group_type = GroupType.CORE

            by_nodeid[nodeid] = CollectedTestCase(
                nodeid=nodeid,
                test_id=_as_test_id(nodeid),
                file_path=file_path,
                checkpoint=source_checkpoint,
                group_type=group_type,
            )

        grouped_sets: dict[str, set[str]] = {}
        for test_case in by_nodeid.values():
            key = _group_key(test_case.checkpoint, test_case.group_type)
            grouped_sets.setdefault(key, set()).add(test_case.test_id)

        grouped_test_ids = {
            key: sorted(ids) for key, ids in sorted(grouped_sets.items())
        }

        return CheckpointTestCollection(
            tests=[by_nodeid[key] for key in sorted(by_nodeid)],
            by_nodeid=by_nodeid,
            grouped_test_ids=grouped_test_ids,
            total_collected=len(by_nodeid),
            test_collection_hash=compute_tc_hash(grouped_test_ids),
            infrastructure_failure=infrastructure_failure,
        )

    finally:
        session.cleanup()


def _result_nodeid(result: TestResult) -> str:
    if result.file_path and not result.id.startswith(f"{result.file_path}::"):
        return f"{result.file_path}::{result.id}"
    return result.id


def apply_collection_inventory(
    results: CorrectnessResults,
    collection: CheckpointTestCollection,
) -> CorrectnessResults:
    """Apply collected inventory to execution results and backfill misses."""
    existing_by_nodeid = {
        _result_nodeid(result): result for result in results.tests
    }
    merged: list[TestResult] = []
    missing_count = 0

    for collected_test in collection.tests:
        existing = existing_by_nodeid.pop(collected_test.nodeid, None)
        if existing is None:
            missing_count += 1
            merged.append(
                TestResult(
                    id=collected_test.test_id,
                    checkpoint=collected_test.checkpoint,
                    group_type=collected_test.group_type,
                    status="failed",
                    duration_ms=0.0,
                    file_path=collected_test.file_path,
                    markers=[],
                    failure_message=None,
                )
            )
            continue

        existing.checkpoint = collected_test.checkpoint
        existing.group_type = collected_test.group_type
        existing.file_path = collected_test.file_path
        existing.id = collected_test.test_id
        merged.append(existing)

    if existing_by_nodeid:
        merged.extend(existing_by_nodeid.values())

    totals = dict.fromkeys(GroupType, 0)
    passes = dict.fromkeys(GroupType, 0)
    for test in merged:
        totals[test.group_type] += 1
        if test.status == "passed":
            passes[test.group_type] += 1

    results.tests = merged
    results.total_counts = totals
    results.pass_counts = passes
    results.pytest_collected = collection.total_collected
    results.test_collection_hash = collection.test_collection_hash
    if collection.infrastructure_failure or missing_count > 0:
        results.infrastructure_failure = True
    return results


def _has_k_filter(pytest_args: list[str] | None) -> bool:
    if not pytest_args:
        return False
    for idx, arg in enumerate(pytest_args):
        if arg == "-k":
            return idx + 1 < len(pytest_args)
        if arg.startswith("-k") and arg != "-k":
            return True
    return False


def run_checkpoint_with_collection(
    *,
    submission_path: Path,
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    env_spec: EnvironmentSpec,
    pytest_args: list[str] | None = None,
) -> CorrectnessResults:
    """Run checkpoint pytest and apply collection-backed test inventory."""
    from slop_code.evaluation.pytest_runner import PytestRunner

    runner = PytestRunner(
        problem=problem,
        checkpoint=checkpoint,
        environment=env_spec,
        submission_path=submission_path,
    )

    collection: CheckpointTestCollection | None = None
    if not _has_k_filter(pytest_args):
        collection = collect_checkpoint_tc(
            submission_path=submission_path,
            problem=problem,
            checkpoint=checkpoint,
            env_spec=env_spec,
            pytest_args=pytest_args,
        )

    results = runner.run(pytest_args=pytest_args)
    if collection is not None:
        apply_collection_inventory(results, collection)
    return results

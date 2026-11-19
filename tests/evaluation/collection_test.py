from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from slop_code import evaluation
from slop_code.common import WORKSPACE_TEST_DIR
from slop_code.evaluation.collection import CheckpointTestCollection
from slop_code.evaluation.collection import CollectedTestCase
from slop_code.evaluation.collection import _build_collect_cmd
from slop_code.evaluation.collection import apply_collection_inventory
from slop_code.evaluation.collection import compute_tc_hash
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult as EvalTestResult


def test_public_collection_functions_exported() -> None:
    assert callable(evaluation.collect_checkpoint_tc)
    assert callable(evaluation.compute_tc_hash)


def test_collect_cmd_excludes_agent_conftest() -> None:
    """The --collect-only passes must exclude an agent-authored root conftest.py.

    Pytest otherwise loads a conftest.py at the workspace root (an ancestor of
    the eval test dir); if it errors or conflicts, collection aborts (exit 4)
    and the checkpoint scores 0 as an infrastructure failure.
    """
    cmd = _build_collect_cmd(
        problem=cast("ProblemConfig", SimpleNamespace(test_dependencies=[])),
        checkpoint_name="checkpoint_1",
        entrypoint="python main.py",
        marker="functionality",
        pytest_args=None,
    )
    assert f"--confcutdir={WORKSPACE_TEST_DIR}" in cmd


def test_compute_tc_hash_stable_for_reordered_input() -> None:
    hash_a = compute_tc_hash(
        {
            "checkpoint_2-Core": ["test_b", "test_a"],
            "checkpoint_2-Error": ["test_e"],
        }
    )
    hash_b = compute_tc_hash(
        {
            "checkpoint_2-Error": ["test_e"],
            "checkpoint_2-Core": ["test_a", "test_b"],
        }
    )

    assert hash_a == hash_b


def _make_results(checkpoint_name: str = "checkpoint_2") -> CorrectnessResults:
    return CorrectnessResults(
        problem_name="test_problem",
        problem_version=1,
        checkpoint_name=checkpoint_name,
        checkpoint_version=1,
        duration=1.0,
        entrypoint="python main.py",
        pytest_exit_code=0,
        pytest_collected=0,
    )


def _make_collection(
    cases: list[CollectedTestCase],
) -> CheckpointTestCollection:
    grouped: dict[str, list[str]] = {}
    for case in cases:
        key = f"{case.checkpoint}-{case.group_type.value}"
        grouped.setdefault(key, []).append(case.test_id)
    return CheckpointTestCollection(
        tests=cases,
        by_nodeid={case.nodeid: case for case in cases},
        grouped_test_ids=grouped,
        total_collected=len(cases),
        test_collection_hash=compute_tc_hash(grouped),
        infrastructure_failure=False,
    )


def test_apply_collection_inventory_excludes_skipped_from_counts() -> None:
    """Skipped tests stay in results.tests but are excluded from totals/passes."""
    results = _make_results()
    cases = [
        CollectedTestCase(
            nodeid="tests/test_cp2.py::test_core_pass",
            test_id="test_core_pass",
            file_path="tests/test_cp2.py",
            checkpoint="checkpoint_2",
            group_type=GroupType.CORE,
        ),
        CollectedTestCase(
            nodeid="tests/test_cp2.py::test_core_skip",
            test_id="test_core_skip",
            file_path="tests/test_cp2.py",
            checkpoint="checkpoint_2",
            group_type=GroupType.CORE,
        ),
        CollectedTestCase(
            nodeid="tests/test_cp1.py::test_reg_pass",
            test_id="test_reg_pass",
            file_path="tests/test_cp1.py",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
        ),
        CollectedTestCase(
            nodeid="tests/test_cp1.py::test_reg_fail",
            test_id="test_reg_fail",
            file_path="tests/test_cp1.py",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
        ),
        CollectedTestCase(
            nodeid="tests/test_cp1.py::test_reg_error",
            test_id="test_reg_error",
            file_path="tests/test_cp1.py",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
        ),
        CollectedTestCase(
            nodeid="tests/test_cp1.py::test_reg_skip",
            test_id="test_reg_skip",
            file_path="tests/test_cp1.py",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
        ),
    ]
    statuses = {
        "test_core_pass": "passed",
        "test_core_skip": "skipped",
        "test_reg_pass": "passed",
        "test_reg_fail": "failed",
        "test_reg_error": "error",
        "test_reg_skip": "skipped",
    }
    for case in cases:
        results.add_test_result(
            EvalTestResult(
                id=case.test_id,
                checkpoint=case.checkpoint,
                group_type=case.group_type,
                status=statuses[case.test_id],
                duration_ms=1.0,
                file_path=case.file_path,
            )
        )

    expected_totals = dict(results.total_counts)
    expected_passes = dict(results.pass_counts)
    collection = _make_collection(cases)

    apply_collection_inventory(results, collection)

    assert len(results.tests) == len(cases)
    assert results.pytest_collected == len(cases)
    assert results.infrastructure_failure is False
    assert results.total_counts[GroupType.CORE] == 1
    assert results.pass_counts[GroupType.CORE] == 1
    assert results.total_counts[GroupType.REGRESSION] == 3
    assert results.pass_counts[GroupType.REGRESSION] == 1
    assert (
        results.total_counts[GroupType.CORE] == expected_totals[GroupType.CORE]
    )
    assert (
        results.pass_counts[GroupType.CORE] == expected_passes[GroupType.CORE]
    )
    assert (
        results.total_counts[GroupType.REGRESSION]
        == expected_totals[GroupType.REGRESSION]
    )
    assert (
        results.pass_counts[GroupType.REGRESSION]
        == expected_passes[GroupType.REGRESSION]
    )
    assert results.passes_policy("core-cases") is True

    grouped = results.to_output_dict()["tests"]
    assert grouped["checkpoint_2-Core"]["skipped"] == ["test_core_skip"]
    assert grouped["checkpoint_1-Regression"]["skipped"] == ["test_reg_skip"]


def test_apply_collection_inventory_skipped_policy_and_missing_backfill() -> (
    None
):
    """Missing tests still backfill as failed while skipped tests stay excluded."""
    results = _make_results()
    cases = [
        CollectedTestCase(
            nodeid="tests/test_cp1.py::test_reg_pass",
            test_id="test_reg_pass",
            file_path="tests/test_cp1.py",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
        ),
        CollectedTestCase(
            nodeid="tests/test_cp1.py::test_reg_skip",
            test_id="test_reg_skip",
            file_path="tests/test_cp1.py",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
        ),
        CollectedTestCase(
            nodeid="tests/test_cp1.py::test_reg_missing",
            test_id="test_reg_missing",
            file_path="tests/test_cp1.py",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
        ),
    ]
    results.add_test_result(
        EvalTestResult(
            id="test_reg_pass",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
            status="passed",
            duration_ms=1.0,
            file_path="tests/test_cp1.py",
        )
    )
    results.add_test_result(
        EvalTestResult(
            id="test_reg_skip",
            checkpoint="checkpoint_1",
            group_type=GroupType.REGRESSION,
            status="skipped",
            duration_ms=1.0,
            file_path="tests/test_cp1.py",
        )
    )
    # Also include an uncollected skipped test to verify leftovers exclude skips.
    results.add_test_result(
        EvalTestResult(
            id="test_extra_skip",
            checkpoint="checkpoint_2",
            group_type=GroupType.FUNCTIONALITY,
            status="skipped",
            duration_ms=1.0,
            file_path="tests/test_cp2.py",
        )
    )

    apply_collection_inventory(results, _make_collection(cases))

    assert results.infrastructure_failure is True
    assert results.total_counts[GroupType.REGRESSION] == 2
    assert results.pass_counts[GroupType.REGRESSION] == 1
    assert results.total_counts[GroupType.FUNCTIONALITY] == 0
    assert results.pass_counts[GroupType.FUNCTIONALITY] == 0
    assert len(results.tests) == 4

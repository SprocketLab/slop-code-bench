from __future__ import annotations

from types import SimpleNamespace

from slop_code import evaluation
from slop_code.common import WORKSPACE_TEST_DIR
from slop_code.evaluation.collection import _build_collect_cmd
from slop_code.evaluation.collection import compute_tc_hash


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
        problem=SimpleNamespace(test_dependencies=[]),
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

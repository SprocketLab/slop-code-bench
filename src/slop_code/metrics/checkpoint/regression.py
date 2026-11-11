"""Decompose Regression failures by each test's outcomes at earlier checkpoints.

Every checkpoint re-runs all prior checkpoints' tests as ``Regression`` tests,
so a failed Regression test at checkpoint k is one of:

- ``true_regressions``: passed at some earlier checkpoint, fails at k.
- ``carryover_failures``: ran at an earlier checkpoint but never passed (for
  example, an edge case that was missed when its checkpoint was introduced).
- ``newly_active_failures``: never ran before k (skipped or absent).

``true_regression_hazard`` is ``true_regressions`` divided by
``regression_previously_passed``, the number of Regression tests evaluated at k
that passed at some earlier checkpoint.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from collections.abc import Sequence
from pathlib import Path

from slop_code.common import EVALUATION_FILENAME
from slop_code.evaluation import GroupType

# evaluation.json "tests": {"<checkpoint>-<GroupType>": {"passed": [...], ...}}
GroupedTests = Mapping[str, Mapping[str, Sequence[str]]]

REGRESSION_BREAKDOWN_KEYS: tuple[str, ...] = (
    "true_regressions",
    "carryover_failures",
    "newly_active_failures",
    "regression_previously_passed",
)


class RegressionHistory:
    """Per-test outcomes across the checkpoints of one problem run.

    Tests are identified by (originating checkpoint, test id). Call
    ``observe`` once per checkpoint, in checkpoint order.
    """

    def __init__(self) -> None:
        self._passed: set[tuple[str, str]] = set()
        self._failed: set[tuple[str, str]] = set()

    def observe(self, tests: GroupedTests) -> dict[str, int | float]:
        """Return the Regression breakdown for a checkpoint, then record it.

        Args:
            tests: The grouped ``tests`` mapping from evaluation.json.

        Returns:
            Counts for ``REGRESSION_BREAKDOWN_KEYS`` plus
            ``true_regression_hazard`` (0.0 when nothing previously passed).
        """
        counts = dict.fromkeys(REGRESSION_BREAKDOWN_KEYS, 0)
        for key, buckets in tests.items():
            checkpoint, _, group = key.rpartition("-")
            if group != GroupType.REGRESSION.value:
                continue
            for status in ("passed", "failed"):
                for test_id in buckets.get(status, ()):
                    test = (checkpoint, test_id)
                    passed_before = test in self._passed
                    counts["regression_previously_passed"] += passed_before
                    if status == "passed":
                        continue
                    if passed_before:
                        counts["true_regressions"] += 1
                    elif test in self._failed:
                        counts["carryover_failures"] += 1
                    else:
                        counts["newly_active_failures"] += 1

        for key, buckets in tests.items():
            checkpoint = key.rpartition("-")[0]
            self._passed.update(
                (checkpoint, t) for t in buckets.get("passed", ())
            )
            self._failed.update(
                (checkpoint, t) for t in buckets.get("failed", ())
            )

        previously_passed = counts["regression_previously_passed"]
        return {
            **counts,
            "true_regression_hazard": (
                counts["true_regressions"] / previously_passed
                if previously_passed > 0
                else 0.0
            ),
        }

    def observe_dir(
        self, checkpoint_dir: Path, eval_file_name: str = EVALUATION_FILENAME
    ) -> dict[str, int | float]:
        """Observe a checkpoint directory's evaluation.json.

        Returns an empty dict (and records nothing) if the file is missing.
        """
        eval_file = checkpoint_dir / eval_file_name
        if not eval_file.exists():
            return {}
        with eval_file.open("r") as f:
            tests = json.load(f).get("tests", {})
        if not isinstance(tests, Mapping):
            return {}
        return self.observe(tests)

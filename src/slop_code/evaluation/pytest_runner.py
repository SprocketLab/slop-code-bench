"""Pytest-based test execution for SCBench evaluations.

This module replaces the Adapter/Loader/Verifier orchestration with a simple
pytest execution model. Tests run inside Docker containers with no slop-code
dependencies.

Architecture:
1. PytestRunner orchestrates test execution for a checkpoint
2. pytest runs via uvx for isolated execution (no interference with solution)
3. pytest-json-ctrf generates CTRF JSON report
4. CTRF report parsed and converted to TestResult objects
5. Results aggregated into CorrectnessResults

Key Classes:
- PytestRunner: Main orchestrator for pytest execution
- run_checkpoint_pytest: Public API function (replaces old run_checkpoint)

Example:
    >>> from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
    >>> results = run_checkpoint_pytest(
    ...     submission_path=Path("outputs/problem/checkpoint_1"),
    ...     problem=problem_config,
    ...     checkpoint=checkpoint_config,
    ...     env_spec=environment_spec,
    ... )
    >>> print(results.passes_policy("core-cases"))
"""

from __future__ import annotations

import json
import re
import shlex
from collections import Counter
from pathlib import Path
from typing import Any

from slop_code.common import WORKSPACE_TEST_DIR
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution.assets import resolve_static_assets
from slop_code.logging import get_logger

logger = get_logger(__name__)

# Pytest exit codes (from pytest documentation)
# See: https://docs.pytest.org/en/stable/reference/exit-codes.html
EXIT_OK = 0  # All tests passed
EXIT_TESTSFAILED = 1  # Some tests failed
EXIT_INTERRUPTED = 2  # Test execution interrupted
EXIT_INTERNALERROR = 3  # Internal error
EXIT_USAGEERROR = 4  # Pytest usage error
EXIT_NOTESTSCOLLECTED = 5  # No tests collected

# Valid exit codes (tests ran, some may have failed)
VALID_EXIT_CODES = {EXIT_OK, EXIT_TESTSFAILED}

# Infrastructure failure codes (pytest itself failed)
INFRA_FAILURE_CODES = {
    EXIT_INTERRUPTED,
    EXIT_INTERNALERROR,
    EXIT_USAGEERROR,
    EXIT_NOTESTSCOLLECTED,
}

MAX_LOG_OUTPUT = 4000


def _truncate_output(text: str | None, limit: int = MAX_LOG_OUTPUT) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"


class PytestRunner:
    """Orchestrates pytest execution for a checkpoint evaluation.

    This class manages the full lifecycle of running pytest tests for a checkpoint:
    1. Copies tests from problem directory if needed
    2. Generates pytest.ini with markers
    3. Determines which test files to run (current + prior checkpoints)
    4. Builds pytest command with entrypoint and static assets
    5. Executes pytest via uvx (isolated from solution's environment)
    6. Parses CTRF JSON report
    7. Converts test results to TestResult objects
    8. Aggregates into CorrectnessResults

    Note: Tests are executed using `uvx` to ensure complete isolation from
    the solution's Python environment. This allows testing solutions that
    use different package managers (pip, uv) or even non-Python solutions.

    Attributes:
        problem: Problem configuration
        checkpoint: Checkpoint configuration
        environment: Execution environment specification
        submission_path: Path to the submission directory

    Example:
        >>> runner = PytestRunner(
        ...     problem=problem_config,
        ...     checkpoint=checkpoint_config,
        ...     environment=env_spec,
        ...     submission_path=Path("outputs/problem/checkpoint_1"),
        ... )
        >>> results = runner.run()
    """

    def __init__(
        self,
        problem: ProblemConfig,
        checkpoint: CheckpointConfig,
        environment: EnvironmentSpec,
        submission_path: Path,
    ):
        """Initialize pytest runner.

        Args:
            problem: Problem configuration
            checkpoint: Checkpoint configuration to evaluate
            environment: Execution environment specification
            submission_path: Path to submission directory (contains the code to test)
        """
        self.problem = problem
        self.checkpoint = checkpoint
        self.environment = environment
        self.submission_path = submission_path

    def _get_entrypoint_command(self) -> str:
        """Compute the entrypoint command for the submission.

        Uses the environment's get_command() method to format the entry_file
        from the problem config. This is passed to pytest as --entrypoint.

        Returns:
            Full command to run the submission (e.g., "python main.py")

        Example:
            >>> runner._get_entrypoint_command()
            'python main.py'
        """
        return self.environment.get_command(
            self.problem.entry_file,
            is_agent_run=False,  # Evaluation, not agent inference
        )

    def _copy_tests_from_problem(self, workspace_path: Path) -> None:
        """Copy tests from problem directory to workspace if needed.

        If the workspace doesn't have a tests/ directory but the problem does,
        selectively copy test files for checkpoints 0..N (current checkpoint).
        This allows tests to be defined at the problem level while only running
        relevant tests for the current checkpoint.

        Files copied:
        - conftest.py (shared fixtures)
        - test_{checkpoint_name}.py for checkpoints up to current
        - Any non-test files (helpers, utilities, __init__.py)

        Args:
            workspace_path: Path to the workspace root
        """
        import shutil

        workspace_tests = workspace_path / WORKSPACE_TEST_DIR
        problem_tests = self.problem.path / "tests"

        if workspace_tests.exists():
            logger.debug(
                "Workspace already has tests directory",
                workspace_tests=str(workspace_tests),
            )
            return

        if not problem_tests.exists():
            raise RuntimeError(
                f"No tests directory found.\n"
                f"  Checked workspace: {workspace_tests}\n"
                f"  Checked problem: {problem_tests}\n"
                f"Expected tests/ directory with test files in one of these locations."
            )

        # Get test files based on include_prior_tests setting
        checkpoint_files: set[str] = set()
        if self.checkpoint.include_prior_tests:
            # Include all checkpoints 0..N
            for checkpoint_name, _ in self.problem.iterate_checkpoint_items():
                checkpoint_files.add(f"test_{checkpoint_name}.py")
                if checkpoint_name == self.checkpoint.name:
                    break
        else:
            # Only include current checkpoint
            checkpoint_files.add(f"test_{self.checkpoint.name}.py")

        logger.debug(
            "Selectively copying tests from problem directory",
            source=str(problem_tests),
            dest=str(workspace_tests),
            checkpoint_files=list(checkpoint_files),
        )

        # Create tests directory
        workspace_tests.mkdir(parents=True, exist_ok=True)

        # Copy files selectively
        for item in problem_tests.iterdir():
            if item.is_file():
                # Check if this is a checkpoint test file
                is_checkpoint_test = (
                    item.name.startswith("test_")
                    and item.name.endswith(".py")
                    and item.name != "conftest.py"
                )

                if item.name == "conftest.py":
                    # Always copy conftest.py
                    shutil.copy2(item, workspace_tests / item.name)
                    logger.debug(
                        "Copying conftest.py",
                        source=str(item),
                        dest=str(workspace_tests / item.name),
                    )
                elif is_checkpoint_test:
                    # Only copy checkpoint test files for checkpoints 0..N
                    if item.name in checkpoint_files:
                        logger.debug(
                            "Copying checkpoint test file",
                            source=str(item),
                            dest=str(workspace_tests / item.name),
                        )
                        shutil.copy2(item, workspace_tests / item.name)
                else:
                    # Copy non-test files (helpers, __init__.py, etc.)
                    logger.debug(
                        "Copying non-test file",
                        source=str(item),
                        dest=str(workspace_tests / item.name),
                    )
                    shutil.copy2(item, workspace_tests / item.name)
            elif item.is_dir():
                if item.name == "__pycache__":
                    continue
                # Copy subdirectories (e.g., fixtures, data)
                logger.debug(
                    "Copying subdirectory",
                    source=str(item),
                    dest=str(workspace_tests / item.name),
                )
                shutil.copytree(item, workspace_tests / item.name)

    # Built-in markers that are always registered
    # Maps marker name -> (description, GroupType)
    BUILTIN_MARKERS: dict[str, tuple[str, GroupType]] = {
        "error": ("error-handling / edge-case tests", GroupType.ERROR),
        "functionality": (
            "non-core / nice-to-have tests",
            GroupType.FUNCTIONALITY,
        ),
        "regression": (
            "regression tests from prior checkpoints",
            GroupType.REGRESSION,
        ),
    }

    def _generate_pytest_ini(self, workspace_path: Path) -> None:
        """Generate pytest.ini in the workspace root.

        Creates pytest.ini with:
        - testpaths = tests (tells pytest where to find tests)
        - markers = custom markers from problem config + built-in markers

        The markers are read from problem.markers dict
        (e.g., {"functionality": "...", "error": "..."}) plus built-in markers
        (error, functionality, regression).

        Args:
            workspace_path: Path to workspace root

        Example pytest.ini:
            [pytest]
            testpaths = tests
            markers =
                functionality: non-core / nice-to-have tests
                error: error-handling / edge-case tests
                regression: regression tests from prior checkpoints
        """
        # Build markers section from built-in + problem.markers
        markers_lines = []
        # Add built-in markers first (BUILTIN_MARKERS values are (description, GroupType) tuples)
        for marker_name, (marker_desc, _) in self.BUILTIN_MARKERS.items():
            markers_lines.append(f"    {marker_name}: {marker_desc}")
        # Add problem-specific custom markers (MarkerConfig objects)
        for marker_name, marker_config in self.problem.markers.items():
            if marker_name not in self.BUILTIN_MARKERS:
                markers_lines.append(
                    f"    {marker_name}: {marker_config.description}"
                )

        markers_section = "\n".join(markers_lines)

        content = f"""[pytest]
testpaths = tests
markers =
{markers_section}
"""

        pytest_ini_path = workspace_path / "pytest.ini"
        pytest_ini_path.write_text(content)

        logger.debug("Generated pytest.ini", path=str(pytest_ini_path))

    # Test dependencies installed via uvx for isolated execution
    TEST_DEPENDENCIES = [
        "pytest",  # Test framework
        "pytest-json-ctrf",  # CTRF JSON report plugin
        "pytest-json-report",  # Detailed failure reports
        "pytest-timeout",  # Session-level timeout support
        "jsonschema",  # JSON schema validation (for test cases)
        "deepdiff",  # Deep comparison utilities
    ]

    def _build_pytest_command(
        self,
        extra_args: list[str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Build the pytest command to execute.

        Constructs a pytest command that:
        1. Runs via uvx with ephemeral dependencies (uvx --with=... pytest ...)
        2. Discovers tests via pytest.ini testpaths setting
        3. Passes entrypoint as --entrypoint CLI option
        4. Passes checkpoint name as --checkpoint CLI option
        5. Generates CTRF report via --ctrf option
        6. Generates pytest JSON report via --json-report option
        7. Uses verbose output (-vv)
        8. Applies session-level timeout via pytest-timeout if specified

        Static assets are passed via environment variables (SCBENCH_ASSET_{NAME})
        rather than CLI options.

        Using uvx ensures tests run in an isolated environment that doesn't
        interfere with the solution's own pyproject.toml or virtualenv.

        Args:
            extra_args: Additional pytest args to append (e.g., ["-k", "name"])
            timeout: Session-level timeout in seconds (applied via pytest-timeout)

        Returns:
            Full pytest command string (properly shell-quoted)

        Example:
            >>> runner._build_pytest_command()
            'uvx --with=pytest --with=pytest-json-ctrf ... pytest ...'
        """
        entrypoint = self._get_entrypoint_command()

        # Build command parts
        extra_args = extra_args or []
        quoted_extra_args = [shlex.quote(arg) for arg in extra_args]

        # Build uvx --with flags for each dependency (base + problem-specific)
        all_deps = list(self.TEST_DEPENDENCIES) + list(
            self.problem.test_dependencies or []
        )
        with_flags = [f"--with={dep}" for dep in all_deps]

        # Build timeout args if specified
        timeout_args = []
        if timeout is not None:
            timeout_args = [f"--timeout={int(timeout)}"]

        cmd_parts = [
            "uvx",
            *with_flags,
            "pytest",
            *timeout_args,
            f"--entrypoint={shlex.quote(entrypoint)}",
            f"--checkpoint={shlex.quote(self.checkpoint.name)}",
            "--ctrf=.scbench/ctrf-report.json",  # CTRF report output path
            "--json-report",
            "--json-report-file=.scbench/pytest-report.json",
            "--json-report-omit=traceback",
            "--json-report-omit=streams",
            "--json-report-omit=log",
            "--json-report-omit=collectors",
            "--json-report-omit=warnings",
            "-vv",  # Verbose output
            *quoted_extra_args,
            WORKSPACE_TEST_DIR,
        ]

        return " ".join(cmd_parts)

    def _parse_ctrf_report(
        self, ctrf_path: Path
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Parse CTRF JSON report from pytest-json-ctrf plugin.

        CTRF (Common Test Report Format) is a standardized JSON format for test results.
        The pytest-json-ctrf plugin generates this format.

        Expected CTRF structure:
        {
            "results": {
                "tool": {"name": "pytest", ...},
                "summary": {...},
                "tests": [
                    {
                        "name": "test_example",
                        "status": "passed",
                        "duration": 123,
                        "filePath": "tests/test_checkpoint_1.py",
                        "tags": ["functionality"],
                        "message": "..."
                    },
                    ...
                ]
            }
        }

        Args:
            ctrf_path: Path to CTRF JSON file

        Returns:
            Tuple of (tests, report_data)
            - tests: List of test dictionaries from the "tests" array
            - report_data: Full CTRF JSON report (or None if missing/invalid)

        Example:
            >>> tests, report = runner._parse_ctrf_report(
            ...     Path(".scbench/ctrf-report.json")
            ... )
            >>> len(tests)
            10
        """
        if not ctrf_path.exists():
            logger.error("CTRF report not found", path=str(ctrf_path))
            return [], None

        try:
            with ctrf_path.open() as f:
                data = json.load(f)

            # CTRF format: {"results": {"tool": {...}, "tests": [...]}}
            tests = data.get("results", {}).get("tests", [])

            logger.info(
                "Parsed CTRF report", test_count=len(tests), path=str(ctrf_path)
            )
            return tests, data

        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse CTRF report as JSON",
                path=str(ctrf_path),
                error=str(e),
                exc_info=True,
            )
            return [], None
        except Exception as e:
            logger.error(
                "Unexpected error parsing CTRF report",
                path=str(ctrf_path),
                error=str(e),
                exc_info=True,
            )
            return [], None

    def _infer_checkpoint_from_file(self, file_path: str) -> str:
        """Extract checkpoint name from test file path.

        Test files follow the naming convention: tests/test_{checkpoint_name}.py

        Args:
            file_path: Test file path (e.g., "tests/test_checkpoint_1.py")

        Returns:
            Checkpoint name (e.g., "checkpoint_1")

        Example:
            >>> runner._infer_checkpoint_from_file("tests/test_checkpoint_2.py")
            'checkpoint_2'
        """
        # Pattern: test_{checkpoint_name}.py
        match = re.search(r"test_([^/]+)\.py", file_path)

        if match:
            return match.group(1)

        # Fallback to current checkpoint if pattern doesn't match
        logger.warning(
            "Could not infer checkpoint from file path, using current checkpoint",
            file_path=file_path,
            fallback=self.checkpoint.name,
        )
        return self.checkpoint.name

    def _determine_group_type(
        self,
        test_checkpoint: str,
        markers: list[str],
        current_checkpoint: str,
    ) -> GroupType:
        """Determine GroupType based on checkpoint and markers.

        This is the CORE CATEGORIZATION LOGIC that replaces the old Adapter/Loader/Verifier
        group determination.

        Rules (in priority order):
        1. If test is from prior checkpoint -> REGRESSION (regardless of markers)
        2. If "error" marker present -> ERROR (current checkpoint only)
        3. If "regression" marker present -> REGRESSION
        4. Check custom markers from problem config -> return their configured GroupType
        5. If test is from current checkpoint:
           - If "functionality" marker -> FUNCTIONALITY
           - If no marker -> CORE

        Args:
            test_checkpoint: Checkpoint this test belongs to (inferred from file path)
            markers: Pytest markers on this test (e.g., ["functionality", "slow"])
            current_checkpoint: The checkpoint being evaluated

        Returns:
            GroupType for this test

        Example:
            >>> # Unmarked test in current checkpoint
            >>> runner._determine_group_type("checkpoint_1", [], "checkpoint_1")
            GroupType.CORE

            >>> # Functionality test in current checkpoint
            >>> runner._determine_group_type("checkpoint_1", ["functionality"], "checkpoint_1")
            GroupType.FUNCTIONALITY

            >>> # Test from prior checkpoint (regression)
            >>> runner._determine_group_type("checkpoint_1", [], "checkpoint_2")
            GroupType.REGRESSION

            >>> # Explicit regression marker in current checkpoint
            >>> runner._determine_group_type("checkpoint_2", ["regression"], "checkpoint_2")
            GroupType.REGRESSION

            >>> # Error test in current checkpoint
            >>> runner._determine_group_type("checkpoint_1", ["error"], "checkpoint_1")
            GroupType.ERROR

            >>> # Error test in prior checkpoint (now REGRESSION, not ERROR)
            >>> runner._determine_group_type("checkpoint_1", ["error"], "checkpoint_2")
            GroupType.REGRESSION
        """
        is_current = test_checkpoint == current_checkpoint

        # RULE 1: Prior checkpoint tests ALWAYS become regression (regardless of markers)
        if not is_current:
            return GroupType.REGRESSION

        # RULE 2: Error marker for current checkpoint
        if "error" in markers:
            return GroupType.ERROR

        # RULE 3: Explicit regression marker
        if "regression" in markers:
            return GroupType.REGRESSION

        # RULE 4: Check custom markers from problem config
        for marker in markers:
            if marker in self.problem.markers:
                return self.problem.markers[marker].group

        # RULE 5: Current checkpoint tests
        # If has functionality marker -> FUNCTIONALITY
        # Otherwise -> CORE
        if "functionality" in markers:
            return GroupType.FUNCTIONALITY

        return GroupType.CORE

    def _parse_pytest_json_report(
        self, report_path: Path
    ) -> dict[str, Any] | None:
        """Parse pytest-json-report output if available."""
        if not report_path.exists():
            logger.debug("Pytest JSON report not found", path=str(report_path))
            return None

        try:
            with report_path.open() as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse pytest JSON report as JSON",
                path=str(report_path),
                error=str(e),
                exc_info=True,
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error parsing pytest JSON report",
                path=str(report_path),
                error=str(e),
                exc_info=True,
            )
            return None

    def _stringify_failure_detail(self, value: Any) -> str:
        if isinstance(value, str):
            return value

        if isinstance(value, dict):
            repr_crash = value.get("reprcrash")
            if isinstance(repr_crash, dict):
                message = repr_crash.get("message")
                path = repr_crash.get("path")
                lineno = repr_crash.get("lineno")
                parts = []
                if path and lineno is not None:
                    parts.append(f"{path}:{lineno}")
                if message:
                    parts.append(str(message))
                if parts:
                    return "\n".join(parts)

        return json.dumps(value, indent=2, ensure_ascii=True)

    def _extract_failure_message(
        self, report_test: dict[str, Any]
    ) -> str | None:
        for phase in ["call", "setup", "teardown"]:
            phase_data = report_test.get(phase) or {}
            if phase_data.get("outcome") not in {"failed", "error"}:
                continue
            for key in ["longreprtext", "longrepr", "crash", "message"]:
                value = phase_data.get(key)
                if value:
                    return self._stringify_failure_detail(value)
        return None

    def _build_failure_index(
        self, report_data: dict[str, Any]
    ) -> dict[str, str]:
        tests = report_data.get("tests", [])
        if not isinstance(tests, list):
            return {}

        failure_index: dict[str, str] = {}
        for test_entry in tests:
            if not isinstance(test_entry, dict):
                continue
            node_id = test_entry.get("nodeid")
            if not node_id:
                continue
            message = self._extract_failure_message(test_entry)
            if message:
                failure_index[node_id] = message
        return failure_index

    def _lookup_failure_message(
        self,
        test_data: dict[str, Any],
        failure_index: dict[str, str],
    ) -> str | None:
        name = test_data.get("name") or ""
        file_path = test_data.get("filePath") or ""
        candidates = [name]
        if file_path and name and "::" not in name:
            candidates.append(f"{file_path}::{name}")

        for candidate in candidates:
            if candidate in failure_index:
                return failure_index[candidate]

        if not name:
            return None

        suffix = f"::{name}"
        matches = []
        for node_id, message in failure_index.items():
            if file_path and not node_id.startswith(f"{file_path}::"):
                continue
            if node_id.endswith(suffix):
                matches.append(message)

        if len(matches) == 1:
            return matches[0]
        return None

    def _merge_failure_messages(
        self, existing: str | None, message: str
    ) -> str:
        if not existing:
            return message
        if message in existing:
            return existing
        if existing in message:
            return message
        return f"{existing}\n\n{message}"

    def _augment_ctrf_with_failures(
        self,
        ctrf_tests: list[dict[str, Any]],
        failure_index: dict[str, str],
    ) -> None:
        if not failure_index:
            return

        updated = 0
        for test_data in ctrf_tests:
            if test_data.get("status") not in {"failed", "error"}:
                continue
            message = self._lookup_failure_message(test_data, failure_index)
            if not message:
                continue
            test_data["message"] = self._merge_failure_messages(
                test_data.get("message"), message
            )
            updated += 1

        if updated:
            logger.debug("Augmented CTRF failures", count=updated)

    def _convert_ctrf_test_to_result(
        self, test_data: dict[str, Any]
    ) -> TestResult:
        """Convert a CTRF test result to a TestResult model.

        CTRF test schema (relevant fields):
        - name: Test name/nodeid (str)
        - status: "passed" | "failed" | "skipped" | "error" (str)
        - duration: Execution time in milliseconds (int)
        - filePath: File path (str)
        - tags: Markers/tags (list[str], optional)
        - message: Failure message (str, optional)

        Args:
            test_data: CTRF test object from the "tests" array

        Returns:
            TestResult model instance

        Example:
            >>> ctrf_test = {
            ...     "name": "test_example",
            ...     "status": "passed",
            ...     "duration": 123,
            ...     "filePath": "tests/test_checkpoint_1.py",
            ... }
            >>> result = runner._convert_ctrf_test_to_result(ctrf_test)
            >>> result.status
            'passed'
        """
        # Extract file path from filePath or infer from test name (nodeid)
        # CTRF filePath may be empty, but the name field contains the nodeid
        # which has the format: path/to/test_file.py::TestClass::test_method
        file_path = test_data.get("filePath", "")
        if not file_path:
            name = test_data.get("name", "")
            if "::" in name:
                # Extract file path from nodeid (everything before first ::)
                file_path = name.split("::")[0]

        test_checkpoint = self._infer_checkpoint_from_file(file_path)

        # Extract markers (CTRF uses "tags" field)
        # pytest-json-ctrf plugin should populate this with markers
        markers = test_data.get("tags", []) or []

        # Determine group type using categorization logic
        group_type = self._determine_group_type(
            test_checkpoint=test_checkpoint,
            markers=markers,
            current_checkpoint=self.checkpoint.name,
        )

        # Create TestResult
        return TestResult(
            id=test_data.get("name", "unknown"),
            checkpoint=test_checkpoint,
            group_type=group_type,
            status=test_data.get(
                "status", "error"
            ),  # Default to "error" if missing
            duration_ms=test_data.get("duration", 0),
            file_path=file_path,
            markers=markers,
            failure_message=test_data.get(
                "message"
            ),  # Optional failure message
        )

    def _convert_pytest_report_test_to_result(
        self, test_data: dict[str, Any]
    ) -> TestResult:
        """Convert a pytest-json-report test entry to a TestResult model.

        pytest-json-report expands parametrized tests into individual entries,
        unlike CTRF which collapses them. This method handles the pytest-json-report
        format which includes:
        - nodeid: Full test ID like "tests/test_file.py::test_func[param]"
        - outcome: "passed" | "failed" | "skipped" | "error"
        - duration: Execution time in seconds (float)
        - keywords: List of markers/keywords
        - call/setup/teardown: Phase data with failure details

        Args:
            test_data: pytest-json-report test object from the "tests" array

        Returns:
            TestResult model instance
        """
        nodeid = test_data.get("nodeid", "")

        # Extract file path from nodeid (everything before first ::)
        file_path = ""
        if "::" in nodeid:
            file_path = nodeid.split("::")[0]

        test_checkpoint = self._infer_checkpoint_from_file(file_path)

        # Extract markers from keywords
        # pytest-json-report stores markers in the keywords list
        keywords = test_data.get("keywords", []) or []
        # Filter to only include our known markers (built-in + problem-defined custom)
        known_markers = set(self.BUILTIN_MARKERS.keys())
        known_markers.update(self.problem.markers.keys())
        markers = [kw for kw in keywords if kw in known_markers]

        # Determine group type using categorization logic
        group_type = self._determine_group_type(
            test_checkpoint=test_checkpoint,
            markers=markers,
            current_checkpoint=self.checkpoint.name,
        )

        # Map pytest outcome to our status format
        outcome = test_data.get("outcome", "error")
        # pytest uses "passed", "failed", "skipped", "error", "xfailed", "xpassed"
        status_map = {
            "passed": "passed",
            "failed": "failed",
            "skipped": "skipped",
            "error": "error",
            "xfailed": "skipped",  # Expected failure = skip
            "xpassed": "passed",  # Unexpected pass = pass
        }
        status = status_map.get(outcome, "error")

        # Extract failure message from call phase
        failure_message = self._extract_failure_message(test_data)

        # Duration is stored inside phase objects (setup, call, teardown), sum them
        duration_seconds = 0.0
        for phase in ["setup", "call", "teardown"]:
            phase_data = test_data.get(phase) or {}
            if isinstance(phase_data, dict):
                duration_seconds += phase_data.get("duration", 0) or 0
        duration_ms = duration_seconds * 1000

        # Extract simple test ID from nodeid (remove file path prefix)
        # "tests/test_file.py::TestClass::test_func[param]" -> "TestClass::test_func[param]"
        test_id = nodeid.split("::", 1)[-1] if "::" in nodeid else nodeid

        return TestResult(
            id=test_id,
            checkpoint=test_checkpoint,
            group_type=group_type,
            status=status,
            duration_ms=duration_ms,
            file_path=file_path,
            markers=markers,
            failure_message=failure_message,
        )

    def _parse_pytest_report_tests(
        self, report_data: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Extract test entries from pytest-json-report.

        Args:
            report_data: Parsed pytest-json-report JSON

        Returns:
            List of test entry dictionaries
        """
        if not report_data:
            return []

        tests = report_data.get("tests", [])
        if not isinstance(tests, list):
            return []

        return tests

    def _check_collection_line(self, stdout: str) -> tuple[bool, int]:
        """Parse pytest stdout for collection line.

        Pytest outputs a line like "collected 10 items" when it successfully
        collects tests. This line indicates pytest found and loaded tests.

        Args:
            stdout: Pytest stdout output

        Returns:
            Tuple of (success: bool, num_collected: int)
            - success: True if collection line found and num_collected > 0
            - num_collected: Number of tests collected (0 if not found)

        Example:
            >>> stdout = "collected 5 items\\n\\ntest_example.py::test_1 PASSED"
            >>> success, count = runner._check_collection_line(stdout)
            >>> success, count
            (True, 5)

            >>> stdout = "ERROR: No tests found"
            >>> success, count = runner._check_collection_line(stdout)
            >>> success, count
            (False, 0)
        """
        # Pattern: "collected <number> items" or "collected <number> item"
        match = re.search(r"collected (\d+) items?", stdout)

        if not match:
            logger.warning("Collection line not found in pytest stdout")
            return False, 0

        num_collected = int(match.group(1))

        if num_collected == 0:
            logger.warning("Pytest collected 0 tests")
            return False, 0

        logger.debug(
            "Pytest collection successful", num_collected=num_collected
        )
        return True, num_collected

    def run(
        self,
        pytest_args: list[str] | None = None,
    ) -> CorrectnessResults:
        """Execute pytest for this checkpoint and return results.

        This is the main orchestration method that:
        1. Creates workspace and session
        2. Copies tests from problem directory (only checkpoints 0..N)
        3. Materializes static assets into tests/assets/
        4. Generates pytest.ini
        5. Builds and executes pytest command (via uvx for isolation)
        6. Parses CTRF + pytest JSON reports
        7. Detects infrastructure failures
        8. Converts CTRF tests to TestResults
        9. Returns CorrectnessResults

        Args:
            pytest_args: Extra pytest args (e.g., ["-k", "pattern"])

        Returns:
            CorrectnessResults with test outcomes and metadata

        Raises:
            RuntimeError: If critical setup steps fail

        Example:
            >>> runner = PytestRunner(...)
            >>> results = runner.run()
            >>> results.passes_policy("core-cases")
            True
        """
        logger.info(
            "Starting pytest evaluation",
            problem=self.problem.name,
            checkpoint=self.checkpoint.name,
            environment=self.environment.type,
            submission_path=str(self.submission_path),
        )

        # Resolve static assets (needed for mounts + pytest args)
        resolved_assets = resolve_static_assets(
            base_path=self.problem.path,
            assets=self.problem.static_assets,
        )

        # Create session using factory method (handles snapshot properly)
        session = Session.from_environment_spec(
            spec=self.environment,
            base_dir=self.submission_path,
            static_assets=resolved_assets,
            is_agent_infer=False,
        )

        try:
            # Prepare workspace and session
            session.prepare()
            workspace_path = session.workspace.working_dir
            logger.debug("Workspace prepared", path=str(workspace_path))

            # STEP 1: Copy tests from problem directory if needed
            logger.debug("Copying tests from problem directory if needed")
            self._copy_tests_from_problem(workspace_path)

            # STEP 2: Materialize static assets into tests/assets/
            materialized_assets = (
                session.workspace.materialize_static_assets_for_tests()
            )

            # Build environment variables for static assets
            # Use relative paths so they work inside Docker container
            asset_env_vars: dict[str, str] = {}
            if materialized_assets:
                assets_dir = Path(WORKSPACE_TEST_DIR, "assets")
                asset_env_vars["SCBENCH_ASSETS_DIR"] = str(assets_dir)
                for name in materialized_assets:
                    env_key = f"SCBENCH_ASSET_{name.upper()}"
                    # Use relative path (works in container where cwd is /workspace)
                    asset_env_vars[env_key] = str(assets_dir / name)
                logger.info(
                    "Static assets materialized",
                    asset_count=len(materialized_assets),
                    assets=list(materialized_assets.keys()),
                )
                logger.debug(
                    "Static asset env vars",
                    env_vars=asset_env_vars,
                    verbose=True,
                )

            # STEP 3: Generate pytest.ini with markers
            logger.debug("Generating pytest.ini")
            self._generate_pytest_ini(workspace_path)

            # STEP 4: Build pytest command
            pytest_cmd = self._build_pytest_command(
                pytest_args,
                timeout=self.checkpoint.timeout,
            )
            logger.debug("Pytest command", command=pytest_cmd)

            # STEP 5: Execute pytest (single-shot mode - no persistent container)
            logger.info("Executing pytest")
            full_env = {
                **self.environment.get_full_env(self.checkpoint.env),
                **asset_env_vars,
            }
            runtime = session.exec(command=pytest_cmd)
            try:
                exec_result = runtime.execute(
                    full_env,
                    None,  # stdin
                    None,  # timeout handled by pytest-timeout
                )
            finally:
                runtime.cleanup()

            logger.info(
                "Pytest execution complete",
                exit_code=exec_result.exit_code,
                duration=exec_result.elapsed,
            )
            if exec_result.exit_code != EXIT_OK:
                logger.debug(
                    "Pytest execution reported failure",
                    exit_code=exec_result.exit_code,
                    stdout=_truncate_output(exec_result.stdout),
                    stderr=_truncate_output(exec_result.stderr),
                )
            else:
                logger.debug(
                    "Pytest stdout/stderr",
                    stdout=_truncate_output(exec_result.stdout),
                    stderr=_truncate_output(exec_result.stderr),
                    verbose=True,
                )

            # STEP 6: Parse test reports
            # We prefer pytest-json-report as primary source because it expands
            # parametrized tests into individual entries. CTRF collapses them.
            pytest_report_path = (
                workspace_path / ".scbench" / "pytest-report.json"
            )
            pytest_report = self._parse_pytest_json_report(pytest_report_path)
            pytest_report_tests = self._parse_pytest_report_tests(pytest_report)

            # Also parse CTRF for backwards compatibility and as fallback
            ctrf_path = workspace_path / ".scbench" / "ctrf-report.json"
            ctrf_tests, ctrf_report = self._parse_ctrf_report(ctrf_path)

            # Determine which source to use for test results
            use_pytest_report = len(pytest_report_tests) > 0
            if use_pytest_report:
                logger.debug(
                    "Using pytest-json-report as primary test source",
                    num_tests=len(pytest_report_tests),
                )
            elif ctrf_tests:
                logger.debug(
                    "Falling back to CTRF report",
                    num_tests=len(ctrf_tests),
                )

            # STEP 7: Check for infrastructure failures
            collection_ok, num_collected = self._check_collection_line(
                exec_result.stdout
            )

            infrastructure_failure = (
                exec_result.exit_code in INFRA_FAILURE_CODES
                or not collection_ok
            )

            if infrastructure_failure:
                logger.error(
                    "Pytest infrastructure failure detected",
                    exit_code=exec_result.exit_code,
                    collected=num_collected,
                    exit_code_meaning=(
                        "EXIT_NOTESTSCOLLECTED"
                        if exec_result.exit_code == 5
                        else "EXIT_INTERRUPTED"
                        if exec_result.exit_code == 2
                        else "EXIT_INTERNALERROR"
                        if exec_result.exit_code == 3
                        else "EXIT_USAGEERROR"
                        if exec_result.exit_code == 4
                        else "UNKNOWN"
                    ),
                )

            # STEP 8: Build CorrectnessResults
            results = CorrectnessResults(
                problem_name=self.problem.name,
                problem_version=self.problem.version,
                checkpoint_name=self.checkpoint.name,
                checkpoint_version=self.checkpoint.version,
                duration=exec_result.elapsed,
                entrypoint=self._get_entrypoint_command(),
                pytest_exit_code=exec_result.exit_code,
                pytest_collected=num_collected,
                infrastructure_failure=infrastructure_failure,
                stdout=exec_result.stdout,
                stderr=exec_result.stderr,
                pytest_ctrf_report=ctrf_report,
                pytest_json_report=pytest_report,
            )

            # STEP 9: Convert test entries to TestResults
            # Use pytest-json-report if available (expands parametrized tests),
            # otherwise fall back to CTRF (collapses parametrized tests)
            if use_pytest_report:
                for test_data in pytest_report_tests:
                    test_result = self._convert_pytest_report_test_to_result(
                        test_data
                    )
                    results.add_test_result(test_result)
            else:
                for test_data in ctrf_tests:
                    test_result = self._convert_ctrf_test_to_result(test_data)
                    results.add_test_result(test_result)

            status_counts = Counter(
                test_result.status for test_result in results.tests
            )
            logger.info(
                "Pytest evaluation complete",
                problem=self.problem.name,
                checkpoint=self.checkpoint.name,
                infrastructure_failure=infrastructure_failure,
                status_counts=dict(status_counts),
            )

            return results

        finally:
            # Always cleanup session (close Docker containers, etc.)
            session.cleanup()


def run_checkpoint_pytest(
    submission_path: Path,
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    env_spec: EnvironmentSpec,
    pytest_args: list[str] | None = None,
) -> CorrectnessResults:
    """Run pytest evaluation for a checkpoint.

    This is the main entry point that replaces the old run_checkpoint() function
    from evaluation.runner. It creates a PytestRunner and executes tests.

    Test files are automatically determined based on the checkpoint being evaluated.
    Only test files for checkpoints 0..N (current) are copied and run.

    Args:
        submission_path: Path to the submission directory (contains code to test)
        problem: Problem configuration
        checkpoint: Checkpoint configuration to evaluate
        env_spec: Execution environment specification
        pytest_args: Extra pytest args (e.g., ["-k", "pattern"])

    Returns:
        CorrectnessResults with test outcomes and aggregated statistics

    Example:
        >>> from slop_code.evaluation.pytest_runner import run_checkpoint_pytest
        >>> from slop_code.evaluation import ProblemConfig
        >>> from slop_code.execution import DockerEnvironmentSpec
        >>>
        >>> problem = ProblemConfig.from_yaml(Path("problems/example"))
        >>> checkpoint = problem.checkpoints["checkpoint_1"]
        >>> env = DockerEnvironmentSpec(...)
        >>>
        >>> results = run_checkpoint_pytest(
        ...     submission_path=Path("outputs/problem/checkpoint_1"),
        ...     problem=problem,
        ...     checkpoint=checkpoint,
        ...     env_spec=env,
        ... )
        >>>
        >>> print(f"Passed: {results.passes_policy('core-cases')}")
    """
    runner = PytestRunner(
        problem=problem,
        checkpoint=checkpoint,
        environment=env_spec,
        submission_path=submission_path,
    )
    return runner.run(pytest_args=pytest_args)

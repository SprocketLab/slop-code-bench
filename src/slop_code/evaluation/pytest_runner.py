"""Pytest-based test execution for SCBench evaluations.

This module replaces the Adapter/Loader/Verifier orchestration with a simple
pytest execution model. Tests run inside Docker containers with no slop-code
dependencies.

Architecture:
1. PytestRunner orchestrates test execution for a checkpoint
2. uv initializes test environment inside Docker
3. pytest runs with CTRF JSON reporter plugin
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
from pathlib import Path
from typing import Any

from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.report import GroupType
from slop_code.evaluation.report import TestResult
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import Snapshot
from slop_code.execution import Workspace
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


class PytestRunner:
    """Orchestrates pytest execution for a checkpoint evaluation.

    This class manages the full lifecycle of running pytest tests for a checkpoint:
    1. Sets up test environment (uv init, install deps)
    2. Generates pytest.ini with markers
    3. Determines which test files to run (current + prior checkpoints)
    4. Builds pytest command with entrypoint and static assets
    5. Executes pytest in Docker
    6. Parses CTRF JSON report
    7. Converts test results to TestResult objects
    8. Aggregates into CorrectnessResults

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

    def _get_test_files_for_checkpoint(self) -> list[str]:
        """Get list of test files to run for this checkpoint.

        Returns test files for ALL checkpoints up to and including the current one.
        This ensures regression testing: running checkpoint_2 also tests checkpoint_1.

        The order matters:
        - Tests from checkpoint_1 run first
        - Tests from checkpoint_2 run second
        - etc.

        Returns:
            List of test file paths relative to workspace
            (e.g., ["tests/test_checkpoint_1.py", "tests/test_checkpoint_2.py"])

        Example:
            >>> # Evaluating checkpoint_2
            >>> runner._get_test_files_for_checkpoint()
            ['tests/test_checkpoint_1.py', 'tests/test_checkpoint_2.py']
        """
        test_files = []

        # Iterate checkpoints in order
        for checkpoint_name, _ in self.problem.iterate_checkpoint_items():
            test_file = f"tests/test_{checkpoint_name}.py"
            test_files.append(test_file)

            # Stop after current checkpoint
            if checkpoint_name == self.checkpoint.name:
                break

        logger.debug(
            "Determined test files for checkpoint",
            checkpoint=self.checkpoint.name,
            test_files=test_files,
        )

        return test_files

    def _setup_test_environment(
        self, workspace_path: Path, session: Session
    ) -> None:
        """Initialize test environment with uv inside Docker.

        Sets up the tests/ directory as a uv project and installs default dependencies.
        Respects any additional dependencies in tests/pyproject.toml if it exists.

        Steps:
        1. Check if tests/pyproject.toml exists
        2. If not, run `uv init --no-readme` in tests/
        3. Add default dependencies: pytest, pytest-json-ctrf, jsonschema, deepdiff
        4. Any additional deps in pyproject.toml are preserved

        Args:
            workspace_path: Path to the workspace root
            session: Session instance for spawning runtimes

        Raises:
            RuntimeError: If uv commands fail
        """
        tests_dir = workspace_path / "tests"

        if not tests_dir.exists():
            raise RuntimeError(
                f"Tests directory not found: {tests_dir}\n"
                f"Expected problem to have tests/ directory with test files"
            )

        # Initialize uv project if pyproject.toml doesn't exist
        pyproject_file = tests_dir / "pyproject.toml"
        if not pyproject_file.exists():
            logger.debug("Initializing uv project in tests/")
            runtime = session.spawn()
            try:
                result = runtime.execute(
                    "cd tests && uv init --no-readme",
                    env={},
                    stdin=None,
                    timeout=60,
                )
                if result.exit_code != 0:
                    raise RuntimeError(
                        f"uv init failed with exit code {result.exit_code}\n"
                        f"stdout: {result.stdout}\n"
                        f"stderr: {result.stderr}"
                    )
            finally:
                runtime.cleanup()

        # Add default test dependencies
        # These are the core deps needed for pytest-based evaluation
        default_deps = [
            "pytest",  # Test framework
            "pytest-json-ctrf",  # CTRF JSON report plugin
            "jsonschema",  # JSON schema validation (for test cases)
            "deepdiff",  # Deep comparison utilities
        ]

        logger.debug("Adding default test dependencies", deps=default_deps)
        runtime = session.spawn()
        try:
            deps_str = " ".join(default_deps)
            result = runtime.execute(
                f"cd tests && uv add {deps_str}",
                env={},
                stdin=None,
                timeout=120,
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"uv add failed with exit code {result.exit_code}\n"
                    f"stdout: {result.stdout}\n"
                    f"stderr: {result.stderr}"
                )
        finally:
            runtime.cleanup()

        logger.info("Test environment setup complete", tests_dir=str(tests_dir))

    def _generate_pytest_ini(self, workspace_path: Path) -> None:
        """Generate pytest.ini in the workspace root.

        Creates pytest.ini with:
        - testpaths = tests (tells pytest where to find tests)
        - markers = custom markers from problem config

        The markers are read from problem.markers dict
        (e.g., {"functionality": "...", "error": "..."}).

        Args:
            workspace_path: Path to workspace root

        Example pytest.ini:
            [pytest]
            testpaths = tests
            markers =
                functionality: non-core / nice-to-have tests
                error: error-handling / edge-case tests
        """
        # Build markers section from problem.markers
        markers_lines = []
        for marker_name, marker_desc in self.problem.markers.items():
            markers_lines.append(f"    {marker_name}: {marker_desc}")

        markers_section = "\n".join(markers_lines)

        content = f"""[pytest]
testpaths = tests
markers =
{markers_section}
"""

        pytest_ini_path = workspace_path / "pytest.ini"
        pytest_ini_path.write_text(content)

        logger.debug("Generated pytest.ini", path=str(pytest_ini_path))

    def _build_pytest_command(
        self,
        test_files: list[str],
        static_assets: dict[str, str],
    ) -> str:
        """Build the pytest command to execute.

        Constructs a pytest command that:
        1. Runs via uv (uv run pytest ...)
        2. Runs specific test files (tests/test_checkpoint_1.py ...)
        3. Passes entrypoint as --entrypoint CLI option
        4. Passes checkpoint name as --checkpoint CLI option
        5. Passes static assets as JSON via --static-assets CLI option
        6. Generates CTRF report via --ctrf option
        7. Uses verbose output (-v)

        Args:
            test_files: List of test file paths to run
            static_assets: Dict of asset name -> resolved path

        Returns:
            Full pytest command string (properly shell-quoted)

        Example:
            >>> runner._build_pytest_command(
            ...     ["tests/test_checkpoint_1.py"],
            ...     {"sde_dir": "/workspace/sde"}
            ... )
            'uv run pytest tests/test_checkpoint_1.py --entrypoint="python main.py" ...'
        """
        entrypoint = self._get_entrypoint_command()

        # Serialize static assets to JSON
        assets_json = json.dumps(static_assets)

        # Build command parts
        cmd_parts = [
            "uv",
            "run",
            "pytest",
            *test_files,  # Expand test file list
            f"--entrypoint={shlex.quote(entrypoint)}",
            f"--checkpoint={shlex.quote(self.checkpoint.name)}",
            f"--static-assets={shlex.quote(assets_json)}",
            "--ctrf=.scbench/ctrf-report.json",  # CTRF report output path
            "-v",  # Verbose output
        ]

        return " ".join(cmd_parts)

    def _parse_ctrf_report(self, ctrf_path: Path) -> list[dict[str, Any]]:
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
            List of test dictionaries from the "tests" array

        Example:
            >>> tests = runner._parse_ctrf_report(Path(".scbench/ctrf-report.json"))
            >>> len(tests)
            10
        """
        if not ctrf_path.exists():
            logger.error("CTRF report not found", path=str(ctrf_path))
            return []

        try:
            with ctrf_path.open() as f:
                data = json.load(f)

            # CTRF format: {"results": {"tool": {...}, "tests": [...]}}
            tests = data.get("results", {}).get("tests", [])

            logger.info(
                "Parsed CTRF report", test_count=len(tests), path=str(ctrf_path)
            )
            return tests

        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse CTRF report as JSON",
                path=str(ctrf_path),
                error=str(e),
                exc_info=True,
            )
            return []
        except Exception as e:
            logger.error(
                "Unexpected error parsing CTRF report",
                path=str(ctrf_path),
                error=str(e),
                exc_info=True,
            )
            return []

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
        1. If "error" marker present -> ERROR (always, regardless of checkpoint)
        2. If test is from prior checkpoint (not current):
           -> REGRESSION (tests from earlier checkpoints prevent regressions)
        3. If test is from current checkpoint:
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

            >>> # Error test in current checkpoint
            >>> runner._determine_group_type("checkpoint_1", ["error"], "checkpoint_1")
            GroupType.ERROR

            >>> # Error test in prior checkpoint (still ERROR)
            >>> runner._determine_group_type("checkpoint_1", ["error"], "checkpoint_2")
            GroupType.ERROR
        """
        is_current = test_checkpoint == current_checkpoint

        # RULE 1: Error marker always wins (highest priority)
        if "error" in markers:
            return GroupType.ERROR

        # RULE 2: Prior checkpoint tests become regressions (except errors, handled above)
        if not is_current:
            return GroupType.REGRESSION

        # RULE 3: Current checkpoint tests
        # If has functionality marker -> FUNCTIONALITY
        # Otherwise -> CORE
        if "functionality" in markers:
            return GroupType.FUNCTIONALITY

        return GroupType.CORE

    def _convert_ctrf_test_to_result(self, test_data: dict[str, Any]) -> TestResult:
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
        # Extract file path and infer checkpoint
        file_path = test_data.get("filePath", "")
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
            status=test_data.get("status", "error"),  # Default to "error" if missing
            duration_ms=test_data.get("duration", 0),
            file_path=file_path,
            markers=markers,
            failure_message=test_data.get("message"),  # Optional failure message
        )

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

        logger.debug("Pytest collection successful", num_collected=num_collected)
        return True, num_collected

    def run(self) -> CorrectnessResults:
        """Execute pytest for this checkpoint and return results.

        This is the main orchestration method that:
        1. Creates workspace and session
        2. Sets up test environment (uv)
        3. Generates pytest.ini
        4. Determines test files to run
        5. Resolves static assets
        6. Builds and executes pytest command
        7. Parses CTRF report
        8. Detects infrastructure failures
        9. Converts CTRF tests to TestResults
        10. Returns CorrectnessResults

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
        )

        # Create snapshot from submission path
        snapshot = Snapshot.from_directory(
            self.submission_path,
            env={},
            keep_globs={"**/*"},
        )

        # Create workspace with snapshot
        workspace = Workspace(
            initial_snapshot=snapshot,
            snapshot_fn=lambda p: Snapshot.from_directory(p, env={}),
            is_agent_infer=False,
        )

        # Resolve static assets (needed for mounts + pytest args)
        resolved_assets = resolve_static_assets(
            base_path=self.problem.path,
            assets=self.problem.static_assets,
        )

        # Create session for execution
        session = Session(
            spec=self.environment,
            workspace=workspace,
            static_assets=resolved_assets,
            is_agent_infer=False,
        )

        try:
            # Prepare workspace and session
            session.prepare()
            workspace_path = workspace.working_dir

            # STEP 1: Setup test environment (uv init + uv add deps)
            logger.debug("Setting up test environment")
            self._setup_test_environment(workspace_path, session)

            # STEP 2: Generate pytest.ini with markers
            logger.debug("Generating pytest.ini")
            self._generate_pytest_ini(workspace_path)

            # STEP 3: Determine which test files to run
            test_files = self._get_test_files_for_checkpoint()
            logger.info("Running test files", files=test_files)

            # Convert to dict of name -> string path
            if self.environment.type == "docker":
                static_assets_dict = {
                    name: (Path("/static") / asset.save_path).as_posix()
                    for name, asset in resolved_assets.items()
                }
            else:
                static_assets_dict = {
                    name: str(asset.absolute_path)
                    for name, asset in resolved_assets.items()
                }

            # STEP 4: Build pytest command
            pytest_cmd = self._build_pytest_command(test_files, static_assets_dict)
            logger.debug("Pytest command", command=pytest_cmd)

            # STEP 5: Execute pytest in Docker
            logger.info("Executing pytest")
            runtime = session.spawn()
            try:
                exec_result = runtime.execute(
                    pytest_cmd,
                    self.environment.get_full_env(self.checkpoint.env),
                    None,  # stdin
                    self.checkpoint.timeout,
                )
            finally:
                runtime.cleanup()

            logger.info(
                "Pytest execution complete",
                exit_code=exec_result.exit_code,
                duration=exec_result.elapsed,
            )

            # STEP 6: Parse CTRF report
            ctrf_path = workspace_path / ".scbench" / "ctrf-report.json"
            ctrf_tests = self._parse_ctrf_report(ctrf_path)

            # STEP 7: Check for infrastructure failures
            collection_ok, num_collected = self._check_collection_line(
                exec_result.stdout
            )

            infrastructure_failure = (
                exec_result.exit_code in INFRA_FAILURE_CODES or not collection_ok
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
            )

            # STEP 9: Convert CTRF tests to TestResults and add to results
            for test_data in ctrf_tests:
                test_result = self._convert_ctrf_test_to_result(test_data)
                results.add_test_result(test_result)

            logger.info(
                "Pytest evaluation complete",
                problem=self.problem.name,
                checkpoint=self.checkpoint.name,
                pass_counts=dict(results.pass_counts),
                total_counts=dict(results.total_counts),
                infrastructure_failure=infrastructure_failure,
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
) -> CorrectnessResults:
    """Run pytest evaluation for a checkpoint.

    This is the main entry point that replaces the old run_checkpoint() function
    from evaluation.runner. It creates a PytestRunner and executes tests.

    Args:
        submission_path: Path to the submission directory (contains code to test)
        problem: Problem configuration
        checkpoint: Checkpoint configuration to evaluate
        env_spec: Execution environment specification

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
    return runner.run()

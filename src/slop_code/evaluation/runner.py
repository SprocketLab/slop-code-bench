"""Primary orchestration logic for executing evaluation checkpoints.

The runner coordinates adapter construction, case discovery, user-defined
verifier wiring, and the aggregation of rich reporting data. It is invoked by
both the CLI and higher-level automation to execute an entire checkpoint.
"""

from __future__ import annotations

import time
from pathlib import Path

from slop_code.evaluation import adapters
from slop_code.evaluation.adapters.base import ADAPTER_REGISTRY
from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import GroupConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.loaders import CaseStore
from slop_code.evaluation.loaders import GroupLoader
from slop_code.evaluation.loaders import get_script_loader
from slop_code.evaluation.report import CorrectnessResults
from slop_code.evaluation.verifiers import VerifierProtocol
from slop_code.evaluation.verifiers import VerifierReport
from slop_code.evaluation.verifiers import VerifierReturnType
from slop_code.evaluation.verifiers import initialize_verifier
from slop_code.execution import EnvironmentSpec
from slop_code.execution import ResolvedStaticAsset
from slop_code.execution import Session
from slop_code.execution import Snapshot
from slop_code.execution import Workspace
from slop_code.execution import resolve_static_assets
from slop_code.logging import get_logger

logger = get_logger(__name__)

EXCLUDE_NAMES = ["venv", "__pycache__", ".venv"]


def initialize_loader(
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    use_placeholders: bool = False,
) -> GroupLoader:
    """Dynamically import a user-defined group loader from a problem directory.

    Args:
        problem_path: Path to the problem directory containing group_loader.py

    Returns:
        Group loader instance matching the GroupLoader protocol

    Raises:
        LoaderError: If the group loader cannot be imported or instantiated.
    """
    loader = get_script_loader(
        problem=problem,
        checkpoint=checkpoint,
        use_placeholders=use_placeholders,
    )
    logger.info("Initialized loader", loader_cls=type(loader).__qualname__)
    if not isinstance(loader, GroupLoader):
        raise ValueError("Loader is not a subclass of GroupLoader")
    return loader


def run_case(
    adapter: adapters.Adapter,
    case: adapters.BaseCase,
    expected: adapters.CaseResult,
    verifier_fn: VerifierProtocol,
    store: CaseStore,
) -> VerifierReport:
    """Execute a single case and evaluate it with the user verifier.

    Returns:
        Tuple of (VerifierReport, BaseCase, expected CaseResult) for debug logging.
    """
    t0 = time.time()
    invoke_result = adapter.run_case(case)
    try:
        result: VerifierReturnType = verifier_fn(
            group_name=case.group,
            case_name=case.id,
            actual=invoke_result,
            expected=expected,
        )
    except Exception as e:
        logger.error("Result", result=invoke_result.model_dump(mode="json"))
        logger.error("Expected", expected=expected.model_dump(mode="json"))
        logger.error(
            "Verifier error", error=str(e), exc_info=True, case=case.id
        )
        raise e
    duration = time.time() - t0
    store.update(case, invoke_result, expected)

    report = VerifierReport.from_verifier_result(
        case=case,
        duration=duration,
        actual_result=invoke_result,
        expected_result=expected,
        raw_results=result,
    )
    return report


class CheckpointRunner:
    def __init__(
        self,
        problem_name: str,
        submission: Path,
        checkpoint: CheckpointConfig,
        environment: EnvironmentSpec,
        entry_file: str,
        static_assets: dict[str, ResolvedStaticAsset],
        adapter: adapters.AdapterConfig,
        verifier: VerifierProtocol,
        loader: GroupLoader,
        version: int,
    ):
        self.problem_name = problem_name
        self.submission = submission
        self.checkpoint = checkpoint
        self.environment = environment
        self.entry_file = entry_file
        self.static_assets = static_assets
        self.adapter = adapter
        self.verifier = verifier
        self.loader = loader
        self.version = version

    def snapshot_fn(self, cwd: Path) -> Snapshot:
        return Snapshot.from_environment_spec(
            cwd=cwd,
            env_spec=self.environment,
            static_assets=self.static_assets,
        )

    @classmethod
    def from_problem(
        cls,
        problem: ProblemConfig,
        checkpoint_name: str,
        environment: EnvironmentSpec,
        submission: Path,
        static_assets: dict[str, ResolvedStaticAsset],
    ) -> CheckpointRunner:
        logger.info(
            "Initializing checkpoint runner from problem",
            problem=problem.name,
            environment=environment.name,
            environment_type=environment.type,
            submission=submission,
        )

        verifier = initialize_verifier(
            problem.path, problem.checkpoints[checkpoint_name]
        )
        loader = get_script_loader(
            problem=problem, checkpoint=problem.checkpoints[checkpoint_name]
        )

        return cls(
            problem_name=problem.name,
            submission=submission,
            checkpoint=problem.checkpoints[checkpoint_name],
            environment=environment,
            entry_file=problem.entry_file,
            static_assets=static_assets,
            adapter=problem.adapter,
            verifier=verifier,
            loader=loader,
            version=problem.version,
        )

    def run_group(
        self, group: GroupConfig, snapshot: Snapshot
    ) -> list[VerifierReport]:
        """Execute all cases in a group and collect results plus diagnostics.

        Args:
            group_path: Filesystem path to the group directory.
            group: Parsed group configuration.
            context: Checkpoint execution context providing adapters/env.
            checkpoint_config: Checkpoint configuration.
            problem_constants: Materialized constants available to every case.
            checkpoint_path: Filesystem path to the checkpoint directory.
            problem_module: Importable module name for the problem directory.

        Returns:
            Tuple of (reports, raw_cases) where reports is a list of VerifierReports
            and raw_cases is a list of (BaseCase, expected CaseResult) tuples.
        """
        logger.debug(
            "Setting up workspace and session for group", group=group.name
        )
        workspace = Workspace(
            initial_snapshot=snapshot,
            static_assets=self.static_assets,
            snapshot_fn=self.snapshot_fn,
            is_agent_infer=False,
        )
        session = Session(
            spec=self.environment,
            workspace=workspace,
            static_assets=self.static_assets,
            is_agent_infer=False,
        )

        results = []
        store = self.loader.initialize_store()
        with self.make_adapter(session=session) as adapter:
            for case, expected in self.loader(group=group, store=store):
                # Check if workspace should be reset based on group isolation or case reset flag
                should_reset = group.isolated or getattr(case, "reset", False)
                if should_reset:
                    logger.debug(
                        "Resetting workspace",
                        case=case.id,
                        group_name=case.group,
                        isolated=group.isolated,
                        case_reset=getattr(case, "reset", False),
                    )
                    workspace.reset()

                logger.debug(
                    "Running a case", case=case.id, group_name=case.group
                )
                report = run_case(
                    adapter=adapter,
                    case=case,
                    expected=expected,
                    verifier_fn=self.verifier,
                    store=store,
                )
                logger.debug(
                    "Finished case",
                    case=case.id,
                    group=case.group,
                    result=report.format_result(),
                    score=round(report.calculate_score(), 2),
                )
                results.append(report)

        return results

    def make_adapter(
        self, session: Session, isolated: bool = False
    ) -> adapters.Adapter:
        """Create an adapter instance using the registry.

        Args:
            session: Execution session managing workspace and runtime lifecycle.
            isolated: Whether to reset workspace after each case.

        Returns:
            An adapter instance appropriate for the configured adapter type.
        """
        env = self.environment.get_full_env(self.checkpoint.env)
        command = self.environment.get_command(
            self.entry_file, is_agent_run=False
        )
        return ADAPTER_REGISTRY.make_adapter(
            config=self.adapter,
            session=session,
            env=env,
            command=command,
            timeout=self.checkpoint.timeout,
            isolated=isolated,
        )

    def run(self) -> CorrectnessResults:
        base_snapshot = self.snapshot_fn(cwd=self.submission)
        report = CorrectnessResults(
            problem_name=self.problem_name,
            problem_version=self.version,
            name=self.checkpoint.name,
            version=self.checkpoint.version,
        )
        total_duration = 0
        for group_name, group in self.checkpoint.groups.items():
            logger.info(f"Starting group='{group_name}'")
            t0 = time.time()
            results = self.run_group(
                group=group,
                snapshot=base_snapshot,
            )
            elapsed = time.time() - t0

            report.add_group_report(
                group_name=group.name,
                group_type=group.type,
                reports=results,
                duration=elapsed,
            )
            total_duration += elapsed

        report.duration = total_duration

        return report


def run_checkpoint(
    submission_path: Path,
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    env_spec: EnvironmentSpec,
) -> CorrectnessResults:
    """Run a checkpoint end-to-end and produce an aggregated report.

    Args:
        seed: Deterministic seed shared with the adapter.
        submission_path: Path to the submission directory.
        problem: Parsed problem configuration.
        checkpoint_num: Index of the checkpoint to execute.
        problem_path: Path to the problem root on disk.
        env_spec: Execution environment specification (container, virtualenv).
        debug_path: Optional debug output path.

    Returns:
        :class:`~slop_code.evaluation.report.CheckpointReport` covering all
        groups.

    Raises:
        FileNotFoundError: If the checkpoint or a group path is missing.
        NotADirectoryError: If a group path exists but is not a directory.
    """

    logger.debug(
        "Running checkpoint",
        problem=problem.name,
        problem_path=problem.path,
        checkpoint=checkpoint.path.name,
    )
    static_assets = resolve_static_assets(
        base_path=problem.path,
        assets=problem.static_assets,
    )
    runner = CheckpointRunner.from_problem(
        problem=problem,
        checkpoint_name=checkpoint.path.name,
        environment=env_spec,
        submission=submission_path,
        static_assets=static_assets,
    )
    report = runner.run()

    logger.info(
        "Finished checkpoint",
        problem=problem.name,
        checkpoint=checkpoint.path.name,
        duration=f"{report.duration:.2f}s",
        groups=len(checkpoint.groups),
        pass_counts=report.pass_counts,
        total_counts=report.total_counts,
    )
    return report

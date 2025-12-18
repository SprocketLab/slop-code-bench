"""Agent runner orchestration for running agents across checkpoints."""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from slop_code import common
from slop_code.agent_runner import reporting
from slop_code.agent_runner.agent import Agent
from slop_code.agent_runner.agent import CheckpointInferenceResult
from slop_code.agent_runner.models import AgentRunSpec
from slop_code.agent_runner.models import UsageTracker
from slop_code.agent_runner.reporting import AgentCheckpointSummary
from slop_code.agent_runner.reporting import MetricsTracker
from slop_code.agent_runner.resume import ResumeInfo
from slop_code.agent_runner.state import AgentStateEnum
from slop_code.evaluation import CheckpointConfig
from slop_code.evaluation import CorrectnessResults
from slop_code.evaluation import PassPolicy
from slop_code.evaluation import ProblemConfig
from slop_code.evaluation import run_checkpoint as evaluate_checkpoint
from slop_code.execution import EnvironmentSpec
from slop_code.execution import Session
from slop_code.execution import resolve_static_assets
from slop_code.logging import get_logger
from slop_code.metrics import SnapshotQualityReport
from slop_code.metrics import measure_snapshot_quality
from slop_code.metrics.quality_io import save_quality_metrics

logger = get_logger(__name__)


class AgentRunnerError(Exception):
    """Exception raised by AgentRunner."""


def get_artifacts_path(checkpoint_save_dir: Path, *, compress: bool) -> Path:
    """Get the path to artifacts based on compression setting."""
    if compress:
        return checkpoint_save_dir / common.AGENT_TAR_FILENAME
    return checkpoint_save_dir / common.AGENT_DIR_NAME


def create_agent_session(
    problem_config: ProblemConfig,
    environment_spec: EnvironmentSpec,
) -> Session:
    """Create an execution session for an agent.

    Sets up a session with static assets from the problem configuration.

    Args:
        problem_config: Configuration for the problem being solved
        environment_spec: Specification for the execution environment

    Returns:
        Configured Session ready for agent execution
    """
    logger.debug(
        "Creating agent session",
        problem=problem_config.name,
        environment=environment_spec.type,
    )
    static_assets = resolve_static_assets(
        base_path=problem_config.path,
        assets=problem_config.static_assets,
    )
    return Session.from_environment_spec(
        spec=environment_spec,
        base_dir=None,
        static_assets=static_assets,
        is_agent_infer=True,
    )


def get_checkpoints(
    problem_config: ProblemConfig, output_path: Path
) -> Generator[tuple[CheckpointConfig, Path], None, None]:
    """Generator that yields checkpoints with their output directories.

    Loads checkpoints from config and sets up their output directories.

    Args:
        problem_config: Configuration containing checkpoint definitions
        output_path: Base directory for checkpoint outputs

    Yields:
        Tuple of (checkpoint_config, checkpoint_output_path) for each checkpoint
    """
    logger.debug(
        "Loading checkpoints",
        problem=problem_config.name,
        count=len(problem_config.checkpoints),
    )
    for (
        checkpoint_name,
        checkpoint,
    ) in problem_config.iterate_checkpoint_items():
        logger.debug(
            "Loading checkpoint",
            checkpoint_name=checkpoint_name,
            order=checkpoint.order,
        )
        checkpoint_save_dir = reporting.setup_checkpoint_output_directory(
            checkpoint=checkpoint, output_path=output_path
        )
        yield checkpoint, checkpoint_save_dir


def get_task_for_checkpoint(
    checkpoint: CheckpointConfig,
    template: str,
    entry_file: str,
    environment: EnvironmentSpec,
    *,
    is_first_checkpoint: bool,
    output_path: Path,
) -> str:
    """Generate the task prompt for a specific checkpoint.

    Renders checkpoint spec into a prompt using the template and saves it.

    Args:
        checkpoint: Checkpoint configuration
        template: Prompt template string
        entry_file: Entry file path for the task
        environment: Environment specification for command generation
        is_first_checkpoint: Whether this is the first checkpoint
        output_path: Directory where the prompt should be saved

    Returns:
        Rendered prompt string for the agent
    """
    logger.debug(
        "Generating task prompt",
        checkpoint=checkpoint.name,
        is_first=is_first_checkpoint,
    )
    prompt = common.render_prompt(
        spec_text=checkpoint.get_spec_text(),
        context={"is_continuation": not is_first_checkpoint},
        prompt_template=template,
        entry_file=environment.format_entry_file(entry_file),
        entry_command=environment.get_command(entry_file, is_agent_run=True),
    )
    with (output_path / common.PROMPT_FILENAME).open("w") as f:
        f.write(prompt)
    return prompt


def _should_run_replay(
    replay_path: Path | None,
    agent: Agent,
) -> bool:
    """Determine if replay should be run for a checkpoint.

    Args:
        replay_path: Path to the replay file
        agent: Agent wrapper to run

    Returns:
        True if replay should be run, False otherwise
    """
    if replay_path is None:
        logger.debug(
            "No replay path provided, running inference mode",
            agent=type(agent).__qualname__,
            replay_path=replay_path,
        )
        return False
    if not agent.supports_replay():
        logger.debug(
            "Agent does not support replay",
            agent=type(agent).__qualname__,
            replay_path=replay_path,
            supports_replay=agent.supports_replay(),
        )
        return False
    if not replay_path.exists():
        logger.warning(
            "Replay file does not exist, skipping replay",
            agent=type(agent).__qualname__,
            replay_path=replay_path,
        )
        return False
    if not replay_path.is_file():
        logger.warning(
            "Replay file is not a file, running inference mode",
            agent=type(agent).__qualname__,
            replay_path=replay_path,
        )
        return False
    return True


def _run_checkpoint_task(
    agent: Agent,
    task: str,
    checkpoint_name: str,
    replay_path: Path | None = None,
) -> CheckpointInferenceResult:
    """Run a checkpoint task with optional replay support."""

    if _should_run_replay(replay_path, agent):
        logger.info(
            "Loading replay steps",
            checkpoint=checkpoint_name,
            replay_path=str(replay_path),
        )
        replay_path = cast("Path", replay_path)
        return agent.run_replay(replay_path)

    logger.info(
        "Running checkpoint task with inference mode",
        checkpoint=checkpoint_name,
    )
    return agent.run_checkpoint(task)


def evaluate_agent_snapshot(
    checkpoint: CheckpointConfig,
    save_dir: Path,
    snapshot_dir: Path,
    problem: ProblemConfig,
    environment: EnvironmentSpec,
) -> tuple[CorrectnessResults, SnapshotQualityReport]:
    """Evaluate agent snapshot and compute quality metrics.

    Returns:
        Tuple of (checkpoint_report, quality_report)
    """
    logger.info(
        "Starting checkpoint evaluation",
        checkpoint=checkpoint.name,
        snapshot=snapshot_dir,
    )

    report = evaluate_checkpoint(
        submission_path=snapshot_dir,
        problem=problem,
        checkpoint=checkpoint,
        env_spec=environment,
    )

    report.save(save_dir)

    pretty_counts = {
        k: f"{report.pass_counts.get(k, 0)}/{v}"
        for k, v in report.total_counts.items()
    }
    logger.info(
        "Finished evaluation",
        checkpoint=checkpoint.name,
        result=pretty_counts,
    )

    # Calculate quality metrics
    logger.debug(
        "Calculating quality metrics",
        snapshot=snapshot_dir,
        entry_file=problem.entry_file,
    )
    formatted_entry = environment.format_entry_file(problem.entry_file)
    quality_metrics, file_metrics_list = measure_snapshot_quality(
        formatted_entry, snapshot_dir
    )
    save_quality_metrics(save_dir, quality_metrics, file_metrics_list)

    quality_report = SnapshotQualityReport.from_snapshot_metrics(
        quality_metrics
    )
    return report, quality_report


def _run_inference(
    checkpoint_name: str,
    session: Session,
    agent: Agent,
    task: str,
    save_dir: Path,
    replay_path: Path | None = None,
    *,
    compress_artifacts: bool = False,
):
    logger.info("Running inference for checkpoint", checkpoint=checkpoint_name)
    snapshot_dir = save_dir / common.SNAPSHOT_DIR_NAME
    try:
        result = _run_checkpoint_task(
            agent=agent,
            task=task,
            checkpoint_name=checkpoint_name,
            replay_path=replay_path,
        )

        logger.info(
            "Completed checkpoint inference",
            checkpoint=checkpoint_name,
        )

    finally:
        diff = session.finish_checkpoint(snapshot_dir)
        logger.debug(
            "Created checkpoint snapshot",
            checkpoint=checkpoint_name,
            changes=repr(diff),
        )
    reporting.save_agent_checkpoint_info(
        save_dir, diff, result, agent, compress_artifacts=compress_artifacts
    )

    return snapshot_dir, result


def run_checkpoint(
    agent: Agent,
    session: Session,
    save_dir: Path,
    checkpoint: CheckpointConfig,
    problem: ProblemConfig,
    environment: EnvironmentSpec,
    template: str,
    replay_path: Path | None = None,
    *,
    is_first_checkpoint: bool = True,
    compress_artifacts: bool = False,
) -> tuple[Path, CheckpointInferenceResult | None]:
    task = get_task_for_checkpoint(
        checkpoint=checkpoint,
        template=template,
        entry_file=problem.entry_file,
        environment=environment,
        is_first_checkpoint=is_first_checkpoint,
        output_path=save_dir,
    )
    snapshot_dir, result = _run_inference(
        checkpoint_name=checkpoint.name,
        session=session,
        agent=agent,
        task=task,
        save_dir=save_dir,
        replay_path=replay_path,
        compress_artifacts=compress_artifacts,
    )
    return snapshot_dir, result


class AgentRunner:
    """Orchestrates the full problem run with lifecycle management."""

    def __init__(
        self,
        run_spec: AgentRunSpec,
        agent: Agent,
        output_path: Path,
        progress_queue: queue.Queue,
        *,
        replay_path: Path | None = None,
        resume_info: ResumeInfo | None = None,
    ):
        self.run_spec = run_spec
        self.agent = agent
        self.output_path = output_path
        self.progress_queue = progress_queue
        self.replay_path = replay_path
        self.resume_info = resume_info

        # State to be populated during execution
        self._session: Session | None = None
        self.metrics_tracker: MetricsTracker = MetricsTracker(
            current_checkpoint="INIT",
            state=AgentStateEnum.INITIALIZED,
            usage=UsageTracker(),  # type: ignore[arg-type]
            started=datetime.now(),
            checkpoint_started=datetime.now(),
        )
        self.progress_thread: threading.Thread | None = None
        self.results: list[AgentCheckpointSummary] = []

    @property
    def session(self) -> Session:
        if self._session is None:
            raise AgentRunnerError("Session not set")
        return self._session

    def setup(self) -> None:
        """Create session, initialize metrics, start progress monitoring, setup output directory."""
        is_resuming = self.resume_info is not None
        logger.info(
            "Setting up agent run",
            problem=self.run_spec.problem.name,
            output_path=self.output_path,
            resuming=is_resuming,
        )

        # Setup output directory
        reporting.setup_run_output_directory(self.run_spec, self.output_path)

        # Initialize metrics tracker
        if is_resuming:
            # When resuming, initialize with prior usage from completed checkpoints
            self.metrics_tracker = MetricsTracker(
                current_checkpoint="RESUMING",
                usage=self.resume_info.prior_usage.model_copy(deep=True),
                started=datetime.now(),
                checkpoint_started=datetime.now(),
            )
            # Set prior_cost on agent for rate limit tracking
            self.agent.prior_cost = self.resume_info.prior_usage.cost
            logger.info(
                "Initialized metrics from prior checkpoints",
                prior_cost=self.resume_info.prior_usage.cost,
                prior_steps=self.resume_info.prior_usage.steps,
                completed_checkpoints=len(
                    self.resume_info.completed_checkpoints
                ),
            )
        else:
            self.metrics_tracker = MetricsTracker(
                current_checkpoint="STARTING",
                usage=UsageTracker(),  # type: ignore[arg-type]
                started=datetime.now(),
                checkpoint_started=datetime.now(),
            )

        # Send initial progress update
        self.progress_queue.put(
            (
                self.run_spec.problem.name,
                self.agent.usage,
                self.metrics_tracker,
            )
        )

        # Create session and enter context
        self._session = create_agent_session(
            problem_config=self.run_spec.problem,
            environment_spec=self.run_spec.environment,
        )
        self._session.__enter__()

        # If resuming, restore snapshot and run resume commands
        if is_resuming and self.resume_info.last_snapshot_dir:
            self._session.restore_from_snapshot_dir(
                self.resume_info.last_snapshot_dir
            )
            self._run_resume_commands()

        # Start progress monitoring
        self.progress_thread = threading.Thread(
            target=agent_progress_watcher,
            args=(
                self.agent,
                self.metrics_tracker,
                self.progress_queue,
                self.run_spec.problem.name,
            ),
            daemon=True,
        )
        self.progress_thread.start()

    def _run_resume_commands(self) -> None:
        """Run resume commands after restoring snapshot.

        These commands are run to restore the environment state,
        such as reinstalling dependencies that may have been installed
        by the agent in previous checkpoints.
        """
        resume_commands = self.run_spec.environment.get_resume_commands()
        if not resume_commands:
            logger.debug("No resume commands to run")
            return

        logger.info(
            "Running resume commands",
            num_commands=len(resume_commands),
        )

        # Spawn a runtime just for running resume commands
        runtime = self.session.spawn(disable_setup=True)
        try:
            for cmd in resume_commands:
                logger.debug("Running resume command", command=cmd)
                result = runtime.execute(cmd, env={}, stdin=None, timeout=300)
                if result.exit_code != 0:
                    logger.warning(
                        "Resume command failed",
                        command=cmd,
                        exit_code=result.exit_code,
                        stderr=result.stderr[:500] if result.stderr else None,
                    )
                else:
                    logger.debug(
                        "Resume command completed",
                        command=cmd,
                        exit_code=result.exit_code,
                    )
        finally:
            runtime.cleanup()

    def run(self) -> dict[str, Any]:
        """Main entry point: setup, execute checkpoints, finish."""
        logger.info(
            "Starting agent run",
            problem=self.run_spec.problem.name,
        )

        self.setup()
        try:
            self.results = self._run_problem()
        except Exception as e:
            tb_text = traceback.format_exc()
            logger.error(
                "Error running problem",
                problem=self.run_spec.problem.name,
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=tb_text,
                exc_info=True,
            )
            self.metrics_tracker.record_error(e, traceback_text=tb_text)
            self.metrics_tracker.state = AgentStateEnum.ERROR
            raise
        finally:
            results = self.finish()
        logger.info("Problem run completed", problem=self.run_spec.problem.name)
        return results

    def _setup_for_checkpoint(self, checkpoint: CheckpointConfig) -> None:
        # Update agent state for this checkpoint
        if self.metrics_tracker.state in {
            AgentStateEnum.INITIALIZED,
            AgentStateEnum.PENDING,
        }:
            logger.info(
                "Starting agent for the first checkpoint",
                checkpoint=checkpoint.name,
            )
            self.agent.setup(session=self.session)
            return

        logger.info(
            "Resetting agent context for the checkpoint",
            checkpoint=checkpoint.name,
        )
        self.agent.finish_checkpoint(reset_context=True)

    def finish(self) -> dict[str, Any]:
        """Cleanup agent, stop monitoring, save final results."""
        logger.debug("Finishing agent run", problem=self.run_spec.problem.name)

        # Cleanup agent
        self.agent.cleanup()

        # Close session
        if self._session is not None:
            self._session.__exit__(None, None, None)

        # Save final results
        final_results = reporting.save_results(
            self.results, self.metrics_tracker, self.run_spec, self.output_path
        )

        logger.info(
            "Agent run finished",
            problem=self.run_spec.problem.name,
            final_state=self.metrics_tracker.state.value,
            passed=final_results["summary"]["passed_policy"],
        )

        return final_results

    def _should_early_stop(self, summary: AgentCheckpointSummary) -> bool:
        did_fail_tests = (
            summary.passed_policy is not None and not summary.passed_policy
        )
        if self.run_spec.skip_evaluation:
            did_fail_tests = False
        if did_fail_tests and self.run_spec.pass_policy != PassPolicy.ANY_CASE:
            logger.info(
                "Checkpoint failed due to solution failing tests and thus not passing pass policy"
            )
            if self.metrics_tracker.state not in {
                AgentStateEnum.ERROR,
                AgentStateEnum.HIT_RATE_LIMITED,
            }:
                self.metrics_tracker.state = AgentStateEnum.FAILED
            return True
        if self.metrics_tracker.state == AgentStateEnum.HIT_RATE_LIMITED:
            logger.info("Stopping due to hitting rate limit")
            return True
        if self.metrics_tracker.state == AgentStateEnum.ERROR:
            logger.error(
                "Agent had error while running checkpoint",
                error=summary.error_message,
            )

            return True
        return False

    def _run_checkpoint(
        self,
        checkpoint: CheckpointConfig,
        checkpoint_save_dir: Path,
        is_first_checkpoint: bool,
    ) -> AgentCheckpointSummary:
        self._setup_for_checkpoint(checkpoint)
        self.metrics_tracker.state = AgentStateEnum.RUNNING
        compress = self.run_spec.compress_artifacts
        snapshot_dir, result = run_checkpoint(
            agent=self.agent,
            session=self.session,
            save_dir=checkpoint_save_dir,
            checkpoint=checkpoint,
            problem=self.run_spec.problem,
            environment=self.run_spec.environment,
            template=self.run_spec.template,
            replay_path=self.replay_path,
            is_first_checkpoint=is_first_checkpoint,
            compress_artifacts=compress,
        )
        artifacts_path = get_artifacts_path(
            checkpoint_save_dir, compress=compress
        )
        if result is None or result.had_error:
            if result is None:
                error = AgentRunnerError(
                    f"Agent produced no result for checkpoint '{checkpoint.name}'"
                )
                tb_text = None
            else:
                err_msg = (
                    result.error_message
                    or f"Agent reported an unspecified error on '{checkpoint.name}'"
                )
                error = AgentRunnerError(err_msg)
                tb_text = err_msg
            self.metrics_tracker.record_error(error, traceback_text=tb_text)
            self.metrics_tracker.state = AgentStateEnum.ERROR
        elif self.agent.hit_net_rate_limit():
            logger.warning(
                "Agent hit rate limit during checkpoint",
                checkpoint=checkpoint.name,
            )
            self.metrics_tracker.state = AgentStateEnum.HIT_RATE_LIMITED
        if self.run_spec.skip_evaluation or result is None:
            return AgentCheckpointSummary.from_results(
                checkpoint_name=checkpoint.name,
                path=checkpoint_save_dir,
                snapshot_dir=snapshot_dir,
                artifacts=artifacts_path,
                usage=self.agent.usage,
                had_error=result is None or result.had_error,
                pass_policy=self.run_spec.pass_policy,
                evaluation_result=None,
            )
        report, _ = evaluate_agent_snapshot(
            checkpoint=checkpoint,
            save_dir=checkpoint_save_dir,
            snapshot_dir=snapshot_dir,
            problem=self.run_spec.problem,
            environment=self.run_spec.environment,
        )
        return AgentCheckpointSummary.from_results(
            checkpoint_name=checkpoint.name,
            path=checkpoint_save_dir,
            snapshot_dir=snapshot_dir,
            artifacts=artifacts_path,
            usage=self.agent.usage,
            had_error=result.had_error,
            pass_policy=self.run_spec.pass_policy,
            evaluation_result=report,
        )

    def _load_checkpoint_summary(
        self,
        checkpoint: CheckpointConfig,
        checkpoint_save_dir: Path,
    ) -> AgentCheckpointSummary | None:
        """Load checkpoint summary from existing results.

        Used when resuming to include results from previously completed
        checkpoints without re-running them.

        Args:
            checkpoint: Checkpoint configuration
            checkpoint_save_dir: Directory containing checkpoint results

        Returns:
            AgentCheckpointSummary if results exist, None otherwise
        """
        result_path = checkpoint_save_dir / common.INFERENCE_RESULT_FILENAME
        if not result_path.exists():
            logger.warning(
                "No inference_result.json for completed checkpoint",
                checkpoint=checkpoint.name,
            )
            return None

        try:
            with result_path.open() as f:
                result_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(
                "Failed to read inference_result.json",
                checkpoint=checkpoint.name,
                error=str(e),
            )
            return None

        snapshot_dir = checkpoint_save_dir / common.SNAPSHOT_DIR_NAME
        usage_data = result_data.get("usage", {})

        # Load evaluation results if available
        eval_path = checkpoint_save_dir / common.EVALUATION_FILENAME
        evaluation_result = None
        if eval_path.exists():
            try:
                evaluation_result = CorrectnessResults.from_dir(
                    checkpoint_save_dir
                )
                # Load quality report if available
                quality_path = (
                    checkpoint_save_dir
                    / common.QUALITY_DIR
                    / common.QUALITY_METRIC_SAVENAME
                )
                if quality_path.exists():
                    with quality_path.open() as f:
                        quality_data = json.load(f)
                    from slop_code.metrics import SnapshotMetrics

                    metrics = SnapshotMetrics(**quality_data)
                    quality_report = (
                        SnapshotQualityReport.from_snapshot_metrics(metrics)
                    )
            except (OSError, json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning(
                    "Failed to load evaluation results",
                    checkpoint=checkpoint.name,
                    error=str(e),
                )

        artifacts_path = get_artifacts_path(
            checkpoint_save_dir, compress=self.run_spec.compress_artifacts
        )
        return AgentCheckpointSummary.from_results(
            checkpoint_name=checkpoint.name,
            path=checkpoint_save_dir,
            snapshot_dir=snapshot_dir,
            artifacts=artifacts_path,
            usage=UsageTracker(**usage_data) if usage_data else UsageTracker(),
            had_error=result_data.get("had_error", False),
            pass_policy=self.run_spec.pass_policy,
            evaluation_result=evaluation_result,
        )

    def _run_problem(self) -> list[AgentCheckpointSummary]:
        """Iterate through checkpoints, skipping completed ones if resuming."""
        # Determine checkpoints to skip when resuming
        completed_set: set[str] = set()
        if self.resume_info:
            completed_set = set(self.resume_info.completed_checkpoints)

        logger.info(
            "Starting problem run",
            problem=self.run_spec.problem.name,
            checkpoints=len(self.run_spec.problem.checkpoints),
            skipping=len(completed_set),
        )

        results = []
        for idx, (checkpoint, checkpoint_save_dir) in enumerate(
            get_checkpoints(self.run_spec.problem, self.output_path)
        ):
            # Skip completed checkpoints when resuming
            if checkpoint.name in completed_set:
                logger.info(
                    "Skipping completed checkpoint",
                    checkpoint=checkpoint.name,
                    index=idx + 1,
                )
                # Load existing results for this checkpoint
                existing_summary = self._load_checkpoint_summary(
                    checkpoint, checkpoint_save_dir
                )
                if existing_summary:
                    results.append(existing_summary)
                    self.metrics_tracker.finish_checkpoint(
                        existing_summary.usage
                    )
                continue

            logger.info(
                "Running checkpoint",
                checkpoint=checkpoint.name,
                index=idx + 1,
                total=len(self.run_spec.problem.checkpoints),
            )

            self.metrics_tracker.current_checkpoint = checkpoint.name
            self.metrics_tracker.checkpoint_started = datetime.now()

            summary = self._run_checkpoint(
                checkpoint,
                checkpoint_save_dir,
                idx == 0,
            )
            results.append(summary)
            self.metrics_tracker.finish_checkpoint(self.agent.usage)

            logger.info(
                "Checkpoint finished",
                passed_policy=summary.passed_policy,
                had_error=summary.had_error,
                pass_policy=self.run_spec.pass_policy.value,
                save_dir=str(checkpoint_save_dir.absolute()),
                checkpoint_name=summary.checkpoint_name,
            )

            # Check for early termination
            if self._should_early_stop(summary):
                return results

        logger.info(
            "All checkpoints completed successfully",
            problem=self.run_spec.problem.name,
        )
        self.metrics_tracker.state = AgentStateEnum.COMPLETED
        return results


def agent_progress_watcher(
    agent: Agent,
    metrics_tracker: MetricsTracker,
    progress_queue: queue.Queue,
    problem_name: str,
) -> None:
    """Watch agent progress and report to a queue.

    Monitors agent state and puts progress updates into the queue
    until the agent reaches a terminal state.

    Args:
        agent: Agent wrapper to monitor
        progress_queue: Queue for progress updates
        problem_name: Name of the problem being solved
        current_checkpoint_name: Mutable list containing current checkpoint name
    """
    logger.debug("Starting agent progress watcher", problem=problem_name)
    prev_cost = prev_steps = prev_tokens = prev_net_tokens = None
    prev_state = AgentStateEnum.PENDING
    while True:
        if (
            prev_cost == agent.usage.cost
            and prev_steps == agent.usage.steps
            and prev_tokens == agent.usage.current_tokens
            and prev_net_tokens == agent.usage.net_tokens
            and prev_state == metrics_tracker.state
        ):
            threading.Event().wait(0.25)
            continue
        prev_cost = agent.usage.cost
        prev_steps = agent.usage.steps
        prev_tokens = agent.usage.current_tokens
        prev_net_tokens = agent.usage.net_tokens

        prev_state = metrics_tracker.state
        progress_queue.put(
            (
                problem_name,
                agent.usage.model_copy(deep=True),
                metrics_tracker.model_copy(deep=True),
            )
        )
        if metrics_tracker.state in {
            AgentStateEnum.FAILED,
            AgentStateEnum.ERROR,
            AgentStateEnum.HIT_RATE_LIMITED,
            AgentStateEnum.COMPLETED,
        }:
            logger.debug(
                "Agent reached terminal state",
                problem=problem_name,
                state=metrics_tracker.state.value,
            )
            break
        time.sleep(0.1)


def run_agent(
    run_spec: AgentRunSpec,
    agent: Agent,
    output_path: Path,
    progress_queue: queue.Queue,
    *,
    replay_path: Path | None = None,
    resume_info: ResumeInfo | None = None,
) -> dict[str, Any]:
    """Run an agent through a complete problem specification.

    Orchestrates agent execution including setup, progress monitoring,
    checkpoint execution, and result saving. Runs in a session with cleanup.

    This is a backward-compatible wrapper around AgentRunner.

    Args:
        run_spec: Complete specification for the agent run
        agent: Agent to run
        output_path: Directory for all output files
        progress_queue: Queue for progress updates to consumer
        replay_path: Optional directory containing replay trajectories
        resume_info: Optional resume information for continuing from checkpoint

    Returns:
        Dictionary containing the complete run results
    """
    runner = AgentRunner(
        run_spec=run_spec,
        agent=agent,
        output_path=output_path,
        progress_queue=progress_queue,
        replay_path=replay_path,
        resume_info=resume_info,
    )
    return runner.run()

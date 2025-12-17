"""Run a single test case (or filtered subset) and output JSON results."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import Annotated

import typer

from slop_code.entrypoints.commands import common
from slop_code.entrypoints.config import loader as config_loader
from slop_code.evaluation.runner import CheckpointRunner
from slop_code.evaluation.runner import run_case as _run_case
from slop_code.execution import Session
from slop_code.execution import Workspace
from slop_code.execution import resolve_static_assets
from slop_code.logging import setup_logging


def register(app: typer.Typer, name: str) -> None:
    app.command(
        name,
        help="Run a single test case (or filtered subset) and output JSON.",
    )(run_case)


def run_case(
    ctx: typer.Context,
    snapshot_dir: Annotated[
        Path,
        typer.Option(
            "--snapshot-dir",
            "-s",
            help="Path to the snapshot directory",
            exists=True,
            dir_okay=True,
            file_okay=False,
        ),
    ],
    problem_name: Annotated[
        str,
        typer.Option(
            "-p",
            "--problem",
            help="Name of the problem",
        ),
    ],
    checkpoint_num: Annotated[
        int,
        typer.Option(
            "-c",
            "--checkpoint",
            help="Checkpoint number",
        ),
    ],
    env_config: Annotated[
        Path,
        typer.Option(
            "-e",
            "--env-config",
            help="Path to environment specification configuration",
            exists=True,
            dir_okay=False,
            file_okay=True,
        ),
    ],
    group_filter: Annotated[
        str | None,
        typer.Option(
            "-g",
            "--group",
            help="Filter by group name (supports glob patterns)",
        ),
    ] = None,
    case_filter: Annotated[
        str | None,
        typer.Option(
            "--case",
            help="Filter by case name (supports glob patterns)",
        ),
    ] = None,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Enable debug logging output",
        ),
    ] = False,
) -> None:
    """Run filtered test cases and print JSON results to stdout."""

    setup_logging(verbosity=1)
    problem_path = ctx.obj.problem_path / problem_name
    problem = common.load_problem_config_or_exit(problem_path)
    environment = config_loader.resolve_environment(env_config)

    ordered_checkpoints = list(problem.iterate_checkpoint_items())
    if checkpoint_num < 1 or checkpoint_num > len(ordered_checkpoints):
        typer.echo(
            typer.style(
                f"Checkpoint {checkpoint_num} out of range (1-{len(ordered_checkpoints)})",
                fg=typer.colors.RED,
            )
        )
        raise typer.Exit(1)

    checkpoint_name, checkpoint = ordered_checkpoints[checkpoint_num - 1]

    common.ensure_docker_ready(environment)

    static_assets = resolve_static_assets(
        base_path=problem.path,
        assets=problem.static_assets,
    )

    runner = CheckpointRunner.from_problem(
        problem=problem,
        checkpoint_name=checkpoint_name,
        environment=environment,
        submission=snapshot_dir,
        static_assets=static_assets,
    )

    results = []

    # Create session once for all groups to share server state
    snapshot = runner.snapshot_fn(runner.submission)
    workspace = Workspace(
        initial_snapshot=snapshot,
        static_assets=runner.static_assets,
        snapshot_fn=runner.snapshot_fn,
        is_agent_infer=False,
    )
    session = Session(
        spec=runner.environment,
        workspace=workspace,
        static_assets=runner.static_assets,
        is_agent_infer=False,
    )

    with runner.make_adapter(session=session) as adapter:
        for group_name, group in runner.checkpoint.groups.items():
            if group_filter and not fnmatch.fnmatch(group_name, group_filter):
                continue

            # Fresh store for each group
            store = runner.loader.initialize_store()
            for case, expected in runner.loader(group=group, store=store):
                if case_filter and not fnmatch.fnmatch(case.id, case_filter):
                    continue

                if full:
                    typer.echo(f"Running {group_name}/{case.id}...", err=True)

                report = _run_case(
                    adapter=adapter,
                    case=case,
                    expected=expected,
                    verifier_fn=runner.verifier,
                    store=store,
                )

                if full:
                    # Full output: entire report
                    output = report.model_dump(mode="json")
                else:
                    # Filtered output
                    output = {
                        "id": report.id,
                        "group": report.group,
                        "score": report.calculate_score(),
                        "passed": report.did_pass(),
                    }

                    # Filter results: include verified fields and stderr
                    filtered_results = {}
                    for attr_name, attr_result in report.results.items():
                        is_stderr = attr_name == "stderr"
                        is_verified = attr_result.is_correct is not None
                        if is_verified or is_stderr:
                            filtered_results[attr_name] = attr_result.model_dump(
                                mode="json"
                            )

                    if filtered_results:
                        output["results"] = filtered_results

                results.append(output)

    print(json.dumps(results, indent=2))

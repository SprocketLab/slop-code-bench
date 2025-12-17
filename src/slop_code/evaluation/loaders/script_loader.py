from __future__ import annotations

from slop_code.evaluation.config import CheckpointConfig
from slop_code.evaluation.config import ProblemConfig
from slop_code.evaluation.loaders.loader_protocol import GroupLoader
from slop_code.evaluation.loaders.loader_protocol import LoaderError
from slop_code.logging import get_logger
from slop_code.protocol_loader import ProtocolLoadError
from slop_code.protocol_loader import get_source_files
from slop_code.protocol_loader import load_protocol_entrypoint

logger = get_logger(__name__)


def get_script_loader(
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
    use_placeholders: bool = False,
) -> GroupLoader:
    """Get a script loader instance."""

    loader_cls = load_protocol_entrypoint(
        protocol=GroupLoader,
        module_path=problem.path / problem.loader_script,
        entrypoint_name=problem.loader_entrypoint,
    )
    logger.debug(
        "Initialized script loader", loader_cls=loader_cls.__qualname__
    )
    return loader_cls(
        problem=problem,
        checkpoint=checkpoint,
        use_placeholders=use_placeholders,
    )


def get_group_loader_source_files(
    problem: ProblemConfig,
    checkpoint: CheckpointConfig,
) -> dict[str, str]:
    """Get source code for the group loader and its dependencies.

    This ensures downstream consumers (e.g. reporting or artifact capture)
    can display the exact group loading logic that executed for a checkpoint.

    Args:
        problem_path: Filesystem path to the problem directory.
        loader_config: Loader configuration.
    Returns:
        Mapping of problem-relative file paths to their UTF-8 source contents.

    Raises:
        LoaderError: If the group loader source cannot be retrieved.
    """
    group_loader_path = problem.path / problem.loader_script

    try:
        return get_source_files(
            module_path=group_loader_path,
            load_function=lambda: get_script_loader(
                problem=problem, checkpoint=checkpoint
            ),
        )
    except ProtocolLoadError as e:
        logger.error(
            "Failed to get group loader source files",
            problem=problem,
            loader_path=group_loader_path,
            error=str(e),
        )
        raise LoaderError(
            f"Failed to get source files for {group_loader_path}: {e}"
        ) from e

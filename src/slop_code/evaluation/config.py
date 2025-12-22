"""Configuration models for evaluation problems, checkpoints, and groups.

Evaluation metadata is authored as YAML at three nested levels:

* **Problem** - global knobs that span every checkpoint (environment, tags,
  documentation, and static assets).
* **Checkpoint** - execution-specific wiring for a milestone, including the
  adapter configuration and the list of groups to run.
* **Group** - case discovery rules plus the normalizer and verifier pipelines
  that assert behavior.

This module turns that YAML into Pydantic models with light validation and
helper methods for propagating shared fields from parents to children. The
models are intentionally declarative so that higher-level orchestration code
can focus on execution rather than schema management.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import model_validator

from slop_code.evaluation.report import GroupType

DEFAULT_GROUP_TYPE = GroupType.CORE
from slop_code.evaluation.utils import nested_priority_merge
from slop_code.execution import StaticAssetConfig
from slop_code.logging import get_logger

logger = get_logger(__name__)


class ConfigError(Exception):
    """Error raised when a configuration is invalid."""


class MarkerConfig(BaseModel):
    """Configuration for a custom pytest marker.

    Custom markers allow problems to define additional test categorizations
    beyond the built-in markers (error, functionality, regression). Each
    custom marker must specify which GroupType it maps to.

    Attributes:
        description: Description shown in pytest.ini marker registration.
        group: GroupType this marker maps to for test categorization.

    Example:
        >>> config = MarkerConfig(
        ...     description="performance and load tests",
        ...     group=GroupType.FUNCTIONALITY,
        ... )
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    description: str = Field(description="Marker description for pytest.ini")
    group: GroupType = Field(description="GroupType this marker maps to")


class BaseConfig(BaseModel):
    """Shared knobs present on problem, checkpoint, and group models.

    The base configuration captures execution-wide defaults that should flow
    from a parent scope (problem) down to a child scope (checkpoint/group).
    Instances are merged using
    :func:`slop_code.evaluation.utils.nested_priority_merge` so child values
    always win.

    Attributes:
        env: Mapping of environment variables to inject for each case run.
        timeout: Default timeout, in seconds, applied when a more specific
            value is not provided.
    """

    env: dict[str, str] = Field(
        default_factory=dict,
        description="Environment variables to inject during case execution.",
    )
    timeout: float | None = Field(
        default=None,
        description="Default timeout in seconds for executions (overridable).",
    )

    def get_base_config(self) -> dict[str, Any]:
        """Return the subset of fields that can be inherited by child scopes.

        The returned mapping intentionally mirrors the YAML structure so it
        can be merged directly into a child configuration without additional
        munging.

        Returns:
            Dictionary containing ``env`` and ``timeout`` along with optional
            ``timezone``/``fake_now`` fields if they were defined on the model.
        """
        return {
            "env": self.env,
            "timeout": self.timeout,
        }


class GroupConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)
    name: str = Field(
        description="Name of the group.",
    )
    type: GroupType = Field(
        default=DEFAULT_GROUP_TYPE,
        description="Type of the group.",
    )
    group_files: set[str] = Field(
        default_factory=set,
        description="Files materialized into every case working directory.",
    )
    original_checkpoint: str | None = Field(
        default=None,
        description=(
            "Original checkpoint name if this group is a regression group."
        ),
    )
    original_group: str | None = Field(
        default=None,
        description=(
            "Original group name if this group is a regression group."
        ),
    )
    case_order: list[str] = Field(
        default_factory=list,
        description="Order of cases in the group.",
    )
    timeout: float | None = Field(
        default=None,
        description="Timeout in seconds for the group.",
    )
    case_defaults: dict[str, Any] = Field(
        default_factory=dict,
        description="Default values for cases in the group.",
    )
    isolated: bool = Field(
        default=True,
        description=(
            "Reset workspace between each case in the group. When True, each "
            "case starts with a clean workspace state."
        ),
    )

    @model_validator(mode="after")
    def validate_type(self) -> Self:
        if self.type != GroupType.REGRESSION and (
            self.original_checkpoint is not None
            or self.original_group is not None
        ):
            raise ConfigError(
                "Original checkpoint or group is not allowed for "
                "non-regression groups"
            )
        if self.original_checkpoint is not None and self.original_group is None:
            raise ConfigError(
                "Original checkpoint is set without an original group"
            )
        if self.original_group is not None and self.original_checkpoint is None:
            raise ConfigError(
                "Original group is set without an original checkpoint"
            )
        return self

    def get_real_name(self) -> str:
        """Gets the actual name of the group if it is a regression group."""
        if self.original_group is not None:
            return self.original_group
        return self.name


class RegressionSpec(BaseModel):
    """Declarative specification for importing groups from prior checkpoints.

    Supports both explicit enumeration and bulk imports with wildcards. When
    a regression spec is processed, it expands into one or more GroupConfig
    instances that are merged into the checkpoint's groups dict.

    Attributes:
        checkpoint: Single checkpoint name to import from.
        checkpoints: List of checkpoint names or "*" for all prior.
        groups: List of group names to import. If empty, imports all groups.
        type_filter: Optional GroupType filter (e.g., "Core").
        exclude: Group names to skip even if matched by other criteria.
        name_template: Template for group names. Supports placeholders:
            {checkpoint}, {group}, {idx}. Default: "{checkpoint}_{group}".
    """

    model_config = ConfigDict(extra="forbid")
    checkpoint: str | None = Field(
        default=None,
        description="Single checkpoint to import groups from.",
    )
    checkpoints: list[str] | Literal["*"] | None = Field(
        default=None,
        description="List of checkpoints or '*' for all prior checkpoints.",
    )
    groups: list[str] = Field(
        default_factory=list,
        description="Group names to import. Empty means all groups.",
    )
    type_filter: GroupType | None = Field(
        default=None,
        description="Only import groups matching this type.",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="Group names to exclude from import.",
    )
    name_template: str = Field(
        default="{checkpoint}_{group}",
        description="Template for generated group names.",
    )

    @model_validator(mode="after")
    def validate_checkpoint_spec(self) -> Self:
        if self.checkpoint is not None and self.checkpoints is not None:
            raise ConfigError(
                "Cannot specify both 'checkpoint' and 'checkpoints'"
            )
        if self.checkpoint is None and self.checkpoints is None:
            raise ConfigError(
                "Must specify either 'checkpoint' or 'checkpoints'"
            )
        return self


def _resolve_checkpoint_names(
    spec: RegressionSpec,
    available_checkpoints: dict[str, dict[str, Any]],
    current_checkpoint_order: int,
) -> list[str]:
    """Resolve checkpoint names from a regression spec.

    Args:
        spec: Regression specification with checkpoint/checkpoints fields.
        available_checkpoints: Dict of checkpoint configs with order metadata.
        current_checkpoint_order: Order of the current checkpoint being loaded.

    Returns:
        List of checkpoint names to import from.

    Raises:
        ConfigError: If wildcard cannot be resolved or checkpoints don't exist.
    """
    if spec.checkpoint is not None:
        return [spec.checkpoint]

    if spec.checkpoints == "*":
        # Get all checkpoints with order < current_checkpoint_order
        prior_checkpoints = [
            name
            for name, cfg in available_checkpoints.items()
            if cfg.get("order", 0) < current_checkpoint_order
        ]
        if not prior_checkpoints:
            logger.warning(
                "Wildcard regression matched no prior checkpoints",
                current_order=current_checkpoint_order,
            )
        return sorted(
            prior_checkpoints,
            key=lambda name: available_checkpoints[name].get("order", 0),
        )

    # List of explicit checkpoint names
    return spec.checkpoints or []


def _expand_single_regression(
    spec: RegressionSpec,
    checkpoint_name: str,
    source_groups: dict[str, Any],
    regression_idx: int,
) -> dict[str, dict[str, Any]]:
    """Expand a regression spec for a single checkpoint into group configs.

    Args:
        spec: Regression specification.
        checkpoint_name: Name of the source checkpoint.
        source_groups: Raw group config dicts from the source checkpoint.
        regression_idx: Index of this regression for template expansion.

    Returns:
        Dict mapping generated group names to raw group config dicts.
    """
    expanded_groups = {}

    # Determine which groups to import
    target_groups = spec.groups if spec.groups else list(source_groups.keys())

    for group_name in target_groups:
        if group_name in spec.exclude:
            continue

        if group_name not in source_groups:
            logger.warning(
                "Regression group not found in source checkpoint",
                checkpoint=checkpoint_name,
                group=group_name,
            )
            continue

        source_group = source_groups[group_name]

        # Apply type filter - source_group might be GroupConfig or dict
        source_type = (
            source_group.type
            if isinstance(source_group, GroupConfig)
            else source_group.get("type", DEFAULT_GROUP_TYPE)
        )
        if spec.type_filter is not None and source_type != spec.type_filter:
            continue

        # Generate regression group name
        regression_name = spec.name_template.format(
            checkpoint=checkpoint_name,
            group=group_name,
            idx=regression_idx,
        )

        # Create regression group config dict (not GroupConfig yet)
        # Note: Don't include "name" here as it will be passed separately
        # during GroupConfig construction
        if isinstance(source_group, GroupConfig):
            # Source is already a GroupConfig, extract fields
            expanded_groups[regression_name] = {
                "type": GroupType.REGRESSION,
                "original_checkpoint": checkpoint_name,
                "original_group": group_name,
                "group_files": source_group.group_files,
                "case_order": source_group.case_order,
                "timeout": source_group.timeout,
                "case_defaults": source_group.case_defaults,
            }
        else:
            # Source is a raw dict, copy and override (remove name if present)
            expanded_groups[regression_name] = {
                **{k: v for k, v in source_group.items() if k != "name"},
                "type": GroupType.REGRESSION,
                "original_checkpoint": checkpoint_name,
                "original_group": group_name,
            }

    return expanded_groups


def _expand_regressions(
    regression_specs: list[RegressionSpec],
    available_checkpoints: dict[str, dict[str, Any]],
    current_checkpoint_order: int,
) -> dict[str, dict[str, Any]]:
    """Expand all regression specs into group config dicts.

    Args:
        regression_specs: List of regression specifications to expand.
        available_checkpoints: All available checkpoint configs (raw dicts).
        current_checkpoint_order: Order of the checkpoint being loaded.

    Returns:
        Dict mapping regression group names to raw group config dicts.

    Raises:
        ConfigError: If a referenced checkpoint or group doesn't exist.
    """
    all_regression_groups = {}

    for idx, spec in enumerate(regression_specs):
        checkpoint_names = _resolve_checkpoint_names(
            spec, available_checkpoints, current_checkpoint_order
        )

        for checkpoint_name in checkpoint_names:
            if checkpoint_name not in available_checkpoints:
                raise ConfigError(
                    f"Regression references non-existent checkpoint: "
                    f"{checkpoint_name}"
                )

            source_checkpoint_cfg = available_checkpoints[checkpoint_name]
            source_groups = source_checkpoint_cfg.get("groups", {})

            regression_groups = _expand_single_regression(
                spec, checkpoint_name, source_groups, idx
            )

            # Check for name collisions
            for name in regression_groups:
                if name in all_regression_groups:
                    logger.warning(
                        "Regression group name collision, overwriting",
                        group=name,
                        checkpoint=checkpoint_name,
                    )

            all_regression_groups.update(regression_groups)

    return all_regression_groups


def _resolve_problem_config_path(path: Path) -> Path:
    """Resolve the config.yaml path from a directory or file path.

    Args:
        path: Either a directory containing config.yaml or a direct path to
            a YAML configuration file.

    Returns:
        Resolved path to the configuration file.

    Raises:
        ConfigError: If the path is neither a directory nor a .yaml file.
    """
    if path.is_dir():
        return path / "config.yaml"
    if path.suffix == ".yaml":
        return path
    raise ConfigError(f"Invalid problem config path: {path}")


def _normalize_checkpoints_from_list(
    problem_path: Path,
    checkpoints: list,
) -> dict[str, dict[str, Any]]:
    """Convert a list of checkpoint names into normalized checkpoint configs.

    When checkpoints are specified as a simple list of directory names, this
    function loads each checkpoint's config.yaml (if present) and wraps it
    with order and path metadata.

    Args:
        problem_path: Path to the problem directory.
        checkpoints: List of checkpoint directory names.

    Returns:
        Dict mapping checkpoint names to their raw configuration dicts.

    Raises:
        ConfigError: If a checkpoint name is not a string or config is invalid.
    """
    normalized: dict[str, dict[str, Any]] = {}
    for idx, checkpoint_name in enumerate(checkpoints, start=1):
        if not isinstance(checkpoint_name, str):
            raise ConfigError(
                "Checkpoint names must be strings when defined as a list"
            )
        checkpoint_dir = problem_path / checkpoint_name
        cfg_file = checkpoint_dir / "config.yaml"
        loaded_cfg: dict[str, Any] = {}
        if cfg_file.exists():
            loaded_cfg = yaml.safe_load(cfg_file.read_text()) or {}
            if not isinstance(loaded_cfg, dict):
                raise ConfigError(
                    f"Checkpoint config {cfg_file} must be a mapping"
                )
        else:
            logger.warning(
                "Checkpoint config file missing; using defaults",
                checkpoint=checkpoint_name,
                path=str(cfg_file),
            )
        normalized[checkpoint_name] = {
            "order": idx,
            "path": checkpoint_name,
            **loaded_cfg,
        }
    return normalized


def _normalize_checkpoints_config(
    problem_path: Path,
    checkpoints_cfg: list | dict | None,
) -> dict[str, dict[str, Any]]:
    """Normalize checkpoints config from list, dict, or None into a dict.

    Args:
        problem_path: Path to the problem directory.
        checkpoints_cfg: Checkpoints configuration in one of three formats:
            - list: List of checkpoint directory names
            - dict: Already normalized checkpoint configurations
            - None: No checkpoints defined

    Returns:
        Dict mapping checkpoint names to their raw configuration dicts.

    Raises:
        ConfigError: If checkpoints_cfg is not a valid type.
    """
    if isinstance(checkpoints_cfg, list):
        return _normalize_checkpoints_from_list(problem_path, checkpoints_cfg)
    if checkpoints_cfg is None:
        return {}
    if isinstance(checkpoints_cfg, dict):
        return checkpoints_cfg
    raise ConfigError("Checkpoints configuration must be a mapping or list.")


def _process_checkpoint(
    checkpoint_name: str,
    checkpoint_cfg: dict[str, Any],
    problem_path: Path,
    problem_defaults: dict[str, Any],
    normalized_checkpoints: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Process a single checkpoint: merge defaults, expand regressions, create groups.

    Args:
        checkpoint_name: Name of the checkpoint being processed.
        checkpoint_cfg: Raw checkpoint configuration dict.
        problem_path: Path to the problem directory.
        problem_defaults: Default values inherited from the problem config.
        normalized_checkpoints: Previously processed checkpoints (for regressions).

    Returns:
        Fully processed checkpoint configuration dict ready for CheckpointConfig.

    Raises:
        ConfigError: If checkpoint config is invalid or regression expansion fails.
    """
    if not isinstance(checkpoint_cfg, dict):
        raise ConfigError(
            "Checkpoint configuration must be a mapping of fields"
        )

    merged_cfg = nested_priority_merge(problem_defaults, checkpoint_cfg)

    # Resolve checkpoint path
    checkpoint_path = Path(merged_cfg.get("path", checkpoint_name))
    if not checkpoint_path.is_absolute():
        merged_cfg["path"] = problem_path / checkpoint_path
    merged_cfg.setdefault("groups", {})

    # Expand regressions if present
    regression_specs_raw = merged_cfg.get("regressions", [])
    if regression_specs_raw:
        try:
            regression_specs = [
                RegressionSpec(**spec) for spec in regression_specs_raw
            ]
            current_order = merged_cfg.get(
                "order", len(normalized_checkpoints) + 1
            )
            regression_groups = _expand_regressions(
                regression_specs,
                normalized_checkpoints,
                current_order,
            )
            # Check for collisions with existing groups
            for reg_name in regression_groups:
                if reg_name in merged_cfg["groups"]:
                    logger.warning(
                        "Regression group name collides with existing group",
                        checkpoint=checkpoint_name,
                        group=reg_name,
                    )
            merged_cfg["groups"].update(regression_groups)
        except Exception as e:
            raise ConfigError(
                f"Error expanding regressions for checkpoint "
                f"{checkpoint_name}: {e}"
            ) from e

    # Convert groups to GroupConfig instances
    merged_cfg["groups"] = {
        name: GroupConfig(name=name, **group_data)
        for name, group_data in merged_cfg["groups"].items()
    }

    # Populate case_order for manual regression groups from original group
    for group_name, group in merged_cfg["groups"].items():
        if (
            group.type == GroupType.REGRESSION
            and group.original_checkpoint is not None
            and group.original_group is not None
            and not group.case_order  # Empty list = falsy
        ):
            original_chkpt = normalized_checkpoints.get(
                group.original_checkpoint
            )
            if original_chkpt:
                original_groups = original_chkpt.get("groups", {})
                original_group_cfg = original_groups.get(group.original_group)
                if original_group_cfg:
                    if isinstance(original_group_cfg, GroupConfig):
                        group.case_order = original_group_cfg.case_order
                    else:
                        group.case_order = original_group_cfg.get(
                            "case_order", []
                        )

    # Set order if not already set
    merged_cfg["order"] = merged_cfg.get(
        "order", len(normalized_checkpoints) + 1
    )

    return merged_cfg


class CheckpointConfig(BaseConfig):
    """Configuration for a checkpoint within a problem.

    In the pytest-based harness, checkpoints are logical entities without
    physical directories. All checkpoint metadata is stored inline in the
    problem config.yaml, and test files live in tests/test_{checkpoint_name}.py.

    Attributes:
        name: Checkpoint identifier (e.g., "checkpoint_1", "checkpoint_2")
        version: Version number for the checkpoint tests (incremented when tests change)
        order: Ordering index when iterating checkpoints (1-indexed typically)
        state: Development state of the checkpoint
        spec_override: Optional in-memory specification override (used for testing)

    Inherits from BaseConfig:
        env: Environment variables for execution (dict[str, str])
        timeout: Execution timeout in seconds (int)

    Example:
        >>> config = CheckpointConfig(
        ...     name="checkpoint_1",
        ...     version=1,
        ...     order=1,
        ...     state="Core Tests",
        ...     timeout=30,
        ... )
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    # Core fields
    name: str = Field(description="Checkpoint identifier (e.g., 'checkpoint_1')")
    version: int = Field(
        description="Version number for checkpoint tests (incremented when tests change)"
    )
    order: int = Field(
        description="Ordering index used when iterating checkpoints (typically 1-indexed)"
    )
    state: Literal["Draft", "Core Tests", "Full Tests", "Verified"] = Field(
        default="Draft",
        description="Development state of the checkpoint",
    )
    spec_override: str | None = Field(
        default=None,
        description="Optional in-memory specification override (for testing)",
        exclude=True,  # Don't serialize this field
    )
    include_prior_tests: bool = Field(
        default=True,
        description="If True (default), include test files from prior checkpoints during evaluation. If False, only run tests for this checkpoint.",
    )


class ProblemConfig(BaseConfig):
    """Top-level problem definition that anchors checkpoints and metadata.

    The problem layer sets human-oriented context (names, tags, docs) and
    declares shared assets that every checkpoint inherits. Individual
    checkpoints can still override most execution knobs (e.g. timeouts) but
    rely on the problem to provide the entry point and static assets.

    Attributes:
        name: Human-friendly display name for the benchmark.
        version: Version number for the overall benchmark content.
        description: Short free-form summary of the problem.
        tags: Categories or filters used when selecting benchmarks.
        author: Optional author metadata for the problem.
        checkpoints: Ordered list of checkpoint directory names.
        design_doc: Filename for the design document stored alongside configs.
        submission_static_assets: Assets drawn from the submission tree and
            made available to every checkpoint.
    """

    name: str = Field(description="Human-friendly benchmark name.")
    path: Path = Field(description="Path to the problem directory.")
    version: int = Field(description="Version number of the problem tests.")
    description: str = Field(description="Short description of the problem.")
    tags: list[str] = Field(
        default_factory=list,
        min_length=1,
        description="Tags to categorize or filter the problem.",
    )
    author: str | None = Field(
        default=None,
        description="Author of the problem.",
    )

    category: str = Field(
        default="NOT_SET",
        description="Category of the problem.",
    )
    difficulty: Literal["Easy", "Medium", "Hard"] = Field(
        default="Easy", description="Difficulty of the problem."
    )
    inspiration: str | None = Field(
        default=None,
        description="Inspiration of the problem.",
    )
    checkpoints: dict[str, CheckpointConfig] = Field(
        description="Mapping of checkpoint name to configuration.",
    )
    design_doc: str = Field(
        default="design_doc.md",
        description="Filename of the problem design document.",
    )
    static_assets: dict[str, StaticAssetConfig] = Field(
        default_factory=dict,
        description=(
            "Named static assets referenced by cases without copying bytes."
        ),
    )
    entry_file: str = Field(
        description=(
            "Entry file required for executing checkpoints when not overridden."
        ),
    )
    markers: dict[str, MarkerConfig] = Field(
        default_factory=dict,
        description=(
            "Custom pytest markers beyond built-ins (error, functionality, regression). "
            "Each marker must specify a description and GroupType mapping."
        ),
    )
    test_dependencies: list[str] = Field(
        default_factory=list,
        description="Additional pytest dependencies for this problem's tests.",
    )

    @classmethod
    def from_yaml(cls, path: Path) -> ProblemConfig:
        """Load a problem configuration from a YAML file or directory.

        Args:
            path: Either a directory containing config.yaml or a direct path
                to the configuration file.

        Returns:
            Fully-initialized ProblemConfig with all checkpoints loaded.

        Raises:
            ConfigError: If the path or configuration is invalid.
        """
        logger.debug("Loading problem config", path=path)
        config_path = _resolve_problem_config_path(path)

        with config_path.open("r") as f:
            raw_cfg = yaml.safe_load(f)
        raw_cfg["path"] = path

        # Normalize checkpoints config from list/dict/None to dict
        checkpoints_cfg = _normalize_checkpoints_config(
            path, raw_cfg.get("checkpoints", {})
        )

        # Compute problem defaults for inheritance
        defaults_payload = {**raw_cfg, "checkpoints": {}}
        problem_defaults = cls(**defaults_payload).get_base_config()

        # Process each checkpoint (simplified for pytest-based harness)
        normalized_checkpoints: dict[str, CheckpointConfig] = {}
        for checkpoint_name, checkpoint_cfg in checkpoints_cfg.items():
            if not isinstance(checkpoint_cfg, dict):
                raise ConfigError(
                    f"Checkpoint '{checkpoint_name}' configuration must be a dict, "
                    f"got {type(checkpoint_cfg)}"
                )

            # Add checkpoint name to config
            checkpoint_cfg["name"] = checkpoint_name

            # Merge with problem defaults (env, timeout)
            checkpoint_cfg = nested_priority_merge(problem_defaults, checkpoint_cfg)

            # Set default order if not specified
            if "order" not in checkpoint_cfg:
                checkpoint_cfg["order"] = len(normalized_checkpoints) + 1

            # Validate and create CheckpointConfig
            normalized_checkpoints[checkpoint_name] = CheckpointConfig(
                **checkpoint_cfg
            )

        raw_cfg["checkpoints"] = normalized_checkpoints
        return cls(**raw_cfg)

    def load_checkpoint(self, checkpoint_name: str) -> CheckpointConfig:
        logger.debug(
            "Loading checkpoint config", path=self.path / checkpoint_name
        )
        try:
            return self.checkpoints[checkpoint_name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ConfigError(
                f"Checkpoint {checkpoint_name} not found in problem {self.name}"
            ) from exc

    def iterate_checkpoints(self) -> Generator[CheckpointConfig, None, None]:
        for _, checkpoint in self.iterate_checkpoint_items():
            yield checkpoint

    def iterate_checkpoint_items(
        self,
    ) -> Generator[tuple[str, CheckpointConfig], None, None]:
        ordered = sorted(
            self.checkpoints.items(), key=lambda item: (item[1].order, item[0])
        )
        for name, checkpoint in ordered:
            yield name, checkpoint

    def get_checkpoint_spec(self, checkpoint_name: str) -> str:
        """Get the specification text for a checkpoint.

        Specs are located at the problem root as {checkpoint_name}.md (e.g., checkpoint_1.md).
        If the checkpoint has a spec_override set (for testing), returns that instead.

        Args:
            checkpoint_name: Name of the checkpoint (e.g., "checkpoint_1")

        Returns:
            Specification text content

        Raises:
            KeyError: If checkpoint_name not in checkpoints
            FileNotFoundError: If spec file doesn't exist

        Example:
            >>> problem = ProblemConfig.from_yaml(Path("problems/example"))
            >>> spec = problem.get_checkpoint_spec("checkpoint_1")
            >>> print(spec[:50])  # First 50 chars
        """
        checkpoint = self.checkpoints[checkpoint_name]

        # Check for in-memory override first (used in testing)
        if checkpoint.spec_override is not None:
            return checkpoint.spec_override

        # Read from {checkpoint_name}.md at problem root
        spec_file = self.path / f"{checkpoint_name}.md"

        if not spec_file.exists():
            raise FileNotFoundError(
                f"Checkpoint spec not found: {spec_file}\n"
                f"Expected spec file at problem root: {checkpoint_name}.md"
            )

        return spec_file.read_text()


def get_available_problems(problems_path: Path) -> dict[str, ProblemConfig]:
    problems = {}
    logger.debug("Getting available problems", problems_path=str(problems_path))
    for problem_path in problems_path.iterdir():
        if not problem_path.is_dir():
            continue
        try:
            problem_config = ProblemConfig.from_yaml(problem_path)
        except Exception as e:
            logger.warning(
                "Error loading problem config",
                problem_path=str(problem_path),
                error=str(e),
            )
            continue
        problems[problem_config.name] = problem_config
    logger.debug("Found problems", problems=",".join(problems.keys()))
    return problems

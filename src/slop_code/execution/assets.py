"""Static asset configuration and resolution."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from slop_code.logging import get_logger

logger = get_logger(__name__)


class StaticAssetConfig(BaseModel):
    """Configuration describing a static asset available to checkpoints."""

    path: str = Field(
        description="Relative path to the asset within problem/checkpoint directory.",
    )
    save_path: str | None = Field(
        default=None,
        description=(
            "Relative path where the asset should be written inside the workspace. "
            "Defaults to the configured path if omitted."
        ),
    )

    @field_validator("path")
    @classmethod
    def _ensure_path_is_relative(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            raise ValueError("Static asset 'path' must be relative")
        return value

    @field_validator("save_path")
    @classmethod
    def _ensure_save_path_is_relative(cls, value: str | None) -> str | None:
        if value is None:
            return value

        path = Path(value)
        if path.is_absolute():
            raise ValueError("Static asset 'save_path' must be relative")
        if ".." in path.parts:
            raise ValueError("Static asset 'save_path' cannot traverse upwards")
        return value

    def resolve(self, *, base_path: Path, name: str) -> ResolvedStaticAsset:
        """Resolve the asset against ``base_path``.

        Args:
            base_path: Directory relative to which the asset path is defined.
            name: Asset name used in configuration.

        Returns:
            A :class:`ResolvedStaticAsset` containing absolute and workspace paths.
        """
        absolute_path = (base_path / self.path).resolve()
        save_path = (
            Path(self.save_path)
            if self.save_path is not None
            else Path(self.path)
        )
        logger.debug(
            "Resolving static asset",
            name=name,
            path=self.path,
            save_path=save_path,
            absolute_path=absolute_path,
            verbose=True,
        )
        return ResolvedStaticAsset(
            name=name,
            absolute_path=absolute_path,
            save_path=save_path,
        )


class ResolvedStaticAsset(BaseModel):
    """Fully resolved static asset with absolute and workspace-relative paths."""

    name: str
    absolute_path: Path
    save_path: Path

    @field_validator("absolute_path")
    @classmethod
    def _ensure_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError(
                "Resolved static asset 'absolute_path' must be absolute"
            )
        return value

    @field_validator("save_path")
    @classmethod
    def _ensure_save_path_relative(cls, value: Path) -> Path:
        if value.is_absolute():
            raise ValueError(
                "Resolved static asset 'save_path' must be relative"
            )
        if ".." in value.parts:
            raise ValueError(
                "Resolved static asset 'save_path' cannot traverse upwards"
            )
        return value

    @property
    def save_path_str(self) -> str:
        """Return the workspace-relative save path as a POSIX string."""
        return self.save_path.as_posix()

    def workspace_path(self, workspace_root: Path) -> Path:
        """Return the location inside ``workspace_root`` where the asset should live.

        Args:
            workspace_root: Root directory of the workspace

        Returns:
            Full path to where the asset should be placed in the workspace
        """
        return workspace_root / self.save_path


def resolve_static_assets(
    base_path: Path,
    assets: dict[str, dict[str, StaticAssetConfig]]
    | dict[str, StaticAssetConfig],
    ordering: list[str] | None = None,
) -> dict[str, ResolvedStaticAsset]:
    """Resolve configured assets relative to ``base_path``.

    Args:
        base_path: Directory serving as the reference point for paths.
        assets: List of mappings of asset name to configuration, or flat mapping.
        ordering: List of asset group names in preference order (later wins).

    Returns:
        Mapping of asset name to resolved asset metadata.
    """
    logger.debug(
        "Resolving static assets",
        base_path=base_path,
        assets=list(assets.keys()) if assets else [],
        ordering=ordering,
        verbose=True,
    )

    resolved: dict[str, ResolvedStaticAsset] = {}

    # If assets is a flat dict (old style), resolve directly
    if assets and not ordering:
        if isinstance(next(iter(assets.values())), StaticAssetConfig):
            logger.debug(
                "Resolving flat asset configuration",
                num_assets=len(assets),
                verbose=True,
            )
            for name, asset_cfg in assets.items():  # type: ignore[union-attr]
                resolved[name] = asset_cfg.resolve(
                    base_path=base_path, name=name
                )
            return resolved

    # Otherwise, resolve according to ordering
    if ordering:
        logger.debug(
            "Resolving ordered asset configuration",
            num_groups=len(ordering),
            verbose=True,
        )
        for key in ordering:
            asset_group = assets.get(key, {})  # type: ignore[union-attr]
            if not asset_group:
                logger.debug(
                    "Skipping empty asset group",
                    group=key,
                    verbose=True,
                )
                continue
            logger.debug(
                "Resolving asset group",
                group=key,
                num_assets=len(asset_group),
                verbose=True,
            )
            for name, asset_cfg in asset_group.items():
                resolved[name] = asset_cfg.resolve(
                    base_path=base_path, name=name
                )

    logger.debug(
        "Resolved static assets",
        base_path=base_path,
        assets=list(resolved.keys()),
        num_resolved=len(resolved),
        verbose=True,
    )
    return resolved

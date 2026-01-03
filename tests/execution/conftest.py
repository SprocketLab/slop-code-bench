from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.local_streaming import LocalEnvironmentSpec
from slop_code.execution.models import CommandConfig
from slop_code.execution.session import Session
from slop_code.execution.snapshot import Snapshot
from slop_code.execution.workspace import Workspace


@pytest.fixture
def local_environment_spec() -> LocalEnvironmentSpec:
    """Create a basic environment spec for testing."""
    return LocalEnvironmentSpec(
        type="local",
        name="test",
        commands=CommandConfig(command="python"),
    )


@pytest.fixture
def temp_snapshot_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for snapshots."""
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    return snapshot_dir


@pytest.fixture
def snapshot_fn(temp_snapshot_dir: Path) -> Callable[[Path], Snapshot]:
    """Create a snapshot function for testing."""

    def snapshot_fn(cwd: Path) -> Snapshot:
        return Snapshot.from_directory(
            cwd=cwd,
            env={},
            compression="gz",
            save_path=temp_snapshot_dir,
            ignore_globs={"*.bin"},
        )

    return snapshot_fn


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file1.txt").write_text("content 1", encoding="utf-8")
    (source_dir / "file2.txt").write_text("content 2", encoding="utf-8")
    subdir = source_dir / "subdir"
    subdir.mkdir()
    (subdir / "nested.txt").write_text("nested content", encoding="utf-8")
    (subdir / "binary.bin").write_bytes(b"binary content")
    return source_dir


@pytest.fixture
def initial_snapshot(
    source_dir: Path,
    snapshot_fn: Callable[[Path], Snapshot],
) -> Snapshot:
    """Create an initial snapshot for testing."""
    return snapshot_fn(source_dir)


@pytest.fixture
def static_assets_dir(tmp_path: Path) -> Path:
    """Create static assets for testing."""
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "README.md").write_text("# Instructions", encoding="utf-8")
    (assets / "config.json").write_text('{"key": "value"}', encoding="utf-8")
    return assets


@pytest.fixture
def resolved_static_assets(
    static_assets_dir: Path,
) -> dict[str, ResolvedStaticAsset]:
    """Create resolved static assets."""
    return {
        "readme": ResolvedStaticAsset(
            name="readme",
            absolute_path=static_assets_dir / "README.md",
            save_path=Path("README.md"),
        ),
        "config": ResolvedStaticAsset(
            name="config",
            absolute_path=static_assets_dir / "config.json",
            save_path=Path("config.json"),
        ),
    }


@pytest.fixture
def resolved_directory_asset(
    static_assets_dir: Path,
) -> dict[str, ResolvedStaticAsset]:
    """Create a resolved static asset that is a directory."""
    dataset_dir = static_assets_dir / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "data.csv").write_text("value1,value2", encoding="utf-8")
    nested_dir = dataset_dir / "nested"
    nested_dir.mkdir()
    (nested_dir / "extra.txt").write_text("extra data", encoding="utf-8")

    return {
        "dataset": ResolvedStaticAsset(
            name="dataset",
            absolute_path=dataset_dir,
            save_path=Path("static/data"),
        )
    }


@pytest.fixture
def workspace(
    initial_snapshot: Snapshot,
    resolved_static_assets: dict[str, ResolvedStaticAsset],
    snapshot_fn: Callable[[Path], Snapshot],
) -> Workspace:
    return Workspace(
        initial_snapshot=initial_snapshot,
        snapshot_fn=snapshot_fn,
        static_assets=resolved_static_assets,
        is_agent_infer=False,
    )


@pytest.fixture(params=[True, False], ids=["agent_infer", "not_agent_infer"])
def modified_workspace(
    workspace: Workspace,
    request: pytest.FixtureRequest,
    resolved_static_assets: dict[str, ResolvedStaticAsset],
    initial_snapshot: Snapshot,
    source_dir: Path,
) -> tuple[Workspace, dict[Path, str | None]]:
    workspace._is_agent_infer = request.param
    workspace.prepare()
    (workspace.working_dir / "new_file.txt").write_text("new content")

    initial_files = {}
    for f in initial_snapshot.matched_paths:
        if f.is_dir():
            continue
        initial_files[f] = (source_dir / f).read_text()
    if request.param:
        for f in resolved_static_assets.values():
            for sub_file in f.absolute_path.rglob("*"):
                init_file = f.save_path / sub_file.relative_to(f.absolute_path)
                if not init_file.is_dir():
                    initial_files[init_file] = sub_file.read_text()
                else:
                    initial_files[init_file] = None

    return workspace, initial_files


@pytest.fixture(params=[True, False], ids=["agent_infer", "not_agent_infer"])
def session(
    local_environment_spec: LocalEnvironmentSpec,
    workspace: Workspace,
    resolved_static_assets: dict[str, ResolvedStaticAsset],
    request: pytest.FixtureRequest,
) -> Session:
    return Session(
        spec=local_environment_spec,
        workspace=workspace,
        static_assets=resolved_static_assets,
        is_agent_infer=request.param,
    )

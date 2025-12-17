"""Unit tests for the Workspace class."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.snapshot import Snapshot
from slop_code.execution.workspace import Workspace
from slop_code.execution.workspace import WorkspaceError


class TestWorkspace:
    """Tests for workspace prepare functionality."""

    def test_init_with_snapshot(
        self,
        workspace: Workspace,
        initial_snapshot: Snapshot,
        resolved_static_assets: dict[str, ResolvedStaticAsset],
        snapshot_fn: Callable[[Path], Snapshot],
    ):
        """Test initialization with a snapshot."""
        workspace = Workspace(
            initial_snapshot=initial_snapshot,
            snapshot_fn=snapshot_fn,
            static_assets=resolved_static_assets,
            is_agent_infer=False,
        )
        assert workspace._initial_snapshot == initial_snapshot
        assert workspace._static_assets == resolved_static_assets
        assert workspace._temp_dir is None

    def test_prepare_creates_temp_dir(self, workspace: Workspace):
        """Test that prepare creates a temporary directory."""
        try:
            workspace.prepare()
            assert workspace._temp_dir is not None  # noqa: SLF001
            assert workspace.working_dir.exists()
            assert workspace.working_dir.is_dir()
        finally:
            workspace.cleanup()

    def test_prepare_extracts_snapshot(
        self,
        workspace: Workspace,
        source_dir: Path,
        initial_snapshot: Snapshot,
    ):
        try:
            workspace.prepare()
            working_dir = workspace.working_dir
            for f in initial_snapshot.matched_paths:
                assert (working_dir / f).exists(), f"File {f} does not exist"
                assert (working_dir / f).read_text() == (
                    source_dir / f
                ).read_text(), f"File {f} has incorrect content"

        finally:
            workspace.cleanup()

    def test_prepare_not_agent_infer(
        self,
        workspace: Workspace,
        resolved_static_assets: dict[str, ResolvedStaticAsset],
    ):
        workspace._is_agent_infer = False
        try:
            workspace.prepare()
            working_dir = workspace.working_dir
            for f in resolved_static_assets.values():
                assert not (working_dir / f.save_path).exists(), (
                    f"File {f.save_path} exists"
                )

        finally:
            workspace.cleanup()

    def test_prepare_agent_infer(
        self,
        workspace: Workspace,
        resolved_static_assets: dict[str, ResolvedStaticAsset],
    ):
        """Test that prepare copies static assets to working directory."""
        workspace._is_agent_infer = True
        try:
            workspace.prepare()
            working_dir = workspace.working_dir
            for f in resolved_static_assets.values():
                assert (working_dir / f.save_path).exists(), (
                    f"File {f.save_path} does not exist"
                )
                assert (
                    working_dir / f.save_path
                ).read_text() == f.absolute_path.read_text(), (
                    f"File {f.save_path} has incorrect content"
                )
        finally:
            workspace.cleanup()

    def test_prepare_agent_infer_directory_asset(
        self,
        workspace: Workspace,
        resolved_directory_asset: dict[str, ResolvedStaticAsset],
    ):
        """Test that prepare copies static assets to working directory."""
        workspace._is_agent_infer = True
        workspace._static_assets = resolved_directory_asset
        try:
            workspace.prepare()
            working_dir = workspace.working_dir
            for f in resolved_directory_asset.values():
                for sub_file in f.absolute_path.rglob("*"):
                    actual_path = f.save_path / sub_file.relative_to(
                        f.absolute_path
                    )
                    assert (working_dir / actual_path).exists(), (
                        f"File {actual_path} does not exist"
                    )

                    if sub_file.is_dir():
                        continue
                    assert (
                        working_dir / actual_path
                    ).read_text() == sub_file.read_text(), (
                        f"File {actual_path} has incorrect content"
                    )

        finally:
            workspace.cleanup()

    def test_prepare_twice_raises_error(self, workspace: Workspace):
        """Test that calling prepare twice raises an error."""
        try:
            workspace.prepare()
            with pytest.raises(WorkspaceError, match="already prepared"):
                workspace.prepare()
        finally:
            workspace.cleanup()

    def test_working_dir_before_prepare_raises(self, workspace: Workspace):
        """Test that accessing working_dir before prepare raises error."""
        with pytest.raises(WorkspaceError, match="not prepared"):
            _ = workspace.working_dir

    def test_cleanup_removes_temp_dir(self, workspace: Workspace):
        """Test that cleanup removes the temporary directory."""
        workspace.prepare()
        working_dir = workspace.working_dir

        workspace.cleanup()

        assert not working_dir.exists()
        assert workspace._temp_dir is None  # noqa: SLF001

    def test_cleanup_without_prepare(self, workspace: Workspace):
        """Test that cleanup without prepare does not raise."""
        # Should not raise
        workspace.cleanup()

    def test_cleanup_twice(self, workspace: Workspace):
        """Test that calling cleanup twice does not raise."""
        workspace.prepare()
        workspace.cleanup()
        # Should not raise
        workspace.cleanup()

    def test_reset_recreates_workspace_new_files(
        self, modified_workspace: tuple[Workspace, dict[Path, str]]
    ):
        """Test that reset recreates the workspace from initial snapshot."""
        workspace, initial_files = modified_workspace
        try:
            workspace.reset()
            assert not (workspace.working_dir / "new_file.txt").exists(), (
                "New file exists"
            )
            for f, expected in initial_files.items():
                assert (workspace.working_dir / f).exists(), f"File {f} exists"
                if f.is_file():
                    assert (
                        workspace.working_dir / f
                    ).read_text() == expected, f"File {f} has incorrect content"

        finally:
            workspace.cleanup()

    def test_reset_recreates_workspace_deleted_files(
        self, modified_workspace: tuple[Workspace, dict[Path, str]]
    ):
        """Test that reset recreates the workspace from initial snapshot."""
        workspace, initial_files = modified_workspace
        (workspace.working_dir / "file1.txt").unlink()
        try:
            workspace.reset()
            for f, expected in initial_files.items():
                assert (workspace.working_dir / f).exists(), f"File {f} exists"
                if f.is_file():
                    assert (
                        workspace.working_dir / f
                    ).read_text() == expected, f"File {f} has incorrect content"

        finally:
            workspace.cleanup()

    def test_reset_recreates_workspace_modified_files(
        self, modified_workspace: tuple[Workspace, dict[Path, str]]
    ):
        """Test that reset recreates the workspace from initial snapshot."""
        workspace, initial_files = modified_workspace
        (workspace.working_dir / "file1.txt").write_text("modified content")
        try:
            workspace.reset()
            for f, expected in initial_files.items():
                assert (workspace.working_dir / f).exists(), f"File {f} exists"
                if f.is_file():
                    assert (
                        workspace.working_dir / f
                    ).read_text() == expected, f"File {f} has incorrect content"

        finally:
            workspace.cleanup()

    def test_reset_before_prepare_raises(self, workspace: Workspace):
        """Test that reset before prepare raises error."""
        with pytest.raises(WorkspaceError, match="not prepared"):
            workspace.reset()

    def test_get_file_contents_reads_text_files(self, workspace: Workspace):
        """Test that get_file_contents reads text files correctly."""
        try:
            workspace.prepare()
            (workspace.working_dir / "output1.txt").write_text(
                "output 1", encoding="utf-8"
            )
            (workspace.working_dir / "output2.txt").write_text(
                "output 2", encoding="utf-8"
            )

            contents = workspace.get_file_contents(
                ["output1.txt", "output2.txt"]
            )

            assert contents == {
                "output1.txt": "output 1",
                "output2.txt": "output 2",
            }
        finally:
            workspace.cleanup()

    def test_get_file_contents_reads_binary_files(self, workspace: Workspace):
        """Test that get_file_contents falls back to bytes for invalid UTF-8."""
        try:
            workspace.prepare()
            # Use binary data that will cause UnicodeDecodeError
            binary_data = b"\x80\x81\x82\x83\x84"
            (workspace.working_dir / "binary.bin").write_bytes(binary_data)

            contents = workspace.get_file_contents(["binary.bin"])

            assert contents == {"binary.bin": binary_data}
        finally:
            workspace.cleanup()

    def test_get_file_contents_skips_missing_files(self, workspace: Workspace):
        """Test that get_file_contents skips missing files."""
        try:
            workspace.prepare()
            (workspace.working_dir / "exists.txt").write_text("content")

            contents = workspace.get_file_contents(
                ["exists.txt", "missing.txt", "also_missing.txt"]
            )

            assert contents == {"exists.txt": "content"}
        finally:
            workspace.cleanup()

    def test_get_file_contents_with_nested_paths(self, workspace: Workspace):
        """Test that get_file_contents works with nested paths."""
        try:
            workspace.prepare()
            nested_dir = workspace.working_dir / "output" / "nested"
            nested_dir.mkdir(parents=True)
            (nested_dir / "file.txt").write_text("nested output")

            contents = workspace.get_file_contents(["output/nested/file.txt"])

            assert contents == {"output/nested/file.txt": "nested output"}
        finally:
            workspace.cleanup()

    def test_get_file_contents_expands_glob_patterns(self, workspace: Workspace):
        """Test that get_file_contents expands glob patterns."""
        try:
            workspace.prepare()
            reports_day1 = workspace.working_dir / "reports" / "day1"
            reports_day2 = workspace.working_dir / "reports" / "day2"
            logs_nested = workspace.working_dir / "logs" / "nested"
            reports_day1.mkdir(parents=True)
            reports_day2.mkdir(parents=True)
            logs_nested.mkdir(parents=True)

            (reports_day1 / "summary.txt").write_text("day1 summary")
            (reports_day2 / "summary.txt").write_text("day2 summary")
            (logs_nested / "trace.json").write_text('{"trace": true}')
            (logs_nested / "trace.txt").write_text("ignored")

            contents = workspace.get_file_contents(
                [
                    "reports/**/*.txt",
                    "reports/day1/*.txt",
                    "logs/**/*.json",
                ]
            )

            assert contents == {
                "reports/day1/summary.txt": "day1 summary",
                "reports/day2/summary.txt": "day2 summary",
                "logs/nested/trace.json": '{"trace": true}',
            }
        finally:
            workspace.cleanup()

    def test_get_file_contents_handles_directories(self, workspace: Workspace):
        """Test that get_file_contents recursively collects files from directories."""
        try:
            workspace.prepare()
            test_dir = workspace.working_dir / "dir"
            test_dir.mkdir()
            (test_dir / "file1.txt").write_text("content1")
            (test_dir / "file2.txt").write_text("content2")
            nested_dir = test_dir / "nested"
            nested_dir.mkdir()
            (nested_dir / "file3.txt").write_text("content3")

            contents = workspace.get_file_contents(["dir"])

            assert contents == {
                "dir/file1.txt": "content1",
                "dir/file2.txt": "content2",
                "dir/nested/file3.txt": "content3",
            }
        finally:
            workspace.cleanup()

    def test_get_file_contents_directory_skips_symlinks(
        self, workspace: Workspace
    ):
        """Test that symlinks within directories are skipped."""
        try:
            workspace.prepare()
            test_dir = workspace.working_dir / "dir"
            test_dir.mkdir()
            (test_dir / "real_file.txt").write_text("real content")
            # Create a symlink to the real file
            symlink_path = test_dir / "symlink.txt"
            symlink_path.symlink_to(test_dir / "real_file.txt")

            contents = workspace.get_file_contents(["dir"])

            # Should only contain the real file, not the symlink
            assert contents == {"dir/real_file.txt": "real content"}
        finally:
            workspace.cleanup()

    def test_get_file_contents_directory_mixed_file_types(
        self, workspace: Workspace
    ):
        """Test directory tracking with mix of text and binary files."""
        try:
            workspace.prepare()
            test_dir = workspace.working_dir / "mixed"
            test_dir.mkdir()
            (test_dir / "text.txt").write_text("text content")
            binary_data = b"\x80\x81\x82\x83"
            (test_dir / "binary.bin").write_bytes(binary_data)

            contents = workspace.get_file_contents(["mixed"])

            assert contents == {
                "mixed/text.txt": "text content",
                "mixed/binary.bin": binary_data,
            }
        finally:
            workspace.cleanup()

    def test_get_file_contents_directory_with_globs(
        self, workspace: Workspace
    ):
        """Test that directories and glob patterns work together."""
        try:
            workspace.prepare()
            # Create directory structure
            dir1 = workspace.working_dir / "tracked_dir"
            dir1.mkdir()
            (dir1 / "a.txt").write_text("dir a")
            (dir1 / "b.txt").write_text("dir b")
            (workspace.working_dir / "root.log").write_text("root log")

            # Mix directory paths and glob patterns
            contents = workspace.get_file_contents(["tracked_dir", "*.log"])

            assert contents == {
                "tracked_dir/a.txt": "dir a",
                "tracked_dir/b.txt": "dir b",
                "root.log": "root log",
            }
        finally:
            workspace.cleanup()

    def test_get_file_contents_empty_directory_skipped(
        self, workspace: Workspace
    ):
        """Test that empty directories produce no entries."""
        try:
            workspace.prepare()
            empty_dir = workspace.working_dir / "empty"
            empty_dir.mkdir()

            contents = workspace.get_file_contents(["empty"])

            assert contents == {}
        finally:
            workspace.cleanup()

    def test_get_file_contents_empty_list(self, workspace: Workspace):
        """Test that get_file_contents handles empty list."""
        try:
            workspace.prepare()
            contents = workspace.get_file_contents([])
            assert contents == {}
        finally:
            workspace.cleanup()

    def test_context_manager_prepare_and_cleanup(self, workspace: Workspace):
        """Test that context manager calls prepare and cleanup."""
        assert workspace._temp_dir is None  # noqa: SLF001

        with workspace as ws:
            assert ws is workspace
            assert workspace._temp_dir is not None  # noqa: SLF001
            working_dir = workspace.working_dir
            assert working_dir.exists()

        # After exiting, should be cleaned up
        assert workspace._temp_dir is None  # noqa: SLF001
        assert not working_dir.exists()

    def test_context_manager_cleanup_on_exception(self, workspace: Workspace):
        """Test that context manager cleans up even on exception."""
        with pytest.raises(ValueError), workspace:
            working_dir = workspace.working_dir
            raise ValueError("test error")

        # Should still be cleaned up
        assert workspace._temp_dir is None  # noqa: SLF001
        assert not working_dir.exists()

    def test_workspace_with_empty_snapshot(
        self,
        tmp_path: Path,
        temp_snapshot_dir: Path,
        snapshot_fn: Callable[[Path], Snapshot],
    ):
        """Test workspace with an empty snapshot."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        snapshot = Snapshot.from_directory(
            cwd=empty_dir,
            env={},
            compression="gz",
            save_path=temp_snapshot_dir,
        )

        workspace = Workspace(
            initial_snapshot=snapshot, snapshot_fn=snapshot_fn
        )
        try:
            workspace.prepare()
            # Should work without errors
            assert workspace.working_dir.exists()
            # Directory should be empty (except for potential hidden files)
            files = list(workspace.working_dir.iterdir())
            assert len(files) == 0
        finally:
            workspace.cleanup()

    def test_get_file_contents_unicode_decode_error_fallback(
        self, workspace: Workspace
    ):
        """Test that binary files fall back to bytes when unicode decode fails."""
        try:
            workspace.prepare()
            # Create a file with invalid UTF-8
            invalid_utf8 = b"\x80\x81\x82"
            (workspace.working_dir / "invalid.txt").write_bytes(invalid_utf8)

            contents = workspace.get_file_contents(["invalid.txt"])

            # Should return as bytes since UTF-8 decode failed
            assert contents == {"invalid.txt": invalid_utf8}
        finally:
            workspace.cleanup()

"""Unit tests for the Session class."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from slop_code.execution.assets import ResolvedStaticAsset
from slop_code.execution.file_ops import FileType
from slop_code.execution.file_ops import InputFile
from slop_code.execution.local_streaming import LocalEnvironmentSpec
from slop_code.execution.protocols import StreamingRuntime
from slop_code.execution.session import Session
from slop_code.execution.workspace import Workspace


class TestSessionInitialization:
    """Tests for Session initialization."""

    def test_init_basic(
        self,
        session: Session,
        local_environment_spec: LocalEnvironmentSpec,
        workspace: Workspace,
        resolved_static_assets: dict[str, ResolvedStaticAsset],
    ):
        """Test basic Session initialization."""
        assert session.spec == local_environment_spec
        assert session.workspace == workspace
        assert session.static_assets == resolved_static_assets
        assert session._streaming_runtimes == []
        assert session._exec_runtimes == []

    def test_prepare_calls_workspace_prepare(self, session: Session):
        """Test that prepare calls workspace.prepare()."""
        with patch.object(session.workspace, "prepare") as mock_prepare:
            session.prepare()
            mock_prepare.assert_called_once()

    def test_prepare_integration(
        self,
        session: Session,
        workspace: Workspace,
    ):
        """Test prepare integration with real workspace."""
        try:
            session.prepare()
            # Verify workspace is prepared
            assert workspace.working_dir.exists()
        finally:
            session.cleanup()

    def test_cleanup_calls_workspace_cleanup(self, session: Session):
        """Test that cleanup calls workspace.cleanup()."""
        with patch.object(session.workspace, "cleanup") as mock_cleanup:
            session.cleanup()
            mock_cleanup.assert_called_once()

    def test_cleanup_calls_runtime_cleanup(
        self,
        session: Session,
    ):
        """Test that cleanup calls cleanup on all runtimes."""
        # Create mock runtimes
        mock_runtime1 = Mock(spec=StreamingRuntime)
        mock_runtime2 = Mock(spec=StreamingRuntime)
        session._streaming_runtimes = [mock_runtime1, mock_runtime2]  # noqa: SLF001

        with patch.object(session.workspace, "cleanup"):
            session.cleanup()
            mock_runtime1.cleanup.assert_called_once()
            mock_runtime2.cleanup.assert_called_once()

    def test_cleanup_integration(self, session: Session, workspace: Workspace):
        """Test cleanup integration with real workspace."""
        session.prepare()
        working_dir = workspace.working_dir

        session.cleanup()

        assert not working_dir.exists()

    def test_reset_calls_workspace_reset(
        self, session: Session, workspace: Workspace
    ):
        """Test that reset calls workspace.reset()."""
        with patch.object(session.workspace, "reset") as mock_reset:
            session.reset()
            mock_reset.assert_called_once()

    def test_reset_integration(self, session: Session, workspace: Workspace):
        """Test reset integration with real workspace."""
        try:
            session.prepare()

            # Modify workspace
            (workspace.working_dir / "new_file.txt").write_text("new")
            (workspace.working_dir / "file1.txt").unlink()

            # Reset
            session.reset()

            # Verify reset
            assert not (workspace.working_dir / "new_file.txt").exists()
            assert (workspace.working_dir / "file1.txt").exists()
        finally:
            session.cleanup()

    def test_working_dir_returns_workspace_working_dir(
        self, session: Session, workspace: Workspace
    ):
        """Test that working_dir returns workspace.working_dir."""
        try:
            session.prepare()
            assert session.working_dir == workspace.working_dir
        finally:
            session.cleanup()

    @patch("slop_code.execution.session.spawn_streaming_runtime")
    def test_spawn_creates_launch_spec(
        self,
        mock_spawn_streaming_runtime: Mock,
        session: Session,
        workspace: Workspace,
        resolved_static_assets: dict[str, ResolvedStaticAsset],
    ):
        """Test that spawn creates correct LaunchSpec."""
        # Setup mock
        mock_runtime = Mock(spec=StreamingRuntime)
        mock_spawn_streaming_runtime.return_value = mock_runtime

        try:
            session.prepare()
            runtime = session.spawn()

            # Verify spawn_streaming_runtime was called with correct arguments
            mock_spawn_streaming_runtime.assert_called_once()
            call_kwargs = mock_spawn_streaming_runtime.call_args[1]
            assert call_kwargs["environment"] == session.spec
            assert call_kwargs["working_dir"] == workspace.working_dir
            assert call_kwargs["static_assets"] == resolved_static_assets
            assert call_kwargs["is_evaluation"] == (not session.is_agent_infer)
            assert call_kwargs["ports"] == {}
            assert call_kwargs["mounts"] == {}
            assert call_kwargs["env_vars"] == {}
            assert call_kwargs["setup_command"] is None

            # Verify runtime was added to runtimes list
            assert runtime == mock_runtime
            assert session._streaming_runtimes == [mock_runtime]
        finally:
            session.cleanup()

    @patch("slop_code.execution.session.spawn_streaming_runtime")
    def test_spawn_multiple_runtimes(
        self,
        mock_spawn_streaming_runtime: Mock,
        session: Session,
    ):
        """Test spawning multiple runtimes."""
        # Setup mocks
        mock_runtime1 = Mock(spec=StreamingRuntime)
        mock_runtime2 = Mock(spec=StreamingRuntime)
        mock_spawn_streaming_runtime.side_effect = [mock_runtime1, mock_runtime2]

        try:
            session.prepare()
            runtime1 = session.spawn()
            runtime2 = session.spawn()

            assert runtime1 == mock_runtime1
            assert runtime2 == mock_runtime2
            assert session._streaming_runtimes == [mock_runtime1, mock_runtime2]
            assert mock_spawn_streaming_runtime.call_count == 2
        finally:
            session.cleanup()

    @patch("slop_code.execution.session.materialize_input_files")
    def test_materialize_input_files_calls_function(
        self,
        mock_materialize: Mock,
        session: Session,
        workspace: Workspace,
    ):
        """Test that materialize_input_files calls the file_ops function."""
        try:
            session.prepare()

            files = [
                InputFile(
                    path=Path("test.txt"),
                    content="test content",
                    file_type=FileType.TEXT,
                )
            ]
            session.materialize_input_files(files)

            mock_materialize.assert_called_once_with(
                files, workspace.working_dir
            )
        finally:
            session.cleanup()

    def test_materialize_input_files_integration(
        self, session: Session, workspace: Workspace
    ):
        """Test materialize_input_files integration."""
        try:
            session.prepare()

            files = [
                InputFile(
                    path=Path("test.txt"),
                    content="test content",
                    file_type=FileType.TEXT,
                )
            ]
            session.materialize_input_files(files)

            # Verify file was created
            assert (workspace.working_dir / "test.txt").exists()
            assert (
                workspace.working_dir / "test.txt"
            ).read_text() == "test content"
        finally:
            session.cleanup()

    def test_get_file_contents_delegates_to_workspace(
        self, session: Session, workspace: Workspace
    ):
        """Test that get_file_contents delegates to workspace."""
        files = ["file1.txt", "file2.txt"]
        expected = {"file1.txt": "content1", "file2.txt": "content2"}

        with patch.object(
            workspace, "get_file_contents", return_value=expected
        ) as mock_get:
            result = session.get_file_contents(files)

            mock_get.assert_called_once_with(files)
            assert result == expected

    def test_get_file_contents_integration(
        self, session: Session, workspace: Workspace
    ):
        """Test get_file_contents integration."""
        try:
            session.prepare()

            # Add test files
            (workspace.working_dir / "output.txt").write_text("output content")

            contents = session.get_file_contents(["output.txt"])

            assert contents == {"output.txt": "output content"}
        finally:
            session.cleanup()

    @patch("slop_code.execution.session.resolve_static_placeholders")
    def test_resolve_static_placeholders_without_assets(
        self,
        mock_resolve: Mock,
        session: Session,
        resolved_static_assets: dict[str, ResolvedStaticAsset],
    ):
        """Test resolve_static_placeholders without static assets."""
        data = {"key": "{{static:asset}}"}
        expected = {"key": "/path/to/asset"}
        mock_resolve.return_value = expected

        result = session.resolve_static_placeholders(data)

        mock_resolve.assert_called_once_with(
            data, resolved_static_assets, is_docker=False
        )
        assert result == expected

    @patch("slop_code.execution.session.resolve_static_placeholders")
    def test_resolve_static_placeholders_with_assets(
        self,
        mock_resolve: Mock,
        session: Session,
        resolved_static_assets: dict[str, ResolvedStaticAsset],
    ):
        """Test resolve_static_placeholders with static assets."""
        data = {"key": "{{static:readme}}"}
        expected = {"key": str(resolved_static_assets["readme"].absolute_path)}
        mock_resolve.return_value = expected

        result = session.resolve_static_placeholders(data)

        mock_resolve.assert_called_once_with(
            data, resolved_static_assets, is_docker=False
        )
        assert result == expected

    def test_context_manager_calls_prepare_and_cleanup(
        self, session: Session, workspace: Workspace
    ):
        """Test that context manager calls prepare and cleanup."""
        with session as s:
            assert s is session
            assert workspace.working_dir.exists()
            working_dir = workspace.working_dir

        # After exiting, should be cleaned up
        assert not working_dir.exists()

    def test_context_manager_cleanup_on_exception(
        self, session: Session, workspace: Workspace
    ):
        """Test that context manager cleans up on exception."""
        with pytest.raises(ValueError), session:
            raise ValueError("test error")

        # Should still be cleaned up - workspace should be None after exception
        assert workspace._temp_dir is None

    def test_spawn_without_prepare(
        self, session: Session, workspace: Workspace
    ):
        """Test that spawn works without explicit prepare."""
        try:
            # Prepare workspace manually
            workspace.prepare()

            with patch(
                "slop_code.execution.session.spawn_streaming_runtime"
            ) as mock_spawn:
                mock_runtime = Mock(spec=StreamingRuntime)
                mock_spawn.return_value = mock_runtime

                runtime = session.spawn()
                assert runtime == mock_runtime
        finally:
            session.cleanup()

    def test_cleanup_with_no_runtimes(
        self, session: Session, workspace: Workspace
    ):
        """Test cleanup with no runtimes."""
        with patch.object(session.workspace, "cleanup") as mock_cleanup:
            session.cleanup()
            mock_cleanup.assert_called_once()

    def test_multiple_prepare_calls(self, session: Session):
        """Test behavior with multiple prepare calls."""
        try:
            session.prepare()
            # Second prepare should raise from workspace
            with pytest.raises(Exception):  # WorkspaceError
                session.prepare()
        finally:
            session.cleanup()

    @patch("slop_code.execution.session.spawn_streaming_runtime")
    def test_spawn_with_parameters(
        self,
        mock_spawn_streaming_runtime: Mock,
        session: Session,
        workspace: Workspace,
    ):
        """Test that spawn passes parameters correctly to LaunchSpec."""
        # Setup mock
        mock_runtime = Mock(spec=StreamingRuntime)
        mock_spawn_streaming_runtime.return_value = mock_runtime

        ports = {8080: 8081}
        mounts: dict[str, dict[str, str] | str] = {
            "/host/path": "/container/path"
        }
        env_vars = {"TEST_VAR": "test_value"}
        setup_command = "echo custom setup"

        try:
            session.prepare()
            runtime = session.spawn(
                ports=ports,
                mounts=mounts,
                env_vars=env_vars,
                setup_command=setup_command,
            )

            # Verify spawn_streaming_runtime was called with correct arguments
            mock_spawn_streaming_runtime.assert_called_once()
            call_kwargs = mock_spawn_streaming_runtime.call_args[1]
            assert call_kwargs["environment"] == session.spec
            assert call_kwargs["working_dir"] == workspace.working_dir
            assert call_kwargs["ports"] == ports
            assert call_kwargs["mounts"] == mounts
            assert call_kwargs["env_vars"] == env_vars
            assert call_kwargs["setup_command"] == setup_command
            assert call_kwargs["is_evaluation"] == (not session.is_agent_infer)

            # Verify runtime was added to runtimes list
            assert runtime == mock_runtime
            assert session._streaming_runtimes == [mock_runtime]
        finally:
            session.cleanup()

    @patch("slop_code.execution.session.spawn_streaming_runtime")
    def test_spawn_with_empty_parameters(
        self,
        mock_spawn_streaming_runtime: Mock,
        session: Session,
        workspace: Workspace,
    ):
        """Test that spawn handles empty parameters correctly."""
        # Setup mock
        mock_runtime = Mock(spec=StreamingRuntime)
        mock_spawn_streaming_runtime.return_value = mock_runtime

        try:
            session.prepare()
            runtime = session.spawn(
                ports={},
                mounts={},
                env_vars={},
                setup_command=None,
            )

            # Verify spawn_streaming_runtime was called with correct arguments
            mock_spawn_streaming_runtime.assert_called_once()
            call_kwargs = mock_spawn_streaming_runtime.call_args[1]
            assert call_kwargs["environment"] == session.spec
            assert call_kwargs["working_dir"] == workspace.working_dir
            assert call_kwargs["ports"] == {}
            assert call_kwargs["mounts"] == {}
            assert call_kwargs["env_vars"] == {}
            assert call_kwargs["setup_command"] is None
            assert call_kwargs["is_evaluation"] == (not session.is_agent_infer)

            # Verify runtime was added to runtimes list
            assert runtime == mock_runtime
            assert session._streaming_runtimes == [mock_runtime]
        finally:
            session.cleanup()


class TestRestoreFromSnapshotDir:
    """Tests for Session.restore_from_snapshot_dir method."""

    def test_restore_copies_files(
        self, session: Session, workspace: Workspace, tmp_path: Path
    ):
        """Test that restore copies files from snapshot to workspace."""
        # Create snapshot directory with files
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        (snapshot_dir / "file1.txt").write_text("content1")
        (snapshot_dir / "file2.py").write_text("print('hello')")

        try:
            session.prepare()
            session.restore_from_snapshot_dir(snapshot_dir)

            # Verify files were copied
            assert (workspace.working_dir / "file1.txt").exists()
            assert (workspace.working_dir / "file1.txt").read_text() == "content1"
            assert (workspace.working_dir / "file2.py").exists()
            assert (
                workspace.working_dir / "file2.py"
            ).read_text() == "print('hello')"
        finally:
            session.cleanup()

    def test_restore_copies_directories(
        self, session: Session, workspace: Workspace, tmp_path: Path
    ):
        """Test that restore copies nested directories."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        subdir = snapshot_dir / "subdir" / "nested"
        subdir.mkdir(parents=True)
        (subdir / "deep.txt").write_text("deep content")

        try:
            session.prepare()
            session.restore_from_snapshot_dir(snapshot_dir)

            assert (workspace.working_dir / "subdir" / "nested" / "deep.txt").exists()
            assert (
                workspace.working_dir / "subdir" / "nested" / "deep.txt"
            ).read_text() == "deep content"
        finally:
            session.cleanup()

    def test_restore_overwrites_existing_files(
        self, session: Session, workspace: Workspace, tmp_path: Path
    ):
        """Test that restore overwrites existing files in workspace."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        (snapshot_dir / "existing.txt").write_text("new content")

        try:
            session.prepare()
            # Create existing file with different content
            (workspace.working_dir / "existing.txt").write_text("old content")

            session.restore_from_snapshot_dir(snapshot_dir)

            assert (
                workspace.working_dir / "existing.txt"
            ).read_text() == "new content"
        finally:
            session.cleanup()

    def test_restore_raises_on_missing_snapshot_dir(
        self, session: Session, tmp_path: Path
    ):
        """Test that restore raises error when snapshot dir doesn't exist."""
        from slop_code.execution.session import SessionError

        try:
            session.prepare()
            with pytest.raises(SessionError, match="does not exist"):
                session.restore_from_snapshot_dir(tmp_path / "nonexistent")
        finally:
            session.cleanup()

    def test_restore_replaces_existing_directories(
        self, session: Session, workspace: Workspace, tmp_path: Path
    ):
        """Test that restore replaces existing directories completely."""
        snapshot_dir = tmp_path / "snapshot"
        snapshot_dir.mkdir()
        (snapshot_dir / "mydir").mkdir()
        (snapshot_dir / "mydir" / "new_file.txt").write_text("new")

        try:
            session.prepare()
            # Create existing directory with different content
            (workspace.working_dir / "mydir").mkdir()
            (workspace.working_dir / "mydir" / "old_file.txt").write_text("old")

            session.restore_from_snapshot_dir(snapshot_dir)

            # Old file should be gone, new file should exist
            assert not (workspace.working_dir / "mydir" / "old_file.txt").exists()
            assert (workspace.working_dir / "mydir" / "new_file.txt").exists()
            assert (
                workspace.working_dir / "mydir" / "new_file.txt"
            ).read_text() == "new"
        finally:
            session.cleanup()

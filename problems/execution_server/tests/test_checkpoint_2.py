"""Tests for checkpoint_2: File tracking with globs."""

import pytest

from .assertions import check, check_stats
from .models import ExecuteRequest


class TestFileTracking:
    """Core tests for file tracking functionality."""

    def test_initial_stats(self, client):
        """Stats endpoint should work."""
        stats = client.get_stats()
        check_stats(stats).status(200)

    def test_track_simple_file(self, client):
        """Track a single file with glob pattern."""
        resp = client.execute(
            ExecuteRequest(
                command="echo 'Hello tracked files' > test.txt",
                track=["*.txt"],
            )
        )
        check(resp).success().has_file("test.txt", "Hello tracked files\n").exit_code(0)

    def test_track_glob_mismatch(self, client):
        """Track pattern that doesn't match any files."""
        resp = client.execute(
            ExecuteRequest(
                command="echo hello > output.log",
                track=["*.txt"],
            )
        )
        check(resp).success().no_files()

    def test_track_no_glob(self, client):
        """Track with empty array returns no files field or empty dict."""
        resp = client.execute(
            ExecuteRequest(
                command="echo 'no track'",
                track=[],
            )
        )
        check(resp).success().files_absent()

    def test_track_without_track_field(self, client):
        """Request without track field should not include files."""
        resp = client.execute(ExecuteRequest(command="echo 'no track field' > out.txt"))
        check(resp).success().files_absent()

    def test_track_multiple_globs(self, client):
        """Multiple glob patterns with overlap should dedupe files."""
        resp = client.execute(
            ExecuteRequest(
                command="sh -c \"mkdir -p out && printf 'a\\n' > a.txt && printf 'b\\n' > out/b.txt\"",
                track=["*.txt", "out/*.txt", "**/*.txt"],
            )
        )
        check(resp).success().has_file("a.txt", "a\n").has_file("out/b.txt", "b\n")

    def test_not_recursive_by_default(self, client):
        """Non-recursive glob should not match nested files."""
        resp = client.execute(
            ExecuteRequest(
                command="sh -c \"mkdir -p sub && echo 'root' > root.txt && echo 'nested' > sub/nested.txt\"",
                track=["*.txt"],
            )
        )
        check(resp).success().has_file("root.txt", "root\n")
        assert "sub/nested.txt" not in resp.files

    def test_recursive_glob(self, client):
        """Recursive glob should match nested files."""
        resp = client.execute(
            ExecuteRequest(
                command="sh -c \"mkdir -p a/b && echo 'deep' > a/b/deep.log\"",
                track=["**/*.log"],
            )
        )
        check(resp).success().has_file("a/b/deep.log", "deep\n")

    def test_final_stats(self, client):
        """Stats should reflect all runs."""
        stats = client.get_stats()
        check_stats(stats).status(200).ran_at_least(1).duration_all_set()


@pytest.mark.functionality
class TestFileTrackingFunctionality:
    """Additional file tracking tests."""

    def test_track_binary_extension(self, client):
        """Track files with non-text extension."""
        resp = client.execute(
            ExecuteRequest(
                command="echo 'data' > output.bin",
                track=["*.bin"],
            )
        )
        check(resp).success().has_file("output.bin", "data\n")

    def test_track_no_extension(self, client):
        """Track files without extension."""
        resp = client.execute(
            ExecuteRequest(
                command="echo 'makefile content' > Makefile",
                track=["Makefile"],
            )
        )
        check(resp).success().has_file("Makefile", "makefile content\n")

    def test_track_multiple_files_same_dir(self, client):
        """Track multiple files in same directory."""
        resp = client.execute(
            ExecuteRequest(
                command="sh -c \"echo '1' > one.txt && echo '2' > two.txt && echo '3' > three.txt\"",
                track=["*.txt"],
            )
        )
        check(resp).success().has_file("one.txt", "1\n").has_file("two.txt", "2\n").has_file("three.txt", "3\n")

    def test_track_with_input_files(self, client):
        """Track output when input files provided."""
        resp = client.execute(
            ExecuteRequest(
                command="cp input.txt output.txt",
                files={"input.txt": "copied content"},
                track=["output.txt"],
            )
        )
        check(resp).success().has_file("output.txt", "copied content")

    def test_track_overwritten_file(self, client):
        """Track file that was overwritten during execution."""
        resp = client.execute(
            ExecuteRequest(
                command="sh -c \"echo 'first' > file.txt && echo 'second' > file.txt\"",
                track=["*.txt"],
            )
        )
        check(resp).success().has_file("file.txt", "second\n")

    def test_track_empty_file(self, client):
        """Track empty file."""
        resp = client.execute(
            ExecuteRequest(
                command="touch empty.txt",
                track=["*.txt"],
            )
        )
        check(resp).success().has_file("empty.txt", "")


@pytest.mark.error
class TestFileTrackingErrors:
    """Error handling for file tracking."""

    def test_invalid_track_type(self, client):
        """Non-array track should return 400."""
        resp = client.execute_raw({"command": "echo test", "track": "*.txt"})
        check(resp).status(400).error_code("INVALID_TYPE")

    def test_invalid_track_element_type(self, client):
        """Non-string elements in track should return 400."""
        resp = client.execute_raw({"command": "echo test", "track": [123]})
        check(resp).status(400).error_code("INVALID_TYPE")

"""Tests for checkpoint 2: extended word stats with lines and stopwords."""

import subprocess

import pytest


def run_main(
    input_text: str,
    args: list[str] | None = None,
    entrypoint: str = "python main.py",
) -> str:
    """Run main.py with the given input and return stdout."""
    cmd = entrypoint.split()
    if args:
        cmd.extend(args)

    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class TestLineCount:
    """Core tests for line counting functionality."""

    def test_lines_single_line(self, entrypoint):
        """Test line count with single line."""
        output = run_main(
            "hello world", args=["--lines"], entrypoint=entrypoint
        )
        assert output == "words: 2, lines: 1"

    def test_lines_multiple(self, entrypoint):
        """Test line count with multiple lines."""
        output = run_main(
            "hello world\nfoo bar\nbaz", args=["--lines"], entrypoint=entrypoint
        )
        assert output == "words: 5, lines: 3"

    def test_lines_empty(self, entrypoint):
        """Test line count with empty input."""
        output = run_main("", args=["--lines"], entrypoint=entrypoint)
        assert output == "words: 0, lines: 0"


class TestStopwordFiltering:
    """Tests for stopword filtering functionality."""

    def test_filter_stopwords(self, entrypoint, static_assets):
        """Test filtering stopwords."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "the quick brown fox",
            args=["--filter-stopwords", stopwords_path],
            entrypoint=entrypoint,
        )
        # "the" is a stopword, so only 3 words should be counted
        assert output == "3"

    def test_filter_all_stopwords(self, entrypoint, static_assets):
        """Test input that is all stopwords."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "the a an is are",
            args=["--filter-stopwords", stopwords_path],
            entrypoint=entrypoint,
        )
        assert output == "0"

    @pytest.mark.functionality
    def test_filter_case_insensitive(self, entrypoint, static_assets):
        """Test that stopword filtering is case-insensitive."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "THE Quick BROWN Fox",
            args=["--filter-stopwords", stopwords_path],
            entrypoint=entrypoint,
        )
        # "THE" should be filtered (case-insensitive)
        assert output == "3"


class TestCombined:
    """Tests for combined functionality."""

    @pytest.mark.functionality
    def test_lines_and_stopwords(self, entrypoint, static_assets):
        """Test combining --lines and --filter-stopwords."""
        stopwords_path = static_assets.get("stopwords")
        if not stopwords_path:
            pytest.skip("stopwords static asset not available")

        output = run_main(
            "the quick fox\njumps over",
            args=["--lines", "--filter-stopwords", stopwords_path],
            entrypoint=entrypoint,
        )
        # "the" and "over" are stopwords -> 3 words, 2 lines
        assert output == "words: 3, lines: 2"

"""Tests for checkpoint 1: basic word counting."""

import subprocess


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


class TestBasicWordCount:
    """Core tests for basic word counting functionality."""

    def test_simple_words(self, entrypoint):
        """Test counting simple space-separated words."""
        output = run_main("hello world", entrypoint=entrypoint)
        assert output == "2"

    def test_multiple_words(self, entrypoint):
        """Test counting multiple words."""
        output = run_main("the quick brown fox jumps", entrypoint=entrypoint)
        assert output == "5"

    def test_empty_input(self, entrypoint):
        """Test empty input returns 0."""
        output = run_main("", entrypoint=entrypoint)
        assert output == "0"

    def test_single_word(self, entrypoint):
        """Test single word."""
        output = run_main("hello", entrypoint=entrypoint)
        assert output == "1"

    def test_whitespace_only(self, entrypoint):
        """Test whitespace-only input."""
        output = run_main("   \t\n  ", entrypoint=entrypoint)
        assert output == "0"

    def test_multiline(self, entrypoint):
        """Test multiline input."""
        output = run_main("hello world\nfoo bar baz", entrypoint=entrypoint)
        assert output == "5"

#!/usr/bin/env python3
"""Word statistics CLI tool."""

import argparse
import sys


def load_stopwords(path: str) -> set[str]:
    """Load stopwords from a file (one per line)."""
    with open(path) as f:
        return {line.strip().lower() for line in f if line.strip()}


def count_words(text: str, stopwords: set[str] | None = None) -> int:
    """Count words in text, optionally filtering stopwords."""
    words = text.split()
    if stopwords:
        words = [w for w in words if w.lower() not in stopwords]
    return len(words)


def count_lines(text: str) -> int:
    """Count lines in text."""
    if not text:
        return 0
    return len(text.splitlines())


def main():
    parser = argparse.ArgumentParser(description="Word statistics tool")
    parser.add_argument(
        "--lines",
        action="store_true",
        help="Also output line count",
    )
    parser.add_argument(
        "--filter-stopwords",
        type=str,
        metavar="PATH",
        help="Path to stopwords file",
    )
    args = parser.parse_args()

    # Read all input
    text = sys.stdin.read()

    # Load stopwords if specified
    stopwords = None
    if args.filter_stopwords:
        stopwords = load_stopwords(args.filter_stopwords)

    # Count words
    word_count = count_words(text, stopwords)

    # Output
    if args.lines:
        line_count = count_lines(text)
        print(f"words: {word_count}, lines: {line_count}")
    else:
        print(word_count)


if __name__ == "__main__":
    main()

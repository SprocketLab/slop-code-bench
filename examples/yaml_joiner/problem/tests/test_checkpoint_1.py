"""Tests for checkpoint_1: Basic YAML joining."""

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from deepdiff import DeepDiff


def load_test_case(case_dir: Path) -> tuple[list[str], dict, list[Path]]:
    """Load a test case from a directory.

    Returns:
        Tuple of (args, expected_result, input_files)
    """
    args = shlex.split((case_dir / "ARGS").read_text().strip())
    expected = yaml.safe_load((case_dir / "result.yaml").read_text())

    # Find input files (all .yaml files except result.yaml)
    input_files = [
        f for f in case_dir.glob("**/*.yaml")
        if f.name != "result.yaml"
    ]

    return args, expected, input_files


def test_single_file_join(entrypoint_argv, test_data_dir, tmp_path):
    """Core: Join a single YAML file."""
    case_dir = test_data_dir / "checkpoint_1" / "core" / "single"
    args, expected, input_files = load_test_case(case_dir)

    # Copy input files to tmp_path
    for f in input_files:
        rel_path = f.relative_to(case_dir)
        dest = tmp_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, dest)

    # Run the submission
    result = subprocess.run(
        entrypoint_argv + args,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, \
        f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    # Check output file exists
    output_file = tmp_path / "result.yaml"
    assert output_file.exists(), f"Output file {output_file} does not exist"

    # Compare results
    actual = yaml.safe_load(output_file.read_text())
    diff = DeepDiff(expected, actual, ignore_order=True)
    assert not diff, f"Output mismatch: {diff}"


def test_multiple_files_join(entrypoint_argv, test_data_dir, tmp_path):
    """Core: Join multiple YAML files."""
    case_dir = test_data_dir / "checkpoint_1" / "core" / "multiple"
    args, expected, input_files = load_test_case(case_dir)

    # Copy input files to tmp_path
    for f in input_files:
        rel_path = f.relative_to(case_dir)
        dest = tmp_path / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, dest)

    # Run the submission
    result = subprocess.run(
        entrypoint_argv + args,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, \
        f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    # Check output file exists
    output_file = tmp_path / "result.yaml"
    assert output_file.exists(), f"Output file {output_file} does not exist"

    # Compare results
    actual = yaml.safe_load(output_file.read_text())
    diff = DeepDiff(expected, actual, ignore_order=True)
    assert not diff, f"Output mismatch: {diff}"

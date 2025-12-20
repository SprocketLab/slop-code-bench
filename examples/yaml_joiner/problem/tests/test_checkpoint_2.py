"""Tests for checkpoint_2: Directory recursion and static assets."""

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
        Tuple of (args, expected_result, input_files_or_dirs)
    """
    args = shlex.split((case_dir / "ARGS").read_text().strip())
    expected = yaml.safe_load((case_dir / "result.yaml").read_text())

    # Find input files/directories (all .yaml files except result.yaml, and subdirs)
    input_files = [
        f for f in case_dir.glob("**/*.yaml")
        if f.name not in ("result.yaml", "ARGS", "ignore.yaml")
    ]

    return args, expected, input_files


def substitute_static_assets(args: list[str], static_assets: dict) -> list[str]:
    """Replace {{static:name}} placeholders with actual paths."""
    result = []
    pattern = re.compile(r"\{\{static:(\w+)\}\}")

    for arg in args:
        match = pattern.search(arg)
        if match:
            asset_name = match.group(1)
            if asset_name in static_assets:
                arg = pattern.sub(str(static_assets[asset_name]), arg)
        result.append(arg)

    return result


def test_local_directory_recursion(entrypoint_argv, test_data_dir, tmp_path):
    """Core: Recursively join YAML files in a local directory."""
    case_dir = test_data_dir / "checkpoint_2" / "random" / "local"
    args, expected, input_files = load_test_case(case_dir)

    # Copy the local/ subdirectory structure to tmp_path
    local_src = case_dir / "local"
    if local_src.exists():
        shutil.copytree(local_src, tmp_path / "local")

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


def test_static_assets_directory(entrypoint_argv, test_data_dir, static_assets, tmp_path):
    """Core: Join YAML files from a static assets directory."""
    case_dir = test_data_dir / "checkpoint_2" / "random" / "static"
    args_raw = shlex.split((case_dir / "ARGS").read_text().strip())
    expected = yaml.safe_load((case_dir / "result.yaml").read_text())

    # Substitute static asset placeholders
    args = substitute_static_assets(args_raw, static_assets)

    # Run the submission from tmp_path (output file goes there)
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

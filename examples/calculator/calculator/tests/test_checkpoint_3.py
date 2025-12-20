"""Tests for checkpoint_3: Functions and history."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml


def load_input_result(case_dir: Path) -> tuple[str, dict]:
    """Load stdin input and expected result from a test case directory."""
    stdin = (case_dir / "input").read_text()
    expected = json.loads((case_dir / "result").read_text())
    return stdin, expected


def load_error_case(case_file: Path) -> dict:
    """Load an error test case from a YAML file."""
    return yaml.safe_load(case_file.read_text())


def parse_calculator_output(stdout: str) -> list:
    """Parse calculator output to extract results.

    The calculator outputs lines like 'equation: <result>' and we need to
    extract the result values, ignoring the 'exit' command output.
    """
    results = []
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if not line or line == "exit":
            continue
        # Try to extract number from 'equation: <result>' format
        if ":" in line:
            _, _, value = line.partition(":")
            value = value.strip()
        else:
            value = line
        try:
            results.append(float(value))
        except ValueError:
            pass
    return results


def test_advanced_math(entrypoint_argv, test_data_dir):
    """Core: Advanced mathematical expressions."""
    case_dir = test_data_dir / "checkpoint_3" / "core" / "advanced_math"
    stdin, expected = load_input_result(case_dir)

    result = subprocess.run(
        entrypoint_argv + ["--eval"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    actual_results = parse_calculator_output(result.stdout)
    expected_results = expected.get("results", [])

    assert len(actual_results) == len(expected_results), \
        f"Expected {len(expected_results)} results, got {len(actual_results)}"

    for i, (actual, exp) in enumerate(zip(actual_results, expected_results)):
        assert actual == exp, f"Result {i}: expected {exp}, got {actual}"


@pytest.mark.functionality
def test_simple_function(entrypoint_argv, test_data_dir):
    """Functionality: Simple function definition and call."""
    case_dir = test_data_dir / "checkpoint_3" / "functions" / "simple"
    stdin, expected = load_input_result(case_dir)

    result = subprocess.run(
        entrypoint_argv + ["--eval"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    actual_results = parse_calculator_output(result.stdout)
    expected_results = expected.get("results", [])

    for i, (actual, exp) in enumerate(zip(actual_results, expected_results)):
        assert actual == exp, f"Result {i}: expected {exp}, got {actual}"


@pytest.mark.functionality
def test_multiple_params_function(entrypoint_argv, test_data_dir):
    """Functionality: Function with multiple parameters."""
    case_dir = test_data_dir / "checkpoint_3" / "functions" / "multiple_params"
    stdin, expected = load_input_result(case_dir)

    result = subprocess.run(
        entrypoint_argv + ["--eval"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    actual_results = parse_calculator_output(result.stdout)
    expected_results = expected.get("results", [])

    for i, (actual, exp) in enumerate(zip(actual_results, expected_results)):
        assert actual == exp, f"Result {i}: expected {exp}, got {actual}"


@pytest.mark.functionality
def test_history_basic(entrypoint_argv, test_data_dir):
    """Functionality: History command shows previous calculations."""
    case_dir = test_data_dir / "checkpoint_3" / "history" / "basic"
    stdin, expected = load_input_result(case_dir)

    result = subprocess.run(
        entrypoint_argv + ["--eval"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    actual_results = parse_calculator_output(result.stdout)
    expected_results = expected.get("results", [])

    for i, (actual, exp) in enumerate(zip(actual_results, expected_results)):
        assert actual == exp, f"Result {i}: expected {exp}, got {actual}"


@pytest.mark.functionality
def test_history_clear(entrypoint_argv, test_data_dir):
    """Functionality: Clear command clears history."""
    case_dir = test_data_dir / "checkpoint_3" / "history" / "clear"
    stdin, expected = load_input_result(case_dir)

    result = subprocess.run(
        entrypoint_argv + ["--eval"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"

    actual_results = parse_calculator_output(result.stdout)
    expected_results = expected.get("results", [])

    for i, (actual, exp) in enumerate(zip(actual_results, expected_results)):
        assert actual == exp, f"Result {i}: expected {exp}, got {actual}"


@pytest.mark.error
def test_invalid_function(entrypoint_argv, test_data_dir):
    """Error: Invalid function definition should error with status code 1."""
    case_file = test_data_dir / "checkpoint_3" / "errors" / "invalid_function.yaml"
    case = load_error_case(case_file)

    result = subprocess.run(
        entrypoint_argv + ["--eval"],
        input=case["stdin"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    expected_code = case["expected"]["status_code"]
    assert result.returncode == expected_code, \
        f"Expected exit code {expected_code}, got {result.returncode}"


@pytest.mark.error
def test_function_call_error(entrypoint_argv, test_data_dir):
    """Error: Function call error should error with status code 2."""
    case_file = test_data_dir / "checkpoint_3" / "errors" / "function_call_error.yaml"
    case = load_error_case(case_file)

    result = subprocess.run(
        entrypoint_argv + ["--eval"],
        input=case["stdin"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    expected_code = case["expected"]["status_code"]
    assert result.returncode == expected_code, \
        f"Expected exit code {expected_code}, got {result.returncode}"

"""Common file path constants used across slop_code modules.

This module defines standard filenames and directory names used throughout
the codebase for consistent file organization and access.
"""

# Agent run output files
RUN_INFO_FILENAME = "run_info.yaml"  # Combined run spec + execution summary
CHECKPOINT_CONFIG_NAME = "checkpoint.yaml"
PROMPT_FILENAME = "prompt.txt"
INFERENCE_RESULT_FILENAME = "inference_result.json"
DIFF_FILENAME = "diff.json"
RUBRIC_FILENAME = "rubric.jsonl"
QUALITY_METRIC_SAVENAME = "overall_quality.json"

# Quality analysis directory and files
QUALITY_DIR = "quality_analysis"
FILES_QUALITY_SAVENAME = "files.jsonl"
SYMBOLS_QUALITY_SAVENAME = "symbols.jsonl"
AST_GREP_QUALITY_SAVENAME = "ast_grep.jsonl"
CONFIG_FILENAME = "config.yaml"
SUMMARY_FILENAME = "result.json"
CHECKPOINT_RESULTS_FILENAME = "checkpoint_results.jsonl"

VERIFIER_REPORT_FILENAME = "reports.parquet"
EVALUATION_FILENAME = "evaluation.json"

# Visualization/dashboard files
DASHBOARD_CONFIG_FILENAME = "dashboard_config.json"

# Directory names
AGENT_DIR_NAME = "agent"
AGENT_TAR_FILENAME = "agent.tar.gz"
SNAPSHOT_DIR_NAME = "snapshot"

# Configuration files
ENV_CONFIG_NAME = "environment.yaml"
PROBLEM_CONFIG_NAME = "problem.yaml"


def get_save_spec_dump() -> dict[str, str]:
    """Get mapping of spec keys to their corresponding filenames.

    Returns:
        Dictionary mapping specification keys to filename constants.
    """
    return {
        "snapshot_dir": SNAPSHOT_DIR_NAME,
        "agent_dir": AGENT_DIR_NAME,
        "agent_tar": AGENT_TAR_FILENAME,
        "inference_result_file": INFERENCE_RESULT_FILENAME,
        "run_info_file": RUN_INFO_FILENAME,
        "prompt_file": PROMPT_FILENAME,
        "checkpoint_file": CHECKPOINT_CONFIG_NAME,
        "problem_file": PROBLEM_CONFIG_NAME,
        "environment_file": ENV_CONFIG_NAME,
    }

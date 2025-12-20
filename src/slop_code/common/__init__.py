"""Common utilities shared across slop_code modules.

This package contains pure utility functions that do NOT import from
other slop_code modules (except logging). This ensures clean separation
and prevents circular dependencies.
"""

# Common utilities
# File path constants
from slop_code.common.common import deep_merge
from slop_code.common.common import mask_sensitive_values
from slop_code.common.constants import AGENT_DIR_NAME
from slop_code.common.constants import AGENT_TAR_FILENAME
from slop_code.common.constants import AST_GREP_QUALITY_SAVENAME
from slop_code.common.constants import CHECKPOINT_CONFIG_NAME
from slop_code.common.constants import CHECKPOINT_RESULTS_FILENAME
from slop_code.common.constants import CONFIG_FILENAME
from slop_code.common.constants import DIFF_FILENAME
from slop_code.common.constants import ENV_CONFIG_NAME
from slop_code.common.constants import EVALUATION_FILENAME
from slop_code.common.constants import FILES_QUALITY_SAVENAME
from slop_code.common.constants import INFERENCE_RESULT_FILENAME
from slop_code.common.constants import PROBLEM_CONFIG_NAME
from slop_code.common.constants import PROMPT_FILENAME
from slop_code.common.constants import QUALITY_DIR
from slop_code.common.constants import QUALITY_METRIC_SAVENAME
from slop_code.common.constants import RUBRIC_FILENAME
from slop_code.common.constants import RUN_INFO_FILENAME
from slop_code.common.constants import WORKSPACE_TEST_DIR
from slop_code.common.constants import SNAPSHOT_DIR_NAME
from slop_code.common.constants import SUMMARY_FILENAME
from slop_code.common.constants import SYMBOLS_QUALITY_SAVENAME
from slop_code.common.constants import VERIFIER_REPORT_FILENAME
from slop_code.common.constants import get_save_spec_dump

# Model catalog
from slop_code.common.llms import APIPricing
from slop_code.common.llms import ModelCatalog
from slop_code.common.llms import ModelDefinition
from slop_code.common.llms import ThinkingPreset
from slop_code.common.llms import TokenUsage

# Path serialization utilities
from slop_code.common.paths import serialize_path_dict
from slop_code.common.paths import to_relative_path

# Rendering utilities
from slop_code.common.render import get_file_params
from slop_code.common.render import render_criteria_text
from slop_code.common.render import render_multi_file_prefix
from slop_code.common.render import render_prompt
from slop_code.common.render import replace_spec_placeholders
from slop_code.common.render import strip_canary_string

__all__ = [
    # Path utilities
    "serialize_path_dict",
    "to_relative_path",
    # Constants
    "AGENT_DIR_NAME",
    "AGENT_TAR_FILENAME",
    "CHECKPOINT_CONFIG_NAME",
    "CHECKPOINT_RESULTS_FILENAME",
    "DIFF_FILENAME",
    "ENV_CONFIG_NAME",
    "CONFIG_FILENAME",
    "FILES_QUALITY_SAVENAME",
    "INFERENCE_RESULT_FILENAME",
    "RUBRIC_FILENAME",
    "QUALITY_DIR",
    "QUALITY_METRIC_SAVENAME",
    "SYMBOLS_QUALITY_SAVENAME",
    "AST_GREP_QUALITY_SAVENAME",
    "EVALUATION_FILENAME",
    "VERIFIER_REPORT_FILENAME",
    "SUMMARY_FILENAME",
    "PROBLEM_CONFIG_NAME",
    "PROMPT_FILENAME",
    "RUN_INFO_FILENAME",
    "SNAPSHOT_DIR_NAME",
    "WORKSPACE_TEST_DIR",
    "get_save_spec_dump",
    # Rendering
    "get_file_params",
    "render_criteria_text",
    "render_multi_file_prefix",
    "render_prompt",
    "replace_spec_placeholders",
    "strip_canary_string",
    # Common utilities
    "mask_sensitive_values",
    "deep_merge",
    # LLM catalog
    "APIPricing",
    "ModelCatalog",
    "ModelDefinition",
    "TokenUsage",
    "ThinkingPreset",
]

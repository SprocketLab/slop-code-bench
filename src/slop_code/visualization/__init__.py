"""Visualization utilities for slop-code-bench."""

from slop_code.visualization.chart_builders import MetricConfig
from slop_code.visualization.chart_builders import ProgressLineChartBuilder
from slop_code.visualization.chart_builders import ProgressLineChartConfig
from slop_code.visualization.chart_builders import RadarChartBuilder
from slop_code.visualization.chart_builders import RadarChartConfig
from slop_code.visualization.chart_builders import SubplotBarChartBuilder
from slop_code.visualization.chart_builders import SubplotBarChartConfig
from slop_code.visualization.chart_builders import ViolinDistributionBuilder
from slop_code.visualization.chart_builders import ViolinDistributionConfig
from slop_code.visualization.chart_builders import apply_graph_style
from slop_code.visualization.constants import GRAPH_HEIGHT
from slop_code.visualization.constants import GRAPH_WIDTH
from slop_code.visualization.constants import MODEL_COLORS
from slop_code.visualization.constants import MODEL_DISPLAY_NAMES
from slop_code.visualization.constants import PROVIDER_BASE_COLORS
from slop_code.visualization.constants import PROVIDER_GRADS
from slop_code.visualization.constants import SUBPLOT_HEIGHT
from slop_code.visualization.constants import SUBPLOT_WIDTH
from slop_code.visualization.constants import VERSION_COLORS
from slop_code.visualization.data_transforms import compute_progress_bins
from slop_code.visualization.data_transforms import compute_progress_metric
from slop_code.visualization.data_transforms import (
    filter_high_thinking_checkpoints,
)
from slop_code.visualization.data_transforms import filter_version_data
from slop_code.visualization.data_transforms import format_model_display_name
from slop_code.visualization.data_transforms import get_provider
from slop_code.visualization.data_transforms import get_version_colors
from slop_code.visualization.data_transforms import normalize_per_1k_loc
from slop_code.visualization.data_transforms import (
    select_best_version_per_model,
)
from slop_code.visualization.graph_utils import FONT_FAMILY_IMPACT
from slop_code.visualization.graph_utils import get_theme
from slop_code.visualization.graph_utils import get_theme_layout

__all__ = [
    # Constants
    "GRAPH_HEIGHT",
    "GRAPH_WIDTH",
    "MODEL_COLORS",
    "MODEL_DISPLAY_NAMES",
    "PROVIDER_BASE_COLORS",
    "PROVIDER_GRADS",
    "SUBPLOT_HEIGHT",
    "SUBPLOT_WIDTH",
    "VERSION_COLORS",
    "FONT_FAMILY_IMPACT",
    # Data transforms
    "compute_progress_bins",
    "compute_progress_metric",
    "filter_high_thinking_checkpoints",
    "filter_version_data",
    "format_model_display_name",
    "get_provider",
    "get_version_colors",
    "normalize_per_1k_loc",
    "select_best_version_per_model",
    # Chart builders
    "apply_graph_style",
    "MetricConfig",
    "ProgressLineChartBuilder",
    "ProgressLineChartConfig",
    "RadarChartBuilder",
    "RadarChartConfig",
    "SubplotBarChartBuilder",
    "SubplotBarChartConfig",
    "ViolinDistributionBuilder",
    "ViolinDistributionConfig",
    # Theme utilities
    "get_theme",
    "get_theme_layout",
]

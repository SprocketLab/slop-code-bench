"""Graph components for the dashboard."""

from slop_code.dashboard.graphs.erosion import build_delta_vs_solve_scatter
from slop_code.dashboard.graphs.erosion import build_mass_delta_bars
from slop_code.dashboard.graphs.erosion import build_mass_delta_boxplots
from slop_code.dashboard.graphs.erosion import build_mass_delta_heatmap
from slop_code.dashboard.graphs.erosion import build_other_mass_metrics
from slop_code.dashboard.graphs.erosion import build_symbol_sprawl
from slop_code.dashboard.graphs.erosion import build_velocity_metrics

__all__ = [
    "build_delta_vs_solve_scatter",
    "build_mass_delta_bars",
    "build_mass_delta_boxplots",
    "build_mass_delta_heatmap",
    "build_other_mass_metrics",
    "build_symbol_sprawl",
    "build_velocity_metrics",
]

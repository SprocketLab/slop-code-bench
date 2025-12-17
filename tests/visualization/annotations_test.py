"""Unit tests for smart annotation placement."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from slop_code.dashboard.graphs.scatter import add_smart_annotations


def _annotations(fig: go.Figure) -> list[Any]:
    anns = fig.layout.annotations
    return list(anns) if anns else []


def test_add_smart_annotations_varies_positions_for_clustered_points() -> None:
    fig = go.Figure()
    points = [
        (1.0, 50.0, "A", "#ff0000"),
        (1.0, 50.0, "B", "#00ff00"),
        (1.0, 50.0, "C", "#0000ff"),
        (1.0, 50.0, "D", "#999999"),
    ]

    add_smart_annotations(fig, points)

    anns = _annotations(fig)
    assert len(anns) == len(points)

    # We expect at least two distinct placements (shift or arrow offsets).
    placements: set[tuple[str, int, int]] = set()
    for a in anns:
        if bool(a.showarrow):
            placements.add(("arrow", int(a.ax), int(a.ay)))
        else:
            placements.add(("shift", int(a.xshift or 0), int(a.yshift or 0)))

    assert len(placements) > 1


def test_add_smart_annotations_uses_arrow_when_no_good_near_spot() -> None:
    fig = go.Figure()
    # There are 8 directions * 4 near radii = 32 distinct "near" candidate centers.
    # Once those are occupied in a dense cluster, later labels must fall back to
    # "far with arrow" placements.
    points = [(1.0, 50.0, "X", "#333333") for _ in range(40)]

    add_smart_annotations(fig, points)

    anns = _annotations(fig)
    assert len(anns) == len(points)

    assert any(bool(a.showarrow) for a in anns)
    for a in anns:
        if bool(a.showarrow):
            assert a.ax is not None and a.ay is not None
            assert abs(int(a.ax)) + abs(int(a.ay)) > 0

"""Directory × label heatmap — which patterns fire where.

Rows are directories (top 30 by labeled-call count), columns are the
distinct labels present in the target. A dark cell means that
directory concentrates that kind of call — useful for spotting pattern
gaps (expected labels missing) and false positives (unexpected floods).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import PurePosixPath

import plotly.graph_objects as go

from bindwood import CodeIndex


TOP_DIRECTORIES = 30


def figure_label_heatmap(idx: CodeIndex, target: str) -> go.Figure:
    """Heatmap of labeled-call counts per directory × label."""
    conn = idx._connector()

    rows = conn.execute(
        "SELECT file, properties FROM nodes "
        "WHERE target = ? AND type = 'call' AND properties IS NOT NULL "
        "AND properties != ''",
        (target,),
    ).fetchall()

    counts: dict[tuple[str, str], int] = defaultdict(int)
    dir_totals: dict[str, int] = defaultdict(int)
    for r in rows:
        file = r["file"]
        if not file:
            continue
        try:
            props = json.loads(r["properties"])
        except (TypeError, ValueError):
            continue
        labels = props.get("labels") or []
        if not labels:
            continue
        directory = _top_dir(file)
        for label in labels:
            counts[(directory, label)] += 1
            dir_totals[directory] += 1

    if not counts:
        return _empty_figure(
            f"No labeled calls for target {target!r}. "
            "Add `labels` to your config to populate this view."
        )

    top_dirs = sorted(
        dir_totals.items(), key=lambda kv: kv[1], reverse=True
    )[:TOP_DIRECTORIES]
    dir_order = [d for d, _ in top_dirs]
    label_order = sorted({label for _, label in counts})

    z: list[list[int]] = [
        [counts.get((d, label), 0) for label in label_order] for d in dir_order
    ]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=label_order,
            y=dir_order,
            colorscale="Viridis",
            hovertemplate="directory: %{y}<br>label: %{x}<br>count: %{z}<extra></extra>",
            colorbar={"title": "Count"},
        )
    )
    fig.update_layout(
        title={
            "text": f"Label heatmap — {target} (top {len(dir_order)} dirs)",
            "x": 0.5,
        },
        xaxis={"title": "Label", "tickangle": -30},
        yaxis={"title": "Directory", "autorange": "reversed"},
        margin={"l": 180, "r": 20, "t": 60, "b": 80},
        height=max(400, 22 * len(dir_order) + 160),
    )
    return fig


def _top_dir(file: str, depth: int = 2) -> str:
    path = PurePosixPath(file.replace("\\", "/"))
    parts = path.parts
    if not parts:
        return file
    return "/".join(parts[: min(depth, len(parts) - 1)]) or parts[0]


def _empty_figure(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg, xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False
    )
    fig.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        height=500,
    )
    return fig

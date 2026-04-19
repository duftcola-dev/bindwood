"""Directory treemap — the 'skeleton' of a project sized by content.

Each file becomes a leaf rectangle sized by the number of meaningful
nodes it contains (functions, classes, types, labeled calls). Parent
rectangles aggregate their descendants so the eye lands on the dense
parts of the codebase first.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import plotly.graph_objects as go

from bindwood import CodeIndex


def figure_project_treemap(idx: CodeIndex, target: str) -> go.Figure:
    """Nested treemap of files by directory, sized by node count."""
    conn = idx._connector()

    rows = conn.execute(
        "SELECT file, COUNT(*) AS cnt FROM nodes "
        "WHERE target = ? "
        "AND type IN ('function','class','interface','type_alias','enum','call') "
        "AND file IS NOT NULL "
        "GROUP BY file",
        (target,),
    ).fetchall()

    if not rows:
        return _empty_figure(f"No files with contents for target {target!r}")

    labels: list[str] = []
    parents: list[str] = []
    values: list[int] = []
    ids: list[str] = []
    seen: set[str] = set()

    root_id = target
    labels.append(target)
    parents.append("")
    values.append(0)
    ids.append(root_id)
    seen.add(root_id)

    for r in rows:
        file = r["file"]
        cnt = r["cnt"]
        path = PurePosixPath(file.replace("\\", "/"))
        parts = path.parts
        for i in range(1, len(parts) + 1):
            frag = "/".join(parts[:i])
            node_id = f"{target}/{frag}"
            parent_id = (
                f"{target}/{'/'.join(parts[: i - 1])}" if i > 1 else root_id
            )
            is_leaf = i == len(parts)
            if node_id in seen:
                if is_leaf:
                    idx_pos = ids.index(node_id)
                    values[idx_pos] = cnt
                continue
            seen.add(node_id)
            labels.append(parts[i - 1])
            parents.append(parent_id)
            values.append(cnt if is_leaf else 0)
            ids.append(node_id)

    fig = go.Figure(
        go.Treemap(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            hovertemplate="<b>%{label}</b><br>path: %{id}<br>contents: %{value}<extra></extra>",
            marker={"colorscale": "Blues"},
        )
    )
    fig.update_layout(
        title={"text": f"Project skeleton — {target}", "x": 0.5},
        margin={"l": 10, "r": 10, "t": 60, "b": 10},
        height=700,
    )
    return fig


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

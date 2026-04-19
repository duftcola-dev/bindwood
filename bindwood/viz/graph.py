"""File-level project graph rendered as a Plotly force-directed figure.

We aggregate to the **file** node set, using ``imports`` edges between
files. Function/class/call nodes are summarized via a per-file
``nodes_inside`` count that drives node size. At project scale this
keeps the layout under ~1k points even for mid-sized monorepos.
"""

from __future__ import annotations

import math
from typing import Any

import networkx as nx
import plotly.graph_objects as go

from bindwood import CodeIndex


def figure_project_graph(idx: CodeIndex, target: str) -> go.Figure:
    """Force-directed file graph for a single extraction target."""
    conn = idx._connector()

    file_rows = conn.execute(
        "SELECT id, file FROM nodes WHERE target = ? AND type = 'file'",
        (target,),
    ).fetchall()

    if not file_rows:
        return _empty_figure(f"No files found for target {target!r}")

    inside_rows = conn.execute(
        "SELECT file, COUNT(*) AS cnt FROM nodes "
        "WHERE target = ? AND type IN ('function','class','interface','type_alias','enum','call') "
        "GROUP BY file",
        (target,),
    ).fetchall()
    inside_by_file = {r["file"]: r["cnt"] for r in inside_rows}

    edge_rows = conn.execute(
        "SELECT source, target_node FROM edges "
        "WHERE target = ? AND type = 'imports' AND target_node IS NOT NULL",
        (target,),
    ).fetchall()

    g: nx.Graph = nx.Graph()
    for r in file_rows:
        g.add_node(r["id"], file=r["file"], inside=inside_by_file.get(r["file"], 0))
    file_ids = {r["id"] for r in file_rows}
    for e in edge_rows:
        if e["source"] in file_ids and e["target_node"] in file_ids:
            g.add_edge(e["source"], e["target_node"])

    pos = nx.spring_layout(g, seed=42, k=1.0 / math.sqrt(max(len(g), 1)))

    edge_x: list[float] = []
    edge_y: list[float] = []
    for u, v in g.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line={"width": 0.6, "color": "#9aa0a6"},
        hoverinfo="none",
        showlegend=False,
    )

    node_x: list[float] = []
    node_y: list[float] = []
    hover: list[str] = []
    sizes: list[float] = []
    degrees: list[int] = []
    for n, data in g.nodes(data=True):
        x, y = pos[n]
        node_x.append(x)
        node_y.append(y)
        deg = g.degree(n)
        inside = data.get("inside", 0)
        degrees.append(deg)
        sizes.append(6 + math.sqrt(inside) * 2)
        hover.append(
            f"<b>{data.get('file', n)}</b><br>"
            f"Contents: {inside}<br>"
            f"Connections: {deg}"
        )

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers",
        marker={
            "size": sizes,
            "color": degrees,
            "colorscale": "Viridis",
            "showscale": True,
            "colorbar": {"title": "Import<br>degree"},
            "line": {"width": 0.5, "color": "white"},
        },
        hoverinfo="text",
        hovertext=hover,
        showlegend=False,
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title={"text": f"Project graph — {target}", "x": 0.5},
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        xaxis={"visible": False},
        yaxis={"visible": False},
        plot_bgcolor="white",
        hovermode="closest",
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

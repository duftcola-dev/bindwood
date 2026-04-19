"""Human-facing visualizations for the code graph.

This package renders the bindwood database to interactive HTML using
Plotly + NetworkX. It is intentionally read-only and scoped to what a
human wants to look at — the machine-facing path stays on the
CodeIndex / MCP tools.

Entry points are the ``figure_*`` functions, each returning a Plotly
figure object. The FastAPI layer (:mod:`bindwood.servers.http`)
serializes them to HTML and serves them at ``/viz``.
"""

from bindwood.viz.graph import figure_project_graph
from bindwood.viz.heatmap import figure_label_heatmap
from bindwood.viz.treemap import figure_project_treemap

__all__ = [
    "figure_project_graph",
    "figure_label_heatmap",
    "figure_project_treemap",
]

# Visualization

bindwood's MCP server and query CLI give Claude a great view of the graph — but the same data is useful for **humans** who want to study a codebase. The viz module renders the database as interactive HTML, served from the same FastAPI process as the existing HTTP API.

## What's available

| Tab | What it shows | When to use |
|-----|--------------|-------------|
| **Graph** | File-level force-directed graph. Node size = contents, color = import degree. | *"How is this codebase connected?"* Spot hubs and islands. |
| **Skeleton** | Directory treemap, sized by node count per file. | *"Where's the mass of the code?"* Find the dense / sparse parts. |
| **Labels** | Directory × label heatmap, top 30 directories. | *"Are my label patterns tuned?"* Spot gaps (expected labels missing) and floods (false positives). |

The aggregated file-level default keeps renders fast even for mid-sized monorepos. Plotly starts to struggle past ~5k points, which is exactly why the graph tab summarizes function/class/call nodes into a single per-file size.

## Install

The viz routes require the `[viz]` extra (adds Plotly, NetworkX, numpy, Jinja2):

```bash
uv sync --extra viz
# or
pip install "bindwood[viz]"
```

The extra implies `[http]`, so you don't need to install both.

## Run

```bash
bindwood scan                              # make sure the DB exists
bindwood serve --host 127.0.0.1 --port 8765
# → open http://127.0.0.1:8765/viz/
```

The viz pages are served at **`/viz/`** and are **not gated by `BINDWOOD_API_KEY`** — they're meant for local human use. If you expose the server beyond localhost, put it behind a reverse proxy with auth of its own.

## Routes

| Method | Path | Response |
|--------|------|----------|
| GET | `/viz/` | Target list + DB overview (HTML). |
| GET | `/viz/{target}/graph` | Interactive file graph. |
| GET | `/viz/{target}/treemap` | Directory treemap. |
| GET | `/viz/{target}/heatmap` | Directory × label heatmap. |

Unknown target → empty figure with a hint. Unknown tab → HTTP 404.

## Reading each view

### Graph

- **Big dark nodes** — files that import and are imported from many places. Bus-factor risks; any change ripples out.
- **Bright green islands** — modules that nothing imports. Either dead code, or leaf modules that are fine to refactor in isolation.
- **Tight clusters** — groups of files that communicate mostly among themselves. Good candidates for packaging as a sub-module.

### Skeleton

- Rectangles are sized by **node count** (functions + classes + types + calls). Bigger = denser.
- Zoom in by clicking a directory; parent hierarchy breadcrumb appears at the top.
- Use this alongside a `find --type function --file <dir>` query to drill into what's actually inside.

### Labels

- **Rows = directories, columns = labels**, cell intensity = count of matching calls in that directory.
- **Cold columns** for a label you expected (e.g. no `auth_check` hits on a route directory) → pattern gap. Revisit your `labels` config.
- **Hot rows** for a label you *didn't* expect → likely false positives. Tighten the pattern (e.g. `httpClient.get` instead of `*.get`).
- If the tab shows *"No labeled calls for target..."*, your config has no `labels` rules yet. See [Extractors → Label Patterns](../extractors/label-patterns.md).

## Limitations of the first increment

- **File-level only.** Function-level graphs would require a WebGL renderer past a few thousand nodes; Plotly can't do that well. Function detail lives in the CLI for now (`bindwood query neighbors`).
- **No cross-target view yet.** Frontend `api_call → backend route → table` is the most valuable "full-stack" view but needs richer cross-reference data than a single scan produces today.
- **No vector-DB projection (UMAP/t-SNE) yet.** Planned as the next view — useful for spotting semantic clusters and near-duplicates.
- **No scan diff.** Comparing two runs is a separate feature.

"""FastMCP server — thin wrapper over :class:`CodeIndex`.

Each tool delegates to a single CodeIndex method, so the MCP, HTTP and
CLI surfaces stay consistent. The index is created once at module load
and reused across tool calls (single-threaded stdio loop — one
connection per process).
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from bindwood import CodeIndex


_INDEX: CodeIndex | None = None


def _index() -> CodeIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = CodeIndex()
    return _INDEX


mcp = FastMCP(
    "code-graph",
    instructions=(
        "You have access to a code graph database containing structural and "
        "semantic information about a multi-target codebase.\n"
        "The database contains:\n"
        "- JS/TS/Python code: functions, classes, exports, imports, calls\n"
        "- DDL schema: tables, views, enums, foreign key relationships\n"
        "- Auxiliary-model summaries and vector embeddings for semantic search\n\n"
        "Workflow for answering code questions:\n"
        "1. Call `graph_overview` once to see what's indexed\n"
        "2. Use `search_code` for natural-language discovery\n"
        "3. Use `find_nodes` when you know the type/name\n"
        "4. Use `get_node_detail` to read a node's source\n"
        "5. Use `get_neighbors` (1 hop) or `slice_graph` (N hops) to traverse\n"
        "6. Use `trace_path` to find how two nodes connect\n\n"
        "Targets represent different applications/services in the project."
    ),
)


@mcp.tool()
def graph_overview() -> str:
    """Targets, node/edge counts, and coverage stats. Call this first."""
    return json.dumps(_index().overview(), indent=2)


@mcp.tool()
def search_code(query: str, limit: int = 10, target: str | None = None) -> str:
    """Semantic search across all embedded nodes.

    Args:
        query: Natural-language description (e.g. "user authentication").
        limit: Max results (default 10).
        target: Optional target name filter.
    """
    try:
        results = _index().search(query, limit=limit, target=target)
    except RuntimeError as e:
        return f"Error: {e}"
    return json.dumps(results, indent=2)


@mcp.tool()
def find_nodes(
    type: str | None = None,
    name: str | None = None,
    target: str | None = None,
    file: str | None = None,
    label: str | None = None,
    limit: int = 20,
) -> str:
    """Find nodes by structured filters.

    Args:
        type: Node type (function, class, export, call, file, table, view, ...).
        name: Name pattern (``%%`` as wildcard).
        target: Target name.
        file: File path pattern.
        label: Semantic label on calls (e.g. http_route, db_access).
        limit: Max results.
    """
    try:
        results = _index().find_nodes(
            type=type, name=name, target=target, file=file, label=label, limit=limit
        )
    except ValueError as e:
        return f"Error: {e}"
    return json.dumps(results, indent=2)


@mcp.tool()
def get_node_detail(node_id: str, target: str | None = None) -> str:
    """Full node record including source_text.

    Args:
        node_id: Full or partial node ID.
        target: Optional target name to disambiguate.
    """
    return json.dumps(_index().get_node(node_id, target=target), indent=2)


@mcp.tool()
def get_neighbors(
    node_id: str,
    target: str | None = None,
    direction: str = "both",
    edge_type: str | None = None,
) -> str:
    """One-hop neighbors of a node.

    Args:
        node_id: Full or partial node ID.
        target: Optional target name.
        direction: "in", "out", or "both".
        edge_type: Filter: imports, exports, contains, fk, depends_on, extends, ...
    """
    try:
        return json.dumps(
            _index().get_neighbors(
                node_id, target=target, direction=direction, edge_type=edge_type
            ),
            indent=2,
        )
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
def slice_graph(
    seeds: list[str],
    depth: int = 2,
    direction: str = "out",
    edge_kinds: list[str] | None = None,
    max_nodes: int = 200,
    target: str | None = None,
) -> str:
    """BFS transitive closure around one or more seed nodes.

    Args:
        seeds: Seed node IDs (full or partial).
        depth: Hop budget (default 2).
        direction: "out" (callees), "in" (callers), or "both".
        edge_kinds: Restrict to these edge types (e.g. ["calls", "imports"]).
        max_nodes: Hard cap on discovered nodes.
        target: Optional target name for seed resolution.
    """
    try:
        return json.dumps(
            _index().slice(
                seeds,
                target=target,
                depth=depth,
                direction=direction,
                edge_kinds=edge_kinds,
                max_nodes=max_nodes,
            ),
            indent=2,
        )
    except ValueError as e:
        return f"Error: {e}"


@mcp.tool()
def trace_path(
    from_node: str,
    to_node: str,
    from_target: str | None = None,
    to_target: str | None = None,
    max_depth: int = 3,
) -> str:
    """Find how two nodes connect via BFS (up to 5 hops)."""
    return json.dumps(
        _index().trace_path(
            from_node,
            to_node,
            from_target=from_target,
            to_target=to_target,
            max_depth=max_depth,
        ),
        indent=2,
    )


@mcp.tool()
def get_table_schema(table_name: str) -> str:
    """Full DDL schema for a table including columns, PK, and FK relationships."""
    return json.dumps(_index().get_table_schema(table_name), indent=2)


def run() -> None:
    """Entry point for ``bindwood mcp``."""
    mcp.run()


if __name__ == "__main__":
    run()

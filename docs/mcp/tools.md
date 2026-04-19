# MCP Tools

The MCP server exposes the following tools.

## Summary

| Tool | Purpose | When to use |
|------|---------|-------------|
| `graph_overview` | Database stats: targets, node/edge counts, types. | First call — understand what's available. |
| `search_code` | Semantic similarity search by natural language. | *"Find code related to X"* — broad discovery. |
| `find_nodes` | Structured lookup by type, name, file, label. | When you know what you're looking for. |
| `get_node_detail` | Full node info including source code text. | Read the actual implementation. |
| `get_neighbors` | Graph traversal: edges in/out of a node. | Understand structural relationships. |
| `slice_graph` | BFS transitive closure around seed nodes. | *"What does this module pull in?"* |
| `trace_path` | BFS path finding between two nodes. | *"How does A connect to B?"* |
| `get_table_schema` | DDL table details: columns, PKs, FKs, related tables. | Database schema exploration. |

---

## `search_code`

```text
search_code(query: str, limit: int = 10, target: str | None = None) -> JSON
```

Semantic similarity search. Embeds the query with the same model used at build time and finds the nearest code nodes.

**Parameters**

- `query` — Natural language description (e.g. *"product pricing calculation"*, *"error handling middleware"*).
- `limit` — Max results (default 10).
- `target` — Filter to a specific target (e.g. `"hub4retail-backend"`).

**Returns** — array of matches with `node_id`, `target`, `type`, `name`, `file`, `line`, `distance`, `source_preview`.

---

## `find_nodes`

```text
find_nodes(type, name, target, file, label, limit) -> JSON
```

Structured lookup. At least one filter is required.

**Parameters**

- `type` — Node type: `function`, `class`, `call`, `table`, `interface`, `export`, etc.
- `name` — Name pattern (use `%` as wildcard).
- `target` — Target name.
- `file` — File path pattern (use `%` as wildcard).
- `label` — Semantic label: `http_route`, `db_access`, `auth_check`, `api_call`, etc.
- `limit` — Max results (default 20).

---

## `get_node_detail`

```text
get_node_detail(node_id: str, target: str | None = None) -> JSON
```

Full node details. Supports **partial ID matching** — `"User.login"` will match `func::applications/main/interface/user.js::User.login`.

**Returns** — full node including `properties` dict and `source_text` (the actual code).

---

## `get_neighbors`

```text
get_neighbors(node_id: str, target, direction = "both", edge_type = None) -> JSON
```

Graph traversal.

**Parameters**

- `direction` — `"out"` (outgoing edges), `"in"` (incoming), `"both"`.
- `edge_type` — Filter: `imports`, `exports`, `contains`, `fk`, `depends_on`, `extends`.

**Returns** — `{ outgoing: [...], incoming: [...] }` with full node info for each neighbor.

---

## `slice_graph`

```text
slice_graph(
  seeds: list[str],
  depth: int = 2,
  direction: str = "out",
  edge_kinds: list[str] | None = None,
  max_nodes: int = 200,
  target: str | None = None
) -> JSON
```

BFS transitive closure starting from one or more seed nodes. Useful for understanding the full dependency footprint of a module or function.

**Parameters**

- `seeds` — List of node IDs (full or partial) to start the traversal from.
- `depth` — Max hops (default 2).
- `direction` — `"out"` (dependencies), `"in"` (dependents), or `"both"`.
- `edge_kinds` — Restrict traversal to specific edge types: `imports`, `exports`, `contains`, `fk`, `depends_on`, `extends`.
- `max_nodes` — Hard cap to prevent run-away traversals (default 200).
- `target` — Filter seed resolution to a specific target.

**Returns** — `{ seeds[], nodes[], edges[], stats{ node_count, edge_count, max_depth_reached }, truncated }`.

---

## `trace_path`

```text
trace_path(from_node, to_node, from_target, to_target, max_depth = 3) -> JSON
```

BFS path finding between two nodes. Searches up to `max_depth` hops (default 3; increase for distant nodes).

**Returns** — `{ found: bool, hops: int, path: [...] }` with each step showing the node and edge traversed.

---

## `get_table_schema`

```text
get_table_schema(table_name: str) -> JSON
```

Full DDL table info.

**Returns** — `{ table, columns[], primary_key[], unique_constraints[], references[], referenced_by[] }`.

---

## `graph_overview`

```text
graph_overview() -> JSON
```

Database summary.

**Returns** — `{ targets[], node_counts_by_type, edge_counts_by_type, total_nodes, nodes_with_source_text, nodes_with_embeddings }`.

# Using bindwood as a Library

bindwood can be used as a Python library — import the `Bindwood` class and use it directly in your own application without going through the CLI.

```python
from bindwood import Bindwood
```

## Quick example

```python
from bindwood import Bindwood

bw = Bindwood()

# --- Config management ---
# Create the config file (once per machine)
bw.create_config(
    ollama_url="http://localhost:11434",
    embedding_model="nomic-embed-text",
    auxiliary_model="qwen2.5-coder:1.5b",
    db_path="graph/code_graph.db",
)

# Add a target
bw.add_target({
    "type": "python",
    "name": "my-app",
    "root": "src",
    "include": ["**/*.py"],
})

# Generate an API key for the HTTP server
key = bw.set_api_key()

# --- Pipeline and queries ---
bw.scan()

results = bw.search("user authentication middleware")
for r in results:
    print(r["name"], r["file"], r["distance"])

functions = bw.find(type="function", name="login")
neighbours = bw.neighbors("func::src/auth.ts::login")
```

## Instantiation

```python
# Zero-config — resolves db and config from env / user config dir / defaults
bw = Bindwood()

# Explicit database path
bw = Bindwood(db_path="/path/to/graph/code_graph.db")

# Explicit config and database
bw = Bindwood(
    db_path="/path/to/code_graph.db",
    config_path="/path/to/bindwood.json",
)

# Context manager — closes the DB connection automatically
with Bindwood() as bw:
    print(bw.overview())
```

The database connection is lazy — it is not opened until the first query method is called.

---

## API Reference

### Config management

---

### `reset_config()`

```python
bw.reset_config(*, force=False) -> Path
```

Reset the config file to factory defaults. The existing file is backed up as `config.json.bak` before being overwritten. Raises `FileNotFoundError` only if the config directory itself cannot be created.

Pass `force=True` to skip the backup (useful in automated scripts).

```python
# Safe reset — keeps a .bak copy
bw.reset_config()

# Force reset without backup
bw.reset_config(force=True)
```

Returns the path to the reset config file.

---

### `create_config()`

```python
bw.create_config(
    *,
    ollama_url="http://localhost:11434",
    embedding_model="nomic-embed-text",
    auxiliary_model="qwen2.5-coder:1.5b",
    db_path="graph/code_graph.db",
    overwrite=False,
) -> Path
```

Create the user config file. Writes to the canonical config directory (`$XDG_CONFIG_HOME/bindwood/config.json` on Linux/macOS, `%APPDATA%\bindwood\config.json` on Windows). Returns the path written.

Raises `FileExistsError` if a config already exists and `overwrite=False`.

```python
path = bw.create_config(db_path="/data/myproject/code_graph.db")
print(f"Config written to {path}")

# Replace an existing config
bw.create_config(embedding_model="mxbai-embed-large", overwrite=True)
```

---

### `get_config()`

```python
bw.get_config() -> dict
```

Return the active config dict (same resolver chain as the CLI: env var → user config dir → `./bindwood.json`).

```python
cfg = bw.get_config()
print(cfg["ollama"]["embedding_model"])
print([t["name"] for t in cfg["targets"]])
```

---

### `add_target()`

```python
bw.add_target(target: dict, *, overwrite=False) -> None
```

Add a target to the config. `target` must contain at minimum `"type"` and `"name"`. See the configuration reference for the full schema per type: [DDL](configuration/ddl-targets.md), [JS/TS](configuration/jsts-targets.md), [Python](configuration/python-targets.md).

Raises `ValueError` if the name already exists and `overwrite=False`.

```python
# Python target
bw.add_target({
    "type": "python",
    "name": "my-backend",
    "root": "services/api",
    "output": "graph/my-backend_graph.json",
    "include": ["**/*.py"],
    "exclude": ["**/__pycache__/**", "**/.venv/**"],
})

# TypeScript target
bw.add_target({
    "type": "typescript",
    "name": "my-frontend",
    "root": "services/web/src",
    "include": ["**/*.ts", "**/*.tsx"],
    "resolve": {"tsconfig": "tsconfig.json"},
})

# Replace an existing target
bw.add_target({"type": "python", "name": "my-backend", "root": "."}, overwrite=True)
```

---

### `get_target()`

```python
bw.get_target(name: str) -> dict | None
```

Return a single target's definition from the config, or `None` if no target with that name exists. Handy for reading current values before calling `update_target`.

```python
t = bw.get_target("my-backend")
if t:
    print(t["root"], t["include"])
```

---

### `update_target()`

```python
bw.update_target(name: str, updates: dict) -> dict
```

Update fields on an existing target in-place. `updates` is shallow-merged onto the current definition — keys you pass replace the old values, keys you omit are kept as-is. Returns the merged target dict.

The target name is **immutable**: database rows are keyed by name, so a rename would orphan them. Use `delete_target` + `add_target` to rebuild under a new name. Raises `ValueError` if no target with that name exists, or if `updates["name"]` differs from `name`.

```python
# Flip a DDL target from postgres to mysql after realising the dump is MySQL
bw.update_target("my-dump", {"dialect": "mysql"})

# Extend the include list on a Python target
current = bw.get_target("my-backend")
bw.update_target("my-backend", {
    "include": current["include"] + ["tests/**/*.py"],
})
```

Pair with `rescan()` to rebuild just the affected target's graph, summaries, and embeddings without wiping the whole database.

---

### `delete_target()`

```python
bw.delete_target(name: str) -> bool
```

Remove a target from the config by name. Returns `True` if removed, `False` if no target with that name existed. The database is rebuilt from scratch on the next `scan()` call — the deleted target's rows are purged then.

```python
removed = bw.delete_target("old-service")
if not removed:
    print("Target not found")
```

---

### `set_api_key()`

```python
bw.set_api_key(key=None) -> str
```

Generate (or store a provided) HTTP server API key under `server.api_key` in the config. If `key=None` (default), a random URL-safe 32-byte token is generated. Returns the key that was stored.

The `BINDWOOD_API_KEY` environment variable always takes precedence over the config value at runtime.

```python
# Auto-generate
key = bw.set_api_key()
print(f"Key: {key}")

# Store a specific key
bw.set_api_key("my-secret-key")
```

---

### `get_api_key()`

```python
bw.get_api_key() -> str | None
```

Return the stored API key, or `None` if none has been set.

```python
key = bw.get_api_key()
if key:
    headers = {"Authorization": f"Bearer {key}"}
```

---

### `clear_api_key()`

```python
bw.clear_api_key() -> bool
```

Remove the stored API key from the config. Returns `True` if a key was removed, `False` if there was nothing to remove.

```python
bw.clear_api_key()  # HTTP server now open (no auth required)
```

---

### Pipeline and queries

---

### `scan()`

```python
bw.scan(verbose=False) -> bool
```

Run the full extraction pipeline: extract graphs from all configured targets, rebuild the SQLite database, generate per-node summaries (`qwen2.5-coder:1.5b`), and produce vector embeddings (`nomic-embed-text`). Returns `True` on success, `False` on failure.

```python
ok = bw.scan()
if not ok:
    print("Scan failed — check your config and targets")
```

---

### `rescan()`

```python
bw.rescan(name: str, *, verbose=False) -> bool
```

Re-run the pipeline for a single target. Only the named target's graph, summaries, and embeddings are rebuilt — other targets in the database are preserved. Use this after an interrupted scan, or after calling `update_target` to pick up the new configuration without wiping everything else.

Returns `True` on success, `False` on failure. Raises `ValueError` if no target with that name exists.

```python
# Recover one project after an interrupted scan
bw.rescan("my-backend")

# Edit + rescan in sequence
bw.update_target("my-dump", {"dialect": "mysql"})
bw.rescan("my-dump")
```

---

### `overview()`

```python
bw.overview() -> dict
```

Database summary: targets, node and edge counts by type, embedding coverage.

```python
info = bw.overview()
print(info["total_nodes"])
print(info["targets"])          # [{"name": ..., "type": ..., "root": ...}]
print(info["node_counts_by_type"])  # {"function": 412, "class": 38, ...}
```

---

### `search()`

```python
bw.search(query, *, limit=10, target=None) -> list[dict]
```

Semantic similarity search. Requires Ollama running with the configured embedding model.

```python
results = bw.search("database connection pooling", limit=5)
results = bw.search("error handling", target="my-backend")
```

Each result: `{node_id, target, type, name, file, line, distance, summary, source_preview}`.

Raises `RuntimeError` if Ollama is unreachable.

---

### `find()`

```python
bw.find(*, type=None, name=None, target=None, file=None, label=None, limit=20) -> list[dict]
```

Structured lookup. At least one filter is required. `%` is the wildcard in `name` and `file` patterns.

```python
# All functions named "validate" across all targets
bw.find(type="function", name="validate")

# HTTP route calls in a specific target
bw.find(type="call", label="http_route", target="my-api")

# All tables with "order" in the name
bw.find(type="table", name="%order%")
```

Each result: `{node_id, target, type, name, file, line, summary}`.

---

### `node()`

```python
bw.node(node_id, *, target=None) -> list[dict]
```

Look up a node by ID. Accepts a full ID or a substring — returns all partial matches (up to 5).

```python
# Full ID
bw.node("func::src/auth.ts::login")

# Partial match — returns all nodes whose ID contains "login"
bw.node("login")
```

Each result includes `source_text` (the actual code) and `properties`.

---

### `neighbors()`

```python
bw.neighbors(node_id, *, target=None, direction="both", edge_type=None) -> dict
```

One-hop graph traversal.

```python
# Everything connected to a node
bw.neighbors("func::src/auth.ts::login")

# Only what this node imports
bw.neighbors("file::src/index.ts", direction="out", edge_type="imports")

# Everything that calls this function
bw.neighbors("func::src/auth.ts::login", direction="in")
```

Returns `{node_id, target, outgoing: [...], incoming: [...]}`.

---

### `slice()`

```python
bw.slice(seeds, *, depth=2, direction="out", edge_kinds=None, max_nodes=200, target=None) -> dict
```

BFS transitive closure — the full dependency graph of a node up to `depth` hops.

```python
# Full import tree of a file, 3 hops deep
bw.slice("file::src/index.ts", depth=3)

# Everything that depends on this module (reverse direction)
bw.slice("file::src/auth.ts", direction="in", depth=2)

# Follow only import edges from multiple seeds
bw.slice(
    ["file::src/api.ts", "file::src/db.ts"],
    edge_kinds=["imports"],
    depth=3,
)
```

Returns `{seeds, nodes, edges, stats{node_count, edge_count, max_depth_reached}, truncated}`.

---

### `trace()`

```python
bw.trace(from_node, to_node, *, from_target=None, to_target=None, max_depth=3) -> dict
```

Find the shortest path between two nodes via BFS (hard-capped at 5 hops).

```python
result = bw.trace("file::src/routes.ts", "file::src/db/queries.ts")
if result["found"]:
    for step in result["path"]:
        print(step["name"], "->", step.get("edge", ""))
```

Returns `{found, hops, path}` or `{found: False, message}`.

---

### `table_schema()`

```python
bw.table_schema(table_name) -> dict
```

Full DDL schema for a table.

```python
schema = bw.table_schema("orders")
print(schema["columns"])
print(schema["primary_key"])
print(schema["references"])     # FK outgoing
print(schema["referenced_by"])  # FK incoming
```

---

### `mcp_path()`

```python
Bindwood.mcp_path() -> Path
```

Static method. Returns the absolute path to `bindwood/servers/mcp.py`. Useful for generating a Claude Code `mcpServers` config block programmatically.

```python
import json
from bindwood import Bindwood

config = {
    "mcpServers": {
        "code-graph": {
            "command": "python",
            "args": [str(Bindwood.mcp_path())],
            "env": {"BINDWOOD_DB": "/path/to/code_graph.db"},
        }
    }
}
print(json.dumps(config, indent=2))
```

---

### `serve_mcp()`

```python
bw.serve_mcp()
```

Start the MCP stdio server (blocking). This is the same process Claude Code spawns automatically — call it directly only for testing or non-Claude MCP clients.

---

### `serve_http()`

```python
bw.serve_http(*, host="127.0.0.1", port=8765, reload=False)
```

Start the FastAPI HTTP server (blocking). Requires `pip install 'bindwood[http]'`.

```python
bw.serve_http(host="0.0.0.0", port=9000)
```

---

## Full pipeline example

```python
from bindwood import Bindwood

with Bindwood(db_path="graph/code_graph.db") as bw:
    # 1. Build the database
    bw.scan()

    # 2. Explore what was indexed
    info = bw.overview()
    print(f"Indexed {info['total_nodes']} nodes across {len(info['targets'])} targets")

    # 3. Find entry points
    routes = bw.find(type="call", label="http_route", target="my-api")
    print(f"Found {len(routes)} HTTP routes")

    # 4. Inspect one
    detail = bw.node(routes[0]["node_id"])
    print(detail[0]["source_text"])

    # 5. Trace what it depends on
    subgraph = bw.slice(routes[0]["node_id"], depth=2)
    print(f"Depends on {subgraph['stats']['node_count']} nodes")
```

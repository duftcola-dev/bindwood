# Quick Start

This guide takes you from zero to a queryable graph in under five minutes.

## 1. Create a config

Config files are not meant to be hand-edited — `bindwood init` writes a fresh one to the canonical user config dir (`%APPDATA%\bindwood\config.json` on Windows, `$XDG_CONFIG_HOME/bindwood/config.json` elsewhere) and walks you through the first target interactively:

```bash
bindwood init
```

You'll be prompted for Ollama URL, embedding model, auxiliary (summary) model, the database path, and your first target definition.

Add more targets later with:

```bash
bindwood add
```

Inspect the active config at any time with:

```bash
bindwood list
```

Remove a target (config-only — the DB is rebuilt on the next scan):

```bash
bindwood delete my-target
```

## 2. Scan a codebase

```bash
# Full pipeline: extract graphs + load into SQLite + generate embeddings
bindwood scan
```

This runs three phases:

1. **Extract** — tree-sitter / sqlglot parse every configured target into a graph JSON
2. **Load** — rebuild `graph/code_graph.db` from the JSON graphs
3. **Embed** — send `source_text` to Ollama, store vectors in `sqlite-vec`

Skip embeddings if Ollama isn't available:

```bash
bindwood scan --no-embeddings
```

Scan only a specific target:

```bash
bindwood scan --target my-app
```

!!! warning "Ollama watchdog"
    Every `bindwood` command prints a `[warn]` line to stderr if Ollama isn't reachable at the configured URL. Embeddings and summaries are silently skipped in that case — the structural graph still builds.

## 3. Query the database

```bash
bindwood query stats
bindwood query search "authentication login"
bindwood query find --type function --name login
bindwood query neighbors "table::product"
bindwood query slice "file::src/index.ts" --depth 2
```

Full command reference: [CLI → Query Reference](../cli/query.md).

## 4. Start the MCP server

Expose the graph as MCP tools Claude can call:

```bash
bindwood mcp
```

Then wire it into Claude Code — see [MCP Server → Setup](../mcp/setup.md).

## 5. (Optional) HTTP server

If you installed the `[http]` extra:

```bash
bindwood apikey                          # generate + store an API key
bindwood serve --host 127.0.0.1 --port 8765
```

The `BINDWOOD_API_KEY` env var always wins over the stored key.

## 6. (Optional) Browser visualization

If you installed the `[viz]` extra:

```bash
bindwood serve --host 127.0.0.1 --port 8765
# → open http://127.0.0.1:8765/viz/
```

Three tabs per target — **Graph** (file-level force-directed), **Skeleton** (directory treemap), **Labels** (directory × label heatmap). See [Visualization](../viz/index.md).

## Config resolution order

The CLI always writes to the user config dir, so in normal use you never think about this. Library callers and power users can override via the resolver chain — first match wins:

1. Explicit `--config` passed to library callers
2. `BINDWOOD_CONFIG` environment variable
3. User config dir (`%APPDATA%\bindwood\config.json` / `$XDG_CONFIG_HOME/bindwood/config.json`) — **canonical**
4. `./bindwood.json` in the current directory (repo-local override)
5. Legacy in-repo default: `bindwood/config/config.json` (source checkouts)

Legacy `GTG_CONFIG` / `GTG_DB` / `GTG_API_KEY` / `gtg.json` still work for one deprecation cycle.

A config managed by the CLI looks roughly like:

```json
{
  "version": 1,
  "ollama": {
    "url": "http://localhost:11434",
    "embedding_model": "nomic-embed-text",
    "auxiliary_model": "gemma4:e4b"
  },
  "database": { "path": "graph/code_graph.db" },
  "targets": [
    {
      "type": "typescript",
      "name": "my-app",
      "root": "src",
      "include": ["**/*.ts", "**/*.tsx"]
    }
  ]
}
```

Full reference: [Configuration → Overview](../configuration/index.md).

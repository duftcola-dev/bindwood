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

Edit an existing target (each field is pre-filled — press Enter to keep it):

```bash
bindwood edit                # pick from an indexed list
bindwood edit my-target      # skip the selector
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

This runs four phases:

1. **Extract** — tree-sitter / sqlglot parse every configured target into a graph JSON
2. **Load** — rebuild `graph/code_graph.db` from the JSON graphs
3. **Summarise** — call the auxiliary model (`qwen2.5-coder:1.5b` by default) to write a one-line summary for each node
4. **Embed** — call the embedding model (`nomic-embed-text` by default) and store vectors in `sqlite-vec`

The two Ollama models serve distinct roles and fail independently:

| Model | Role | If unavailable |
|-------|------|---------------|
| `nomic-embed-text` | Produces vector embeddings — required for `search_code` and `context` queries | Embeddings are skipped; structural queries (`find`, `neighbors`, `slice`) still work |
| `qwen2.5-coder:1.5b` | Generates per-node summaries shown in query output and search results | Summaries are skipped; everything else still works |

Pull both models before scanning for the full experience:

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5-coder:1.5b
```

Pass `--verbose` / `-v` to print full tracebacks on error:

```bash
bindwood scan --verbose
```

To rebuild **one** target only — e.g. after editing it, or to recover from an interrupted run — use `rescan`:

```bash
bindwood rescan               # pick from an indexed list
bindwood rescan my-target     # skip the selector
bindwood rescan my-target --force   # skip the confirmation prompt
```

Only the named target's rows are purged and rebuilt; other targets in the database are untouched.

Run `bindwood doctor` to check both models and the rest of your setup in one go.

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

## 4. Wire up the MCP server

`bindwood mcp` is a **stdio MCP server** — you never run it manually. Claude Code spawns the server file automatically using the path you register in its settings. Get that path first:

```bash
bindwood mcp-path
# → /absolute/path/to/bindwood/servers/mcp.py
```

Then add it to your Claude Code settings:

```json title=".claude/settings.local.json"
{
  "mcpServers": {
    "code-graph": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/absolute/path/to/bindwood",
        "python", "bindwood/servers/mcp.py"
      ],
      "env": {
        "BINDWOOD_DB": "/absolute/path/to/your/graph/code_graph.db"
      }
    }
  }
}
```

After saving the file and restarting Claude Code, the tools appear automatically. You can run `bindwood mcp` directly in a terminal only as a smoke-test to confirm the server starts without errors.

Full setup options and verification steps: [MCP Server → Setup](../mcp/setup.md).

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

Legacy `GTG_CONFIG` / `GTG_DB` / `GTG_API_KEY` / `gtg.json` still work for one deprecation cycle.

A config managed by the CLI looks roughly like:

```json
{
  "version": 1,
  "ollama": {
    "url": "http://localhost:11434",
    "embedding_model": "nomic-embed-text",
    "auxiliary_model": "qwen2.5-coder:1.5b"
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

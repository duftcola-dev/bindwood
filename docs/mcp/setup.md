# MCP Server — Setup

`bindwood mcp` is a **stdio MCP server**. You register it in Claude Code's settings and Claude Code spawns the process automatically — you never start it manually.

## 1. Add to Claude Code settings

Claude Code reads this config, spawns `bindwood mcp` as a subprocess, and connects to it over stdio. `BINDWOOD_DB` is an environment variable passed to the **server process** so it knows where to find its SQLite database — Claude itself only ever sees the MCP tools the server exposes.

=== "Project-level (`.claude/settings.local.json`)"

    ```json
    {
      "mcpServers": {
        "code-graph": {
          "command": "bindwood",
          "args": ["mcp"],
          "env": {
            "BINDWOOD_DB": "/absolute/path/to/your/graph/code_graph.db"
          }
        }
      }
    }
    ```

=== "Source checkout (via `uv`)"

    ```json
    {
      "mcpServers": {
        "code-graph": {
          "command": "uv",
          "args": ["run", "--directory", "/path/to/bindwood/checkout", "bindwood", "mcp"]
        }
      }
    }
    ```

=== "Global (`~/.claude/settings.json`)"

    Use the same shape as the project-level config, but place it in your global settings file.

## 2. Verify

Restart Claude Code after editing the settings file. Claude Code reads the config, spawns `bindwood mcp` over stdio, and the tools register automatically.

Ask Claude:

> *"What tools do you have from code-graph?"*

You should see: `graph_overview`, `search_code`, `find_nodes`, `get_node_detail`, `get_neighbors`, `slice_graph`, `trace_path`, `get_table_schema`.

## Prerequisites

- **Database must exist** — run `bindwood scan` at least once before wiring up the server.
- **`BINDWOOD_DB` must be an absolute path** — relative paths break because Claude Code may spawn the process from a different working directory.
- **Ollama is only needed for semantic search** — `search_code` embeds the query at call time, so Ollama must be reachable when Claude calls that tool. Structural tools (`find_nodes`, `get_neighbors`, `slice_graph`, etc.) work without it.

## HTTP server (optional)

If you installed the `[http]` extra, you can expose the same graph over HTTP — useful for non-Claude clients or browser-based access:

```bash
bindwood apikey             # generate an API key (stored in the config)
bindwood serve --host 127.0.0.1 --port 8765
```

Authentication is via `Authorization: Bearer <key>`. The `BINDWOOD_API_KEY` env var always takes precedence over the config value.

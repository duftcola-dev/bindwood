# MCP Server — Setup

`bindwood mcp` is a **stdio MCP server**. You register it in Claude Code's settings and Claude Code spawns the process automatically — you never start it manually.

## 1. Generate the config snippet

Run this once — it prints the MCP server file path **and** a ready-to-paste JSON block with your actual database path already filled in:

```bash
bindwood mcp-path
```

Example output:

```
MCP server file: /home/you/repos/bindwood/bindwood/servers/mcp.py

Add this to .claude/settings.local.json (project) or ~/.claude/settings.json (global):

{
  "mcpServers": {
    "code-graph": {
      "command": "python",
      "args": ["/home/you/repos/bindwood/bindwood/servers/mcp.py"],
      "env": {
        "BINDWOOD_DB": "/home/you/repos/bindwood/graph/code_graph.db"
      }
    }
  }
}
```

Copy that JSON block directly into your settings file — no manual path editing required.

## 2. Add to Claude Code settings

Claude Code reads this config and spawns the server file as a subprocess over stdio. `BINDWOOD_DB` is an environment variable passed to the **server process** so it knows where to find its SQLite database — Claude itself only ever sees the MCP tools the server exposes, never the database directly.

=== "Source checkout (via `uv`)"

    Use the snippet from `bindwood mcp-path` — it already contains the correct paths.
    If you need to build it manually:

    ```json
    {
      "mcpServers": {
        "code-graph": {
          "command": "python",
          "args": ["/absolute/path/to/bindwood/bindwood/servers/mcp.py"],
          "env": {
            "BINDWOOD_DB": "/absolute/path/to/your/graph/code_graph.db"
          }
        }
      }
    }
    ```

=== "Installed via pip"

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

=== "Global (`~/.claude/settings.json`)"

    Use the same shape as either tab above, placed in your global settings file instead.

## 3. Verify

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

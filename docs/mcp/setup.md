# MCP Server — Setup

The MCP (Model Context Protocol) server exposes the code graph as tools that Claude can call directly. This is the key integration that allows Claude to navigate large codebases efficiently.

## 1. Add to Claude Code settings

Add the server to your MCP configuration.

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

After restarting Claude Code, the tools should appear. Ask Claude:

> *"What tools do you have from code-graph?"*

You should see: `graph_overview`, `search_code`, `find_nodes`, `get_node_detail`, `get_neighbors`, `trace_path`, `get_table_schema`.

## Prerequisites

- The database must exist — `bindwood scan` must have been run at least once.
- For semantic search tools (`search_code`), Ollama must be running with the configured embedding model.

## HTTP server (optional)

If you installed the `[http]` extra, you can expose the same graph over HTTP:

```bash
bindwood apikey             # generate an API key (stored in the config)
bindwood serve --host 127.0.0.1 --port 8765
```

This is useful for non-Claude clients or remote access. Authentication is via the generated API key; the `BINDWOOD_API_KEY` env var always wins over the stored value.

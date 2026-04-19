# bindwood

**Tree-sitter-based static analysis that turns codebases into a queryable graph + vector index, exposed to LLMs via MCP.**

bindwood parses source files into ASTs and produces a graph of **nodes** (files, functions, classes, calls, exports, types, tables, views) and **edges** (imports, contains, exports, extends, FK relationships). The graph is enriched with **source code text** and **vector embeddings** (via Ollama), then stored in a single SQLite file.

The result is a `.db` an LLM can query through an MCP server to navigate codebases efficiently — structural traversal for *"where is it?"* and vector search for *"what does it do?"* — replacing blind file exploration with targeted O(1) lookups.

---

## Install

```bash
# From a source checkout
uv sync

# Or install from PyPI
pip install bindwood                # core + MCP + CLI
pip install "bindwood[http]"        # with FastAPI HTTP server
pip install "bindwood[docs]"        # with MkDocs + Material theme
```

Requires Python >= 3.10. [Ollama](https://ollama.ai/) is optional but recommended for semantic search.

## Quick start

```bash
# Create the config (interactive, writes to your user config dir)
bindwood init

# Full pipeline: extract graphs + load into SQLite + generate embeddings
bindwood scan

# Query the database
bindwood query stats
bindwood query search "authentication login"
bindwood query find --type function --name login

# Start the MCP server (for Claude Desktop / Claude Code)
bindwood mcp
```

> Config files are managed through the CLI (`bindwood init`, `add`, `list`, `delete`) — you shouldn't need to hand-edit JSON.

## Documentation

Full documentation lives in [`docs/`](./docs) and is published as an MkDocs site.

To serve it locally:

```bash
pip install "bindwood[docs]"
mkdocs serve
# → http://127.0.0.1:8000
```

Highlights:

- [Getting Started](./docs/getting-started/installation.md)
- [Configuration Reference](./docs/configuration/index.md)
- [Extractor Pipeline & Label Patterns](./docs/extractors/pipeline.md)
- [Database & Embeddings](./docs/database/pipeline.md)
- [Query CLI](./docs/cli/query.md)
- [MCP Server](./docs/mcp/setup.md)
- [Troubleshooting](./docs/troubleshooting.md)

## License

See [LICENSE](./LICENSE).

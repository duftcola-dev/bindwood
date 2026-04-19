# Installation

## Requirements

- **Python >= 3.10**
- **[uv](https://docs.astral.sh/uv/)** — package manager (recommended)

Optional, for embeddings:

- **[Ollama](https://ollama.ai/)** running locally with an embedding model pulled

## Dependencies

Installed automatically by `uv` or `pip`:

| Package | Purpose |
|---------|---------|
| `tree-sitter` | Core AST parsing engine |
| `tree-sitter-javascript` | JavaScript grammar (`.js`, `.jsx`, `.mjs`, `.cjs`) |
| `tree-sitter-typescript` | TypeScript grammar (`.ts`, `.tsx`, `.mts`) |
| `tree-sitter-python` | Python grammar (`.py`) |
| `sqlglot` | DDL/SQL parsing for the database extractor |
| `sqlite-vec` | Vector similarity search extension for SQLite |
| `mcp` | Model Context Protocol SDK for Claude integration |

## Install

=== "From source (uv)"

    ```bash
    git clone https://github.com/your-org/bindwood.git
    cd bindwood
    uv sync
    ```

=== "From PyPI (pip)"

    ```bash
    pip install bindwood                # core + MCP + CLI
    pip install "bindwood[http]"        # with FastAPI HTTP server
    pip install "bindwood[viz]"         # with the browser visualization UI (implies [http])
    pip install "bindwood[docs]"        # with MkDocs + Material theme
    ```

The CLI is installed as `bindwood`; you can also invoke it via `python -m bindwood`.

## Verify

```bash
bindwood --help
```

You should see the top-level commands: `init`, `add`, `list`, `delete`, `apikey`, `scan`, `query`, `mcp`, `serve`, `ollama-status`.

## Install Ollama (optional)

Embeddings are optional but highly recommended — semantic search is what makes bindwood more than just a graph.

```bash
# https://ollama.ai/download
ollama pull nomic-embed-text
```

The pipeline auto-pulls the configured model if it's missing, so this step is optional in practice.

!!! warning "Use an embedding model, not a generative model"
    Generative models (Qwen, Llama, etc.) cannot produce useful embeddings. See [Embeddings → Ollama Setup](../database/embeddings.md#ollama-setup) for the recommended list.

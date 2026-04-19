# Installation

## Requirements

- **Python >= 3.10**
- **[uv](https://docs.astral.sh/uv/)** — package manager (recommended)

Optional, for embeddings and summaries:

- **[Ollama](https://ollama.ai/)** running locally with the models below pulled

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

You should see the top-level commands: `init`, `add`, `list`, `delete`, `apikey`, `scan`, `query`, `mcp`, `serve`, `doctor`.

## Install Ollama (optional)

Ollama powers two independent features. Neither is required for the structural graph to build, but both are recommended.

| Model | Purpose | If missing |
|-------|---------|------------|
| `nomic-embed-text` | Vector embeddings — enables `search_code` and `context` queries | Semantic search unavailable; structural queries still work |
| `gemma4:e4b` | Per-node summaries shown in query output and search results | Summaries skipped; everything else still works |

```bash
# https://ollama.ai/download
ollama pull nomic-embed-text
ollama pull gemma4:e4b
```

Both models are auto-pulled during `bindwood scan` if missing and Ollama is reachable. Pull them manually beforehand to avoid the delay on first scan.

!!! warning "Use an embedding model for embeddings"
    `nomic-embed-text` is an embedding model. Do not replace it with a generative model (Qwen, Llama, etc.) — generative models cannot produce useful embeddings. See [Embeddings → Ollama Setup](../database/embeddings.md#ollama-setup) for alternatives.

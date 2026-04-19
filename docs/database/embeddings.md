# Embeddings

Vector embeddings turn `source_text` into 768-dimension float vectors that `sqlite-vec` can search by cosine distance. This is what powers `bindwood query search` and the `search_code` MCP tool.

## Ollama setup

The pipeline uses [Ollama](https://ollama.ai/) to run embedding models locally. No API keys or external services required.

```bash
# Install Ollama (https://ollama.ai/download)
ollama pull nomic-embed-text
```

The pipeline auto-pulls the configured model if it's not present, so manual pulling is optional.

!!! warning "Use an embedding model, not a generative model"
    Embedding models are small (100–300M params), fast, and produce fixed-dimension vectors. Generative models (Qwen, Llama, etc.) are for text generation and cannot produce useful embeddings.

### Recommended embedding models

| Model | Params | Dimensions | Notes |
|-------|--------|------------|-------|
| `nomic-embed-text` | 137M | 768 | Good default, fast. |
| `nomic-embed-text-v2-moe` | — | 768 | Newer MoE variant. |
| `mxbai-embed-large` | 335M | 1024 | Higher quality, slower. |

If you pick a model with dimensions other than 768, update `FLOAT[768]` in `bindwood/db/schema.py` to match.

---

## Configuration

In `config.json`:

```json
{
  "ollama": {
    "url": "http://localhost:11434",
    "model": "nomic-embed-text"
  }
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `url` | `http://localhost:11434` | Ollama API endpoint. |
| `model` | `nomic-embed-text` | Embedding model to use. |

---

## How it works

1. The pipeline selects all nodes with non-empty `source_text` from the database.
2. Texts are sent to Ollama in batches of 32 via the `/api/embed` endpoint.
3. Each returned 768-dimension vector is stored in the `vec_embeddings` virtual table.
4. At query time, the search query is embedded with the **same model**, then `sqlite-vec` finds the nearest vectors using cosine distance.

This enables natural-language queries like *"find code that handles user authentication"* to return the most semantically relevant functions, classes, and types across the entire codebase.

## What gets embedded

Only nodes with captured source text:

- `function`, `class`
- `interface`, `type_alias`, `enum`
- `table`, `view`, `materialized_view` (DDL nodes get a structured description, not raw SQL)

Files, calls, exports, and edges are **not embedded**, but remain queryable through graph traversal and structured lookups.

## Troubleshooting

- **Ollama unreachable** — the pipeline skips embeddings and continues. Run `bindwood scan` again after starting Ollama to backfill the vector index.
- **Model not found** — auto-pull is attempted; if it fails, pull manually: `ollama pull <model>`.
- **Stale vectors after schema change** — rerun `bindwood scan` (the DB is rebuilt from scratch each time).
- **Search returns unrelated matches** — ensure the same model is used for indexing and querying; a mismatch returns garbage. Also consider a bigger model (`mxbai-embed-large`) for higher quality.

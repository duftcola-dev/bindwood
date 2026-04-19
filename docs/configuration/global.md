# Global Config

The top-level fields of `config.json` control defaults shared across every target.

## Schema

```json
{
  "version": 1,
  "ollama": {
    "url": "http://localhost:11434",
    "model": "nomic-embed-text"
  },
  "database": {
    "path": "graph/code_graph.db"
  },
  "targets": [ ... ]
}
```

## Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `version` | int | `1` | Config schema version. |
| `ollama.url` | string | `"http://localhost:11434"` | Ollama API endpoint. |
| `ollama.model` | string | `"nomic-embed-text"` | Embedding model name (must be an embedding model, not a generative one). |
| `database.path` | string | `"graph/code_graph.db"` | SQLite output path (relative to workspace root, or absolute). |
| `targets` | array | — | List of extraction targets. See [DDL Targets](ddl-targets.md) and [JS/TS Targets](jsts-targets.md). |

!!! note "Embedding dimensions"
    The default model `nomic-embed-text` produces **768-dim** vectors. If you switch to a model with different dimensions, update `FLOAT[768]` in `bindwood/db/schema.py` to match.

## Legacy single-target format

bindwood also accepts a single-target JSON document at the top level (no `version` / `targets` wrapper). The tool auto-detects this for backwards compatibility, but new projects should prefer the full format above.

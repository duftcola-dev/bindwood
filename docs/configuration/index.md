# Configuration

bindwood is driven by a single JSON config file. It specifies global settings (Ollama, database path) and a list of **targets** — one per codebase or DDL file you want to extract.

## Structure

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
    { "type": "ddl",        "name": "...", ... },
    { "type": "javascript", "name": "...", ... },
    { "type": "typescript", "name": "...", ... },
    { "type": "python",     "name": "...", ... }
  ]
}
```

You can also pass a single-target JSON file (legacy format) — the tool auto-detects it.

## Reference

<div class="grid cards" markdown>

- :material-tune: **[Global Config](global.md)** — top-level settings: Ollama, database path, API key.
- :material-database: **[DDL Targets](ddl-targets.md)** — extract schemas from `.sql` files.
- :material-language-typescript: **[JS/TS Targets](jsts-targets.md)** — the main extractor, with labels, resolver, visitors.
- :material-language-python: **[Python Targets](python-targets.md)** — extract graphs from Python codebases.

</div>

## Where config is loaded from

You shouldn't need to know this in normal use — the CLI (`bindwood init`, `bindwood add`, `bindwood edit`, `bindwood delete`) always writes to the canonical user config dir. Rebuild just one target after an edit with `bindwood rescan <name>`. The resolver chain is:

1. Explicit `--config` passed to library callers
2. `BINDWOOD_CONFIG` environment variable
3. User config dir (`%APPDATA%\bindwood\config.json` on Windows, `$XDG_CONFIG_HOME/bindwood/config.json` elsewhere) — **the canonical location**
4. `./bindwood.json` in the current directory (useful for repo-local overrides)

Legacy `GTG_CONFIG` / `gtg.json` are still accepted for one deprecation cycle.

# Troubleshooting

## "No files found"

- Check that `root` points to the right directory (relative to workspace root, not the config file).
- Verify your `include` globs match actual files. Test with:
  ```bash
  ls services/frontend/hub4retail-brand/src/**/*.tsx
  ```
- Check that `exclude` patterns aren't filtering everything out.

## Missing import edges (many `null` targets)

- Add path aliases to `resolve.alias` — bare imports like `import X from 'contexts/...'` won't resolve without them.
- Add directory-index extensions: `"/index.ts"`, `"/index.tsx"` to `resolve.extensions`.
- Set `resolve.tsconfig` if the project uses `baseUrl` or `paths`.

Full walkthrough: [Extractors → Alias Resolution](extractors/alias-resolution.md).

## Excessive output size

- Disable visitors you don't need (e.g. `classes: false` for React frontends).
- Narrow `include` patterns (e.g. `src/contexts/**/*.ts` instead of `src/**/*.ts`).
- Add more `exclude` patterns for generated or vendored files.

## Labels not matching

- Add a temporary `{ "pattern": "*", "label": "debug" }` rule to see every flattened callee, then remove it once you've confirmed the format.
- Remember `fnmatch`: `*` alone matches `router`, **not** `router.get`. Use `*.*` or be explicit.
- See [Label Patterns](extractors/label-patterns.md) for the full matcher semantics.

## Tree-sitter parse errors

- Ensure the `type` field matches the actual language. Use `"typescript"` for `.ts`/`.tsx`, `"javascript"` for `.js`.
- Files with syntax errors still produce partial ASTs — extraction continues with best-effort results.
- Errors are collected and reported at the end (first 10 shown).

## Ollama / embedding issues

- **Ollama unreachable** — the pipeline skips embeddings; rerun `bindwood scan` after starting Ollama. Every command also prints a `[warn]` line to stderr when Ollama isn't reachable.
- **Model not found** — auto-pull is attempted; if it fails, pull manually: `ollama pull <model>`.
- **Search returns unrelated matches** — confirm the same model is used for indexing and querying.

See [Embeddings](database/embeddings.md) for the full setup guide.

## MCP tools don't show up in Claude

- Confirm the database path in `BINDWOOD_DB` is absolute and points to an existing `.db` file.
- Restart Claude Code after editing `.claude/settings.local.json`.
- Verify the server starts at all by running `bindwood mcp` in a shell — it should print MCP protocol messages.

## Visualization page is empty or 500s

- Install the `[viz]` extra: `uv sync --extra viz` or `pip install "bindwood[viz]"`. The `/viz` routes silently do nothing without it.
- Confirm the DB has at least one target: `curl http://127.0.0.1:8765/viz/` should list targets.
- The **Labels** tab showing *"No labeled calls for target..."* is not an error — it means that target's config has no `labels` rules yet. See [Label Patterns](extractors/label-patterns.md).
- Plotly loads from the CDN by default. If you're offline, the charts will render but without the interactive toolbar.

## `bindwood: command not found`

- If installed via `uv sync` from a source checkout, use `uv run bindwood ...` or activate the venv first.
- If installed via `pip`, confirm your Python's `Scripts/` (Windows) or `bin/` (macOS/Linux) directory is on `PATH`.

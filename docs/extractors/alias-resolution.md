# Alias Resolution

Import resolution decides whether an `import` statement becomes an **edge** in the graph (resolved) or a dangling `null` target (unresolved). Tuning the resolver is usually the highest-impact way to improve graph quality.

## Priority order

1. **Relative imports** (`./foo`, `../bar`) — resolved from the importing file's directory.
2. **Manual aliases** (`resolve.alias` in config) — prefix matching, highest priority for non-relative.
3. **tsconfig `paths`** — glob-based path mapping from `tsconfig.json`.
4. **tsconfig `baseUrl`** — resolve non-relative imports from the base directory.
5. **External** — if `skip_external` is `true` (default), the resolver returns `null`.

For each candidate, the resolver tries appending each extension from `resolve.extensions` in order:

```json
"extensions": [".ts", ".tsx", "/index.ts", "/index.tsx"]
```

Entries starting with `/` try a directory index (e.g. `foo/` → `foo/index.ts`).

---

## Example: Vite aliases

If your `vite.config.ts` has:

```typescript
resolve: {
  alias: {
    api:      path.resolve(__dirname, 'src/api'),
    contexts: path.resolve(__dirname, 'src/contexts'),
  }
}
```

Mirror them in the extractor config:

```json
"resolve": {
  "alias": {
    "api": "src/api",
    "contexts": "src/contexts"
  }
}
```

!!! note
    The alias values are **relative to the project `root`**, not the workspace root.

---

## Example: tsconfig baseUrl

If your `tsconfig.json` has `"baseUrl": "src"`, point the resolver at it instead of listing every directory manually:

```json
"resolve": {
  "tsconfig": "tsconfig.json"
}
```

The resolver reads `baseUrl` and `paths` automatically. If both `alias` (manual) and `tsconfig` match, the **manual alias wins**.

---

## Example: custom extensions

Matching directory index files for a modern TS project:

```json
"resolve": {
  "extensions": [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.tsx", "/index.js"]
}
```

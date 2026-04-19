# JS/TS Targets

Extract a structural graph from a JavaScript or TypeScript codebase. This is the main extractor and has the most configuration surface.

## Top-level fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"javascript"` \| `"typescript"` | yes | — | Language grammar. `"typescript"` auto-selects `.ts`/`.tsx` grammars. |
| `name` | string | yes | — | Target name. |
| `root` | string | yes | — | Path to project root (relative to workspace root, or absolute). |
| `output` | string | no | `graph/<name>_graph.json` | Output file path. |
| `include` | string[] | yes | — | Glob patterns for files to scan (relative to `root`). |
| `exclude` | string[] | no | `["**/node_modules/**"]` | Glob patterns for files to skip. |
| `max_depth` | int \| null | no | `null` | Max directory depth from `root` (unlimited by default). |

## `extract` — what to pull out of the AST

Toggle visitors on/off to control output size and extraction speed. Disable what you don't need.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `imports` | bool | `true` | ESM `import` statements and CJS `require()` calls. |
| `exports` | bool | `true` | ESM `export` and CJS `module.exports`. |
| `functions` | bool | `true` | Function declarations, arrow functions, methods. |
| `calls` | bool | `true` | All call expressions (function calls, method calls, `new`). |
| `classes` | bool | `true` | Class declarations with methods and properties. |
| `types` | bool | `false` | TypeScript interfaces, type aliases, enums (TS files only). |

## `resolve` — import resolution

Controls how import specifiers map to project-relative file paths. This determines the **edges** in the graph.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `extensions` | string[] | `[".js", ".ts", ".tsx", ".jsx", "/index.js", "/index.ts"]` | Extensions to try when resolving bare imports. Entries starting with `/` are treated as directory index files. |
| `tsconfig` | string \| null | `null` | Path to `tsconfig.json` relative to `root`. If set, reads `baseUrl` and `paths` for resolution. |
| `alias` | object | `{}` | Manual alias map: `{ "prefix": "target/path" }`. Overrides tsconfig. |
| `skip_external` | bool | `true` | Skip `node_modules` / third-party imports (resolver returns `null`). |

Full walkthrough: [Extractors → Alias Resolution](../extractors/alias-resolution.md).

## `labels` — semantic call labeling

Label rules tag call expressions whose flattened callee chain matches a pattern. This is how you mark calls as "HTTP routes", "API calls", "auth checks", etc.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pattern` | string | yes | One or more `fnmatch` glob patterns separated by `\|`. |
| `label` | string | yes | Semantic label applied to matching calls. |
| `capture_arg` | int \| null | no | If set, captures the Nth argument (0-indexed) as a string value. |

Full walkthrough with recommended patterns per project type: [Extractors → Label Patterns](../extractors/label-patterns.md).

## Complete example

```json
{
  "type": "typescript",
  "name": "my-frontend",
  "root": "services/frontend/web",
  "include": ["src/**/*.ts", "src/**/*.tsx"],
  "exclude": ["**/node_modules/**", "**/*.test.ts"],
  "extract": {
    "imports": true,
    "exports": true,
    "functions": true,
    "calls": true,
    "classes": false,
    "types": true
  },
  "resolve": {
    "tsconfig": "tsconfig.json",
    "alias": {
      "api": "src/api",
      "contexts": "src/contexts"
    },
    "extensions": [".ts", ".tsx", "/index.ts", "/index.tsx"],
    "skip_external": true
  },
  "labels": [
    {
      "pattern": "axios.get|axios.post|axios.put|axios.delete",
      "label": "api_call",
      "capture_arg": 0
    },
    { "pattern": "useReducer",    "label": "state_management" },
    { "pattern": "useContext",    "label": "context_consumer" }
  ]
}
```

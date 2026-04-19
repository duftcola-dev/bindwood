# Python Targets

Extract a structural graph from a Python codebase.

## Top-level fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `"python"` | yes | — | Extractor type. |
| `name` | string | yes | — | Target name. |
| `root` | string | yes | — | Path to project root (relative to workspace root, or absolute). |
| `output` | string | no | `graph/<name>_graph.json` | Output file path. |
| `include` | string[] | yes | — | Glob patterns for files to scan (relative to `root`). |
| `exclude` | string[] | no | see below | Glob patterns for files to skip. |
| `max_depth` | int \| null | no | `10` | Max directory depth from `root`. |

Default `exclude` patterns set by `bindwood add`:

```
**/__pycache__/**
**/.venv/**
**/venv/**
**/.tox/**
**/dist/**
**/build/**
**/*.egg-info/**
```

## `extract` — what to pull out of the AST

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `imports` | bool | `true` | `import` and `from ... import` statements. |
| `functions` | bool | `true` | Function and method definitions. |
| `calls` | bool | `true` | Call expressions. |
| `classes` | bool | `true` | Class declarations. |

## `resolve` — import resolution

Controls how import specifiers map to project-relative file paths.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `skip_external` | bool | `true` | Skip third-party / stdlib imports (resolver returns `null`). |
| `src_roots` | string[] | `[]` | Additional source roots to try when resolving absolute imports (e.g. `["src"]`). |

## `labels` — semantic call labeling

Same format as [JS/TS Targets](jsts-targets.md#labels-semantic-call-labeling). Tag call expressions whose flattened callee chain matches a pattern.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `pattern` | string | yes | One or more `fnmatch` glob patterns separated by `\|`. |
| `label` | string | yes | Semantic label applied to matching calls. |
| `capture_arg` | int \| null | no | Capture the Nth argument (0-indexed) as a string value. |

## Node and edge types

**Nodes produced:**

| Type | Description |
|------|-------------|
| `file` | Python module file. |
| `function` | Function or method definition. |
| `class` | Class declaration. |
| `call` | Call expression. |
| `export` | Top-level name exported from a module. |

**Edges produced:**

| Type | Description |
|------|-------------|
| `imports` | Module imports another module. |
| `contains` | File or class contains a function/method. |
| `exports` | Module exports a name. |

## Complete example

```json
{
  "type": "python",
  "name": "my-backend",
  "root": "services/api",
  "output": "graph/my-backend_graph.json",
  "include": ["**/*.py"],
  "exclude": [
    "**/__pycache__/**",
    "**/.venv/**",
    "**/tests/**",
    "**/migrations/**"
  ],
  "max_depth": 10,
  "extract": {
    "imports": true,
    "functions": true,
    "calls": true,
    "classes": true
  },
  "resolve": {
    "skip_external": true,
    "src_roots": ["src"]
  },
  "labels": [
    { "pattern": "app.route|router.get|router.post|router.put|router.delete", "label": "http_route" },
    { "pattern": "db.execute|session.query|session.execute", "label": "db_access" },
    { "pattern": "jwt.decode|verify_token|require_auth", "label": "auth_check" }
  ]
}
```

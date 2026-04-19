# Output Format

The extractor produces a single JSON file per target with this shape:

```json
{
  "metadata": {
    "extracted_at": "2026-04-04T12:18:12.172859",
    "project": "hub4retail-backend",
    "project_root": "/path/to/project",
    "total_files": 294,
    "total_functions": 1616,
    "total_classes": 169,
    "total_calls": 12140,
    "total_labeled_calls": 1488,
    "total_nodes": 14510,
    "total_edges": 2989
  },
  "nodes": [ ... ],
  "edges": [ ... ]
}
```

## Node types

| Type | ID format | Key fields |
|------|-----------|------------|
| `file` | `file::<path>` | `path` |
| `function` | `func::<path>::<qualified_name>` | `name`, `kind` (declaration/arrow/method/generator), `async`, `params`, `enclosing_class`, `source_text` |
| `class` | `class::<path>::<name>` | `name`, `extends`, `methods[]`, `properties[]`, `source_text` |
| `call` | `call::<path>::L<line>::<callee>` | `callee`, `args_preview`, `is_new`, `labels[]`, `captured_arg` |
| `export` | `export::<path>::<name>` | `name`, `kind` (function/class/variable/re-export), `value_hint` |
| `interface` | `type::<path>::<name>` | `name`, `kind="interface"`, `members[]`, `extends[]`, `source_text` |
| `type_alias` | `type::<path>::<name>` | `name`, `kind="type_alias"`, `source_text` |
| `enum` | `type::<path>::<name>` | `name`, `kind="enum"`, `members[]`, `source_text` |

DDL-specific node types are described in [Database → SQLite Schema](../database/schema.md).

## Edge types

| Type | From | To | Description |
|------|------|----|-------------|
| `imports` | file | file (or null) | File imports another. `to` is `null` for unresolved/external modules. |
| `exports` | file | export | File exports a binding. |
| `contains` | file | function / class | File contains a function or class definition. |
| `extends` | class | null | Class extends another (target resolved by name, not file). |

## Source text capture

The extractors capture actual source code for nodes that benefit from semantic search:

| Node type | What is captured | Max length |
|-----------|------------------|------------|
| `function` | Full function body (signature + implementation) | 2000 chars |
| `class` | Full class definition (including methods) | 2000 chars |
| `interface` | Interface declaration with all members | 2000 chars |
| `type_alias` | Type alias declaration | 2000 chars |
| `enum` | Enum declaration with members | 2000 chars |
| `table` (DDL) | Structured description: columns, types, PKs, FKs | N/A |
| `view` (DDL) | Structured description: columns, sources, definition preview | N/A |

Nodes without source text (files, calls, exports, edges) are **not embedded** but remain queryable through the graph.

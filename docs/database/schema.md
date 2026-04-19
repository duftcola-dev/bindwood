# SQLite Schema

The database has five tables: three for graph data, one for cross-target references, one for vector embeddings.

## Tables

```sql
-- One row per extraction target (backend, frontend, DDL, etc.)
targets (name TEXT PK, type, root, extracted_at, metadata JSON)

-- All graph nodes normalized into a flat table
nodes (
  id TEXT, target TEXT, type, file, line, name,
  source_text, properties JSON
)
  -- PK: (id, target)
  -- Indexes: (type, target), (file), (name)

-- All graph edges
edges (source, target_node, type, target, properties JSON)
  -- Indexes: (source, target), (target_node, target), (type, target)

-- Cross-target references (for future use)
cross_references (
  source_node, source_target,
  target_node, target_target,
  type, confidence
)

-- Vector similarity search (sqlite-vec)
vec_embeddings (node_id TEXT PK, target TEXT, embedding FLOAT[768])
```

## Node types stored

| Type | Source | Description |
|------|--------|-------------|
| `file` | JS/TS/Python | Source file. |
| `function` | JS/TS/Python | Function/method/arrow with source code. |
| `class` | JS/TS/Python | Class definition with source code. |
| `call` | JS/TS/Python | Call expression with labels. |
| `export` | JS/TS | Exported binding. |
| `interface` | TS | TypeScript interface with source code. |
| `type_alias` | TS | TypeScript type alias with source code. |
| `enum` | TS / DDL | TypeScript or PostgreSQL enum. |
| `table` | DDL | Database table with columns, PKs, FKs. |
| `view` | DDL | Regular view. |
| `materialized_view` | DDL | Materialized view. |

## Edge types stored

| Type | Description |
|------|-------------|
| `imports` | File imports another file. |
| `exports` | File exports a binding. |
| `contains` | File contains a function / class. |
| `extends` | Class extends another. |
| `fk` | Foreign key relationship between tables. |
| `depends_on` | View depends on a table or another view. |

## Why SQLite?

- **Zero infrastructure** — a single `.db` file; no Postgres, no vector DB service.
- **Portable** — commit it, ship it, mount it in a container; everything travels together.
- **Fast** — `sqlite-vec` is an extension written in C; vector search runs in-process.
- **Composable** — normal SQL joins across nodes, edges, and vector hits.

## Schema location

The schema lives in [`bindwood/db/schema.py`](../api/db.md). If you change the embedding model to one with different dimensions, update `FLOAT[768]` accordingly.

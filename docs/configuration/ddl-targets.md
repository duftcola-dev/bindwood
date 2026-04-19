# DDL Targets

Extract a graph of tables, columns, foreign keys, indexes, views, and enums from a SQL DDL file.

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"ddl"` | yes | Extractor type. |
| `name` | string | yes | Target name (used in logs and `--target` filtering). |
| `file` | string | yes | Path to the DDL file (relative to workspace root, or absolute). |
| `dialect` | string | no | SQL dialect (default `"postgres"`). |
| `output` | string | no | Output JSON path, relative to workspace root. |

## Example

```json
{
  "type": "ddl",
  "name": "hub4retail-db",
  "file": "ddl/tables/FULL_DB_DDL.sql",
  "dialect": "postgres",
  "output": "graph/db_graph.json"
}
```

## What you get

Nodes produced by this extractor:

| Type | Description |
|------|-------------|
| `table` | Table with columns, primary keys, foreign keys, unique constraints. |
| `view` | Regular view with column list and source query. |
| `materialized_view` | Materialized view. |
| `enum` | PostgreSQL enum type with members. |

Edges produced:

| Type | Description |
|------|-------------|
| `fk` | Foreign key relationship between two tables. |
| `depends_on` | View depends on a table or another view. |

See [Database → Pipeline](../database/pipeline.md) for how DDL targets flow into the SQLite database.

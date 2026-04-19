# Query Reference

`bindwood query` provides an interactive command-line interface for exploring the database.

```bash
bindwood query <command> [options]
```

## Commands

| Command | Description |
|---------|-------------|
| `stats` | Database overview: targets, node/edge counts, embedding stats. |
| `search <query>` | Semantic similarity search using natural language. |
| `find` | Find nodes by type, name, file pattern, or semantic label. |
| `node <id>` | Look up a specific node by ID (full or partial match). |
| `neighbors <id>` | Graph traversal: show all edges in/out of a node. |
| `context <query>` | Semantic search + expand graph neighbors around results. |
| `slice <id>` | Extract a subgraph rooted at a node, up to `--depth` hops. |
| `tables` | List all DDL tables with columns. |
| `sql <query>` | Run a raw SQL query against the database. |

## Common flags

| Flag | Applies to | Description |
|------|------------|-------------|
| `--target <name>` | most | Filter to a specific extraction target. |
| `--limit <n>` | `search`, `find`, `context` | Max results (defaults vary per command). |
| `--depth <n>` | `slice` | Max hops from the root node. |
| `--type <t>` | `find` | Node type filter: `function`, `class`, `call`, `table`, `interface`, etc. |
| `--name <pat>` | `find` | Name pattern (use `%` as SQL wildcard). |
| `--file <pat>` | `find` | File path pattern. |
| `--label <name>` | `find` | Semantic label: `http_route`, `db_access`, `auth_check`, etc. |

See [Examples](examples.md) for end-to-end queries across real workflows.

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
| `slice <seeds...>` | BFS transitive closure around one or more seed nodes. |
| `trace <from> <to>` | Find how two nodes connect via BFS path search. |
| `tables` | List all DDL tables with columns. |

## Common flags

| Flag | Applies to | Description |
|------|------------|-------------|
| `--target <name>` / `-t` | most | Filter to a specific extraction target. |
| `--limit <n>` / `-n` | `search`, `find`, `context` | Max results (defaults vary per command). |
| `--type <t>` | `find` | Node type filter: `function`, `class`, `call`, `table`, `interface`, etc. |
| `--name <pat>` | `find` | Name pattern (use `%` as SQL wildcard). |
| `--file <pat>` | `find` | File path pattern. |
| `--label <name>` | `find` | Semantic label: `http_route`, `db_access`, `auth_check`, etc. |

## `slice` flags

| Flag | Default | Description |
|------|---------|-------------|
| `--depth` / `-d` | `2` | Max hops from each seed. |
| `--direction` | `out` | Edge direction to traverse: `out`, `in`, or `both`. |
| `--edge-kinds` | all | Comma-separated edge types to follow (e.g. `imports,contains`). |
| `--max-nodes` | `200` | Hard cap on discovered nodes. |
| `--json` | off | Output raw JSON instead of formatted text. |

## `neighbors` flags

| Flag | Default | Description |
|------|---------|-------------|
| `--direction` | `both` | `in`, `out`, or `both`. |
| `--edge-type` | all | Filter to a single edge type: `imports`, `exports`, `contains`, `fk`, `depends_on`, `extends`. |

## `trace` flags

| Flag | Default | Description |
|------|---------|-------------|
| `--max-depth` | `3` | Maximum BFS hops to search. |
| `--from-target` | — | Target for the origin node. |
| `--to-target` | — | Target for the destination node. |

See [Examples](examples.md) for end-to-end queries across real workflows.

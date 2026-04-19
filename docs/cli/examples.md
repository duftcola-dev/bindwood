# Query Examples

End-to-end examples for the most common query workflows.

## Semantic search — find code by meaning

```bash
# Authentication-related code
bindwood query search "user authentication login permissions"

# Restrict to the backend target
bindwood query search "database connection pooling" --target hub4retail-backend

# Product catalog logic, fewer results
bindwood query search "product catalog pricing" --limit 5
```

## Structured lookup — find nodes by attributes

```bash
# All functions named "login" across all targets
bindwood query find --type function --name login

# All HTTP route calls in the backend
bindwood query find --type call --label http_route --target hub4retail-backend

# All tables with "product" in the name
bindwood query find --type table --name product

# All functions in a specific file
bindwood query find --type function --file "user.actions.ts"
```

## Node detail — read source code

```bash
# Full details of a specific function
bindwood query node "func::applications/main/interface/user.js::User.login"

# Partial match also works
bindwood query node "User.login"
```

## Graph traversal — explore relationships

```bash
# What tables does the product table reference? What references it?
bindwood query neighbors "table::product"

# What does a file contain/import?
bindwood query neighbors "file::applications/main/interface/user.js"
```

## Context search — semantic + structural

```bash
# Find order processing code and show what it connects to
bindwood query context "database access for orders" --limit 3
```

## Slice — subgraph around a node

```bash
# All nodes reachable within 2 hops of this file (following outgoing edges)
bindwood query slice "file::src/index.ts" --depth 2

# Follow only import edges, both directions, up to 3 hops
bindwood query slice "file::src/index.ts" --depth 3 --direction both --edge-kinds imports

# Multiple seeds at once; emit raw JSON
bindwood query slice "file::src/auth.ts" "file::src/middleware.ts" --json
```

## Trace — how two nodes connect

```bash
# Find the path from one file to another through the import graph
bindwood query trace "file::src/api/routes.ts" "file::src/db/queries.ts"

# Increase search depth for distant nodes
bindwood query trace "func::...::validateOrder" "table::orders" --max-depth 5
```

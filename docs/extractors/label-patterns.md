# Label Patterns

Labels are the most powerful configuration feature. They turn raw call expressions into semantically meaningful markers — so you can query *"which files make API calls?"* or *"where are auth checks?"* directly from the graph.

## How patterns work

Each call expression has its callee **flattened** into a dot-separated chain:

| Source code | Flattened callee |
|-------------|------------------|
| `foo()` | `foo` |
| `router.get(...)` | `router.get` |
| `this.service.findAll(...)` | `this.service.findAll` |
| `connectorHandler.connector.find_items(...)` | `connectorHandler.connector.find_items` |
| `axios.get(...)` | `axios.get` |
| `useReducer(...)` | `useReducer` |
| `dispatch({ type: ... })` | `dispatch` |

Patterns use Python's `fnmatch` syntax (same as shell globbing):

| Pattern | Matches |
|---------|---------|
| `foo` | Exactly `foo` |
| `*.get` | Anything ending in `.get` (e.g. `router.get`, `axios.get`) |
| `*_router.get` | Any variable ending in `_router` followed by `.get` |
| `*.connector.find_*` | Any connector call starting with `find_` |
| `useReducer` | Exactly `useReducer` |
| `use*` | Anything starting with `use` (matches all React hooks) |

Multiple patterns can be combined with `|`:

```json
{
  "pattern": "*.get|*.post|*.put|*.delete|*.patch",
  "label": "http_call"
}
```

## `capture_arg`

When set, the labeler captures the string value of the Nth argument (0-indexed) from the call's argument preview. Useful for extracting route paths, event names, etc.

```json
{
  "pattern": "*_router.get|*_router.post",
  "label": "http_route",
  "capture_arg": 0
}
```

Given `product_router.get("/api/products", ...)`, this produces:

```json
{
  "callee": "product_router.get",
  "labels": ["http_route"],
  "captured_arg": "/api/products"
}
```

---

## Recommended patterns

### Express / Node.js backend (CommonJS)

Targets a classic Route → Interface → Service layered backend with a connector-style ORM.

```json
"labels": [
  {
    "pattern": "*_router.get|*_router.post|*_router.put|*_router.delete|*_router.patch",
    "label": "http_route",
    "capture_arg": 0
  },
  {
    "pattern": "*.connector.find_item|*.connector.find_items|*.connector.find_all_items|*.connector.findAndCount|*.connector.count|*.connector.new_item|*.connector.new_items|*.connector.update_items|*.connector.bulk_update|*.connector.delete_items|*.connector.batch_delete|*.connector.raw_query",
    "label": "db_access"
  },
  { "pattern": "*.checkPermissions", "label": "auth_check" }
]
```

| Label | Why it matters |
|-------|----------------|
| `http_route` | Maps every HTTP endpoint with its path. Essential for API surface discovery and contract validation. `capture_arg: 0` extracts the route string. |
| `db_access` | Marks every ORM call. Reveals which modules touch which tables, exposes N+1 patterns, supports schema impact analysis. |
| `auth_check` | Tags permission checks. Any route without an `auth_check` in its call tree is a potential security gap. |

**Optional additions:**

- `"pattern": "*.sendMail|*.send_email", "label": "email"`
- `"pattern": "s3.putObject|s3.getObject|s3.deleteObject", "label": "s3_access"`
- `"pattern": "*.publish|*.emit", "label": "event_emit"`

---

### React + TypeScript frontend (ESM)

Targets a modern React codebase using Context + `useReducer`, React Router, i18next, axios, Auth0.

```json
"labels": [
  { "pattern": "useReducer",                                         "label": "state_management" },
  { "pattern": "createContext",                                      "label": "context_provider" },
  { "pattern": "useContext",                                         "label": "context_consumer" },
  { "pattern": "useState",                                           "label": "local_state" },
  { "pattern": "useEffect",                                          "label": "side_effect" },
  { "pattern": "useMemo|useCallback",                                "label": "memoization" },
  { "pattern": "useNavigate|useParams|useLocation|useSearchParams",  "label": "routing" },
  { "pattern": "useTranslation",                                     "label": "i18n" },
  {
    "pattern": "axios.get|axios.post|axios.put|axios.delete|axios.patch",
    "label": "api_call",
    "capture_arg": 0
  },
  { "pattern": "useAuth0|*.loginWithRedirect|*.logout|*.getAccessTokenSilently", "label": "auth" },
  { "pattern": "lazy",                                               "label": "lazy_load" },
  { "pattern": "dispatch",                                           "label": "dispatch" }
]
```

| Label | Why it matters |
|-------|----------------|
| `state_management` | Files that create `useReducer` stores — the core of each context domain. |
| `context_provider` | Where `createContext()` is called — roots of each context domain. |
| `context_consumer` | Which components consume which contexts via `useContext()`. |
| `local_state` | `useState` calls. Distinguishes components with local UI state from those depending on shared context. |
| `side_effect` | `useEffect` — data fetching, subscriptions, DOM manipulation. |
| `memoization` | `useMemo` / `useCallback`. Highlights performance-sensitive components. |
| `routing` | React Router hook usage. Maps components depending on URL state. |
| `i18n` | Translated components. Useful for i18n coverage audits. |
| `api_call` | The most important frontend label. Tags every HTTP call with the URL. Maps the frontend-to-backend surface. |
| `auth` | Auth0 interactions — login, logout, token refresh, identity reads. |
| `lazy_load` | `React.lazy()` — which routes/components are code-split. |
| `dispatch` | Reducer dispatch calls — the write-side of your state architecture. |

#### Tuning `api_call` precision

The `axios.get|...` pattern only matches calls on a variable literally named `axios`. If you wrap axios in a custom instance (common), match that name:

```typescript
// src/api/httpClient.ts
const httpClient = axios.create({ baseURL: '...' });
export default httpClient;

// src/api/products.ts
httpClient.get('/products');  // callee = "httpClient.get"
```

```json
{
  "pattern": "httpClient.get|httpClient.post|httpClient.put|httpClient.delete|httpClient.patch",
  "label": "api_call",
  "capture_arg": 0
}
```

To find the right name, search for `axios.create`:

```bash
grep -r "axios.create" src/api/ --include="*.ts"
```

**Optional additions:**

- `"pattern": "useForm|useWatch|useFieldArray", "label": "form"`
- `"pattern": "notification.*|message.*", "label": "user_notification"`
- `"pattern": "console.log|console.warn|console.error", "label": "console_log"`

---

### Generic TypeScript library / CLI

For non-React, non-Express TypeScript projects (shared libs, CLIs, SDKs):

```json
"labels": [
  { "pattern": "console.log|console.warn|console.error|console.debug", "label": "logging" },
  { "pattern": "throw|reject",                                         "label": "error_boundary" },
  { "pattern": "fs.*|readFile*|writeFile*",                            "label": "filesystem" },
  { "pattern": "*.on|*.once|*.emit|*.addEventListener",                "label": "event" }
]
```

---

## Debugging labels that don't match

- Add a temporary `{ "pattern": "*", "label": "debug" }` rule to see **every** flattened callee in the output, then remove it.
- `fnmatch`'s `*` does match dots in bindwood's matcher, but be aware that `*` alone matches `router`, **not** `router.get`. Use `*.*` or be explicit.
- Remember patterns are matched against the **flattened callee chain**, not the source text.

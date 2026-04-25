# Benchmark

The benchmark measures whether installing the bindwood MCP server into a real Claude Code session reduces token consumption vs. Claude Code with only built-in filesystem tools. Every run is a headless `claude -p` subprocess against one of twelve fixture repositories. A judge LLM grades answer quality so we can catch "cheap but wrong".

## What it actually measures

The single variable is the toolset. Both conditions run the same Claude Code binary, against the same fixture, with the same question. The only difference is which tools the model is allowed to use.

| Condition | Tools | MCP |
|-----------|-------|-----|
| **baseline** | `Read`, `Grep`, `Glob`, `Bash` | none |
| **bindwood** | *(no built-in tools)* | `bindwood` MCP server, exclusively loaded via `--strict-mcp-config` |

Bindwood condition has built-ins fully disabled (`--tools ""`), forcing every question through MCP. Baseline has MCP unavailable. There is no middle ground on purpose — a forced split makes the comparison unambiguous.

The MCP server spawn cost is **included** in the bindwood wall time and in its token usage. That is a real component of user-facing latency, so hiding it would flatter bindwood.

## Metrics

Each per-question row records:

- `input_tokens`, `output_tokens` — raw, non-cached
- `cache_creation_input_tokens` — newly written to the prompt cache
- `cache_read_input_tokens` — re-read from the cache
- `effective_tokens` = `input + output + 1.25·cache_creation + 0.1·cache_read`
- `tool_calls` — every tool invocation with name + input
- `turns`, `elapsed_seconds`, `total_cost_usd`, `duration_ms`
- Judge verdict: `baseline` / `bindwood` / `tie` / `error` + per-axis scores (completeness, accuracy, specificity, 1–5)

**Effective tokens is the headline number.** In Claude Code most of the context flows through the prompt cache, so summing only `input + output` drastically undercounts the real workload. The weighting mirrors Anthropic's pricing: cache creation costs 1.25× an input token; cache reads cost 0.1×.

Raw totals are still saved in the JSON so you can re-analyze either way.

## Architecture

```
benchmarks/
├── harness.py        # spawns `claude -p`, parses stream-json, returns RunResult
├── rubric.py         # spawns a second `claude -p` (no tools) as A/B judge
├── repos.py          # loads fixtures.toml, writes shared .mcp.json
├── questions.py      # Question dataclass + code + DDL banks, tagged by applies_to
├── report.py         # per-fixture / per-type / overall tables, JSON export
├── run.py            # CLI entry point
├── fixtures.toml     # YOUR fixture paths (copy from fixtures.example.toml)
└── .mcp_configs/     # auto-generated, shared .mcp.json lives here
```

The MCP config is one shared JSON with a single `bindwood` server (`command: "bindwood"`, `args: ["mcp"]`). No DB path is baked in — `bindwood mcp` resolves its own database from the bindwood config. Fixtures name their `target` so the MCP tools scope correctly.

The judge is also a `claude -p` subprocess — no Anthropic SDK dependency. A/B positions are randomized per call so the judge can't anchor on "always pick A".

## Prerequisites

1. **Logged-in Claude Code CLI.** Run `claude` once and verify interactive login works. OAuth credentials are picked up by subprocesses.
2. **Scanned targets.** Every fixture in `fixtures.toml` must already exist as a bindwood target. Confirm with:
   ```bash
   bindwood list
   ```
   The names in the `target` column must match the `target` field of each fixture entry.
3. **Benchmark dependencies:**
   ```bash
   uv sync --extra benchmark
   ```
4. **Fixture file:**
   ```bash
   cp benchmarks/fixtures.example.toml benchmarks/fixtures.toml
   ```
   Edit the 12 `path` values to match where your sample repos actually live.

## CLI reference

```
python -m benchmarks.run [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--fixtures PATH` | `benchmarks/fixtures.toml` | Fixture TOML. |
| `--types T [T ...]` | all | Filter by fixture type: `ddl`, `python`, `javascript`, `typescript`. |
| `--repos N [N ...]` | all | Filter by fixture name (applied after `--types`). |
| `--tiers T [T ...]` | all | Filter by question tier: `orientation`, `lookup`, `structural`, `cross_cutting`. |
| `--questions a,b,c` | all | Comma-separated question IDs. |
| `--model NAME` | Claude Code default | Passed through to `claude --model`. |
| `--timeout-s N` | `900` | Per-subprocess timeout in seconds. |
| `--no-judge` | — | Skip the judge LLM call. Runs half the subprocesses. |
| `--output PATH` | `benchmark_results.<UTC-timestamp>.json` | Where to write the results JSON. Default auto-suffixes a UTC timestamp (e.g. `benchmark_results.20260425T141233Z.json`) so back-to-back runs don't overwrite. Pass an explicit path to override. |
| `--mcp-cache-dir PATH` | `benchmarks/.mcp_configs` | Where the shared `.mcp.json` is written. |
| `--dry-run` | — | Print the matrix without running anything. |

Always run inside `uv run` so the `bindwood` entry point and Python deps resolve:

```bash
uv run python -m benchmarks.run …
```

## Question bank

Questions are tagged with `applies_to`. Code questions (`orient_*`, `lookup_*`, `struct_*`, `cross_*`) apply to Python/JS/TS. DDL questions (`ddl_*`) apply only to DDL fixtures. The runner auto-filters so you never have to worry about sending a "trace the call chain" question to a `.sql` file.

### Code — Python / JavaScript / TypeScript

| Tier | ID | Question |
|------|----|----------|
| orientation | `orient_1` | Overview: main modules, file count, what each top-level directory contains. |
| orientation | `orient_2` | List every public class with its file. |
| orientation | `orient_3` | Entry points: CLI commands, HTTP routes, public module-level functions, `__main__` blocks. |
| lookup | `lookup_1` | Every function whose name contains "parse" — name, file, line. |
| lookup | `lookup_2` | Module that exposes the main public API; its path and top-level exports. |
| lookup | `lookup_3` | All config-management functions (load, save, validate, reset). |
| structural | `struct_1` | Most central module — what it imports, what imports it. |
| structural | `struct_2` | Call chain from a top-level public API down to low-level I/O. |
| structural | `struct_3` | Functions performing low-level I/O (network, file, DB). |
| cross_cutting | `cross_1` | All error-handling sites with a one-line description. |
| cross_cutting | `cross_2` | External runtime dependencies and which parts of the codebase call them. |
| cross_cutting | `cross_3` | Every public API surface and how it's re-exported. |

### DDL

| Tier | ID | Question |
|------|----|----------|
| orientation | `ddl_orient_1` | Schema overview: table count, major entity groups, tables grouped by purpose. |
| orientation | `ddl_orient_2` | Every table with its primary key. Flag tables missing a PK. |
| lookup | `ddl_lookup_1` | Every foreign-key: `source_table.column → target_table.column`. |
| lookup | `ddl_lookup_2` | Tables with columns named `id` or ending in `_id`, with types. |
| structural | `ddl_struct_1` | Most central table by incoming FK count; referencers and referenced. |
| cross_cutting | `ddl_cross_1` | Impact of dropping one FK: broken relationships and orphan-row risks. |

## Test battery

Ready-to-copy commands, in increasing blast radius. Every command uses `uv run` so the bindwood entry point resolves.

### Shake-outs (single question, single fixture)

One run each — the fastest way to confirm the plumbing is working after a change.

```bash
# Python
uv run python -m benchmarks.run --types python --repos p-example-1 --questions orient_1 --no-judge

# JavaScript
uv run python -m benchmarks.run --types javascript --repos j-example-1 --questions orient_1 --no-judge

# TypeScript
uv run python -m benchmarks.run --types typescript --repos t-example-1 --questions orient_1 --no-judge

# DDL
uv run python -m benchmarks.run --types ddl --repos ddl1 --questions ddl_orient_1 --no-judge
```

### Dry runs (no subprocesses)

Verify which runs would happen without spending tokens.

```bash
uv run python -m benchmarks.run --dry-run
uv run python -m benchmarks.run --types python --dry-run
uv run python -m benchmarks.run --tiers structural --dry-run
```

### Single-tier sweeps

All fixtures, one tier. Good for scaling up from shake-out to full matrix.

```bash
# Orientation only (3 code questions x 9 code fixtures = 27, plus 2 DDL x 3 DDL = 6 → 33 questions)
uv run python -m benchmarks.run --tiers orientation --no-judge

# Lookup only
uv run python -m benchmarks.run --tiers lookup --no-judge

# Structural only
uv run python -m benchmarks.run --tiers structural --no-judge

# Cross-cutting only
uv run python -m benchmarks.run --tiers cross_cutting --no-judge
```

### Per-type full runs

Every question for one language category.

```bash
# Python: 3 fixtures x 12 code questions = 36 runs x 2 conditions = 72 subprocesses
uv run python -m benchmarks.run --types python --no-judge

# JavaScript
uv run python -m benchmarks.run --types javascript --no-judge

# TypeScript
uv run python -m benchmarks.run --types typescript --no-judge

# DDL: 3 fixtures x 6 DDL questions = 18 runs
uv run python -m benchmarks.run --types ddl --no-judge
```

### Single-fixture full runs

Every applicable question for one specific fixture — useful when investigating one target.

```bash
uv run python -m benchmarks.run --repos p-example-2 --no-judge
uv run python -m benchmarks.run --repos t-example-3 --no-judge
uv run python -m benchmarks.run --repos ddl2 --no-judge
```

### Judging sanity check

Small slice with the judge enabled — verifies the `rubric.py` subprocess path before you pay for it at scale.

```bash
uv run python -m benchmarks.run --types python --repos p-example-1 --tiers orientation \
    --output benchmark_results.judge-check.json
```

### Full matrix

All fixtures, all applicable questions, with judging.

- Code: 9 fixtures × 12 questions = **108 questions**
- DDL: 3 fixtures × 6 questions = **18 questions**
- Total: **126 questions** → 252 condition subprocesses + 126 judge subprocesses = **378 `claude -p` invocations**

```bash
uv run python -m benchmarks.run --output benchmark_results.full.json
```

Without judging (half the subprocesses):

```bash
uv run python -m benchmarks.run --no-judge --output benchmark_results.full.no-judge.json
```

### Pinning a model

Every command above accepts `--model` to override the default.

```bash
uv run python -m benchmarks.run --model sonnet --tiers structural --no-judge
uv run python -m benchmarks.run --model haiku --types ddl
```

### Re-running a specific question across all fixtures

For debugging a single question's behavior.

```bash
uv run python -m benchmarks.run --questions lookup_1 --no-judge
uv run python -m benchmarks.run --questions ddl_struct_1 --no-judge
uv run python -m benchmarks.run --questions struct_2,cross_2 --no-judge
```

## Output

### Console

The report prints one table per fixture, a per-type rollup, and an overall rollup.

```
────────────────────────────────────────────────────────────────────────────────────
Fixture: p-example-1  (1 question(s))
────────────────────────────────────────────────────────────────────────────────────
╭──────────┬──────────┬────────┬───────────────┬───────────────┬────────────────────┬────────┬──────────┬
│ Q        │ Base eff │ BW eff │ Δ             │ Base tools    │ BW tools           │ Wall   │ Judge    │
├──────────┼──────────┼────────┼───────────────┼───────────────┼────────────────────┼────────┼──────────┼
│ orient_1 │  30,456  │ 9,822  │ -20,634 (-67%)│ Bash×3 Glob×2 │ graph_overview×1 … │ 36/14s │ bw       │
│ SUBTOTAL │  30,456  │ 9,822  │ -20,634 (-67%)│               │                    │        │ b=0 w=1  │
╰──────────┴──────────┴────────┴───────────────┴───────────────┴────────────────────┴────────┴──────────┴
```

Column meanings:

| Column | Meaning |
|--------|---------|
| **Base eff / BW eff** | Effective tokens (see *Metrics*). |
| **Δ** | `BW - Base`, absolute and as a percentage. Negative = bindwood cheaper. |
| **Base tools / BW tools** | Tool-call frequency for the run, most-used first. |
| **Wall** | `baseline_seconds / bindwood_seconds`. |
| **Judge** | `base` / `bw` / `tie` / `err` — or `-` if `--no-judge`. |

### JSON

`benchmark_results.<UTC-timestamp>.json` contains every run with its full tool trace plus an aggregate summary:

```json
{
  "run_metadata": {
    "started_at": "2026-04-25T14:12:33+00:00",
    "finished_at": "2026-04-25T14:47:09+00:00",
    "duration_seconds": 2076.34
  },
  "runs": [ ... per-question, per-condition records ... ],
  "summary": {
    "baseline_total_tokens": 145000,
    "bindwood_total_tokens": 52000,
    "baseline_effective_tokens": 1820000.0,
    "bindwood_effective_tokens": 740000.0,
    "tokens_delta": -93000,
    "effective_tokens_delta": -1080000.0,
    "savings_pct": 64.1,
    "effective_savings_pct": 59.3,
    "judge_wins": {"bindwood": 78, "baseline": 32, "tie": 16},
    "runs_count": 126,
    "runs_by_type": {"python": 36, "javascript": 36, "typescript": 36, "ddl": 18}
  }
}
```

## Failure modes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `ERROR: result.is_error=success` on every run | Claude Code was passed `--bare`, which disables OAuth | Confirm `--bare` is not in `harness.py` / `rubric.py`. Export `ANTHROPIC_API_KEY` if you want `--bare` back. |
| `claude CLI not found` | `claude` isn't on PATH inside the `uv run` environment | Run `which claude`; if missing, install the CLI and retry. |
| `repo path for 'X' missing` | A fixture's `path` is wrong or the sample repo was moved | Fix the path in `benchmarks/fixtures.toml`. |
| Bindwood condition uses 0 tool calls | MCP server didn't load | Run `bindwood mcp` directly — it should start without crashing. Check `bindwood list` includes the fixture's `target`. |
| Judge reports `unparseable JSON` | Judge timed out mid-reply or the model hallucinated prose | Re-run just the failing question; if persistent, bump `_JUDGE_TIMEOUT_S` in `rubric.py`. |

## Tips

- Start every session with a `--dry-run` to confirm the matrix.
- Use `--no-judge` while iterating on the harness — judging doubles wall time and cost.
- `--tiers structural` is the cleanest signal: structural questions are where graph queries have the biggest leverage over grep + read.
- Keep the `benchmarks/.mcp_configs/` directory — it's cheap to regenerate and lives alongside the script.

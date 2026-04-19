"""Command-line interface.

Thin wrapper over :class:`CodeIndex` (for query commands), the scan
pipeline (for ``scan``), and the two server entry points.

Entry point: ``bindwood`` (see ``pyproject.toml``). Also runnable as
``python -m bindwood``.

The config file is managed exclusively through the CLI — users should
not hand-edit it. ``bindwood init``, ``bindwood add``, ``bindwood list``,
``bindwood delete`` are the supported entry points; they all read and
write the canonical user-config-dir path.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import click

from bindwood import CodeIndex
from bindwood.config import get_ollama_settings
from bindwood.config.resolver import (
    resolve_config_path,
    resolve_db_path,
    user_config_path,
)
from bindwood.scan import init as scan_targets


# ── Config file helpers ──────────────────────────────────────


def _load_config_file(config_path: Path) -> dict:
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "version": 1,
        "ollama": {},
        "database": {"path": "graph/code_graph.db"},
        "targets": [],
    }


def _save_config_file(config_path: Path, cfg: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def _active_config_path() -> Path:
    """Return the config path the CLI should write to.

    Resolver chain determines where we *read* from; writes always go to
    the user config dir so there's exactly one source of truth.
    """
    return user_config_path()


# ── Ollama health warning (runs on every command) ────────────


def _check_ollama_reachable() -> None:
    """Print a stderr warning if Ollama isn't reachable. Never raises."""
    cfg_path = resolve_config_path()
    cfg: dict = {}
    if cfg_path:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    url = get_ollama_settings(cfg)["url"]
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return
    except (urllib.error.URLError, OSError):
        pass
    click.echo(
        f"[warn] Ollama is not reachable at {url}. "
        "Embeddings and summaries will be skipped. "
        "Start Ollama or run `bindwood ollama-status` for details.",
        err=True,
    )


# ── Root ─────────────────────────────────────────────────────


@click.group(help="bindwood — scan projects, query graphs, run servers.")
@click.version_option(package_name="bindwood", message="%(version)s")
def cli() -> None:
    # Skip the warning on the help path so `bindwood --help` stays quiet.
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h", "--version"):
        return
    _check_ollama_reachable()


# ── Config management (top-level, writes to user config dir) ─


def _prompt_ddl_target() -> dict:
    name = click.prompt("  Target name", type=str)
    file_path = click.prompt("  Path to DDL/SQL file", type=click.Path())
    path = Path(file_path)
    if not path.exists():
        click.echo(f"  Warning: file not found: {path.resolve()}")
        if not click.confirm("  Continue anyway?", default=False):
            raise click.Abort()
    dialect = click.prompt(
        "  SQL dialect",
        default="postgres",
        type=click.Choice(
            ["postgres", "mysql", "sqlite", "bigquery", "tsql"], case_sensitive=False
        ),
    )
    output = click.prompt("  Output graph path", default=f"graph/ddl_{name}_graph.json")
    return {
        "type": "ddl",
        "name": name,
        "file": str(Path(file_path).resolve()),
        "dialect": dialect,
        "output": output,
    }


def _prompt_python_target() -> dict:
    name = click.prompt("  Target name", type=str)
    root = click.prompt("  Project root directory", type=click.Path())
    root_path = Path(root)
    if not root_path.exists():
        click.echo(f"  Warning: directory not found: {root_path.resolve()}")
        if not click.confirm("  Continue anyway?", default=False):
            raise click.Abort()
    default_include = "**/*.py"
    default_exclude = (
        "**/__pycache__/**, **/.venv/**, **/venv/**, **/.tox/**, "
        "**/dist/**, **/build/**, **/*.egg-info/**"
    )
    include = [
        p.strip()
        for p in click.prompt("  Include patterns (comma-separated)", default=default_include).split(",")
        if p.strip()
    ]
    exclude = [
        p.strip()
        for p in click.prompt("  Exclude patterns (comma-separated)", default=default_exclude).split(",")
        if p.strip()
    ]
    output = click.prompt("  Output graph path", default=f"graph/{name}_graph.json")
    return {
        "type": "python",
        "name": name,
        "root": str(Path(root).resolve()),
        "output": output,
        "include": include,
        "exclude": exclude,
        "max_depth": 10,
        "extract": {"imports": True, "functions": True, "calls": True, "classes": True},
        "resolve": {"skip_external": True, "src_roots": []},
        "labels": [],
    }


def _prompt_jsts_target(lang: str) -> dict:
    name = click.prompt("  Target name", type=str)
    root = click.prompt("  Project root directory", type=click.Path())
    root_path = Path(root)
    if not root_path.exists():
        click.echo(f"  Warning: directory not found: {root_path.resolve()}")
        if not click.confirm("  Continue anyway?", default=False):
            raise click.Abort()
    if lang == "typescript":
        default_include = "src/**/*.ts, src/**/*.tsx"
        default_exclude = "**/node_modules/**, **/*.test.ts, **/*.test.tsx, **/*.spec.ts, **/*.spec.tsx, **/*.d.ts"
        default_ext = ".ts, .tsx, /index.ts, /index.tsx"
    else:
        default_include = "src/**/*.js"
        default_exclude = "**/node_modules/**, **/*.test.js, **/*.spec.js"
        default_ext = ".js, /index.js"
    include = [
        p.strip()
        for p in click.prompt("  Include patterns (comma-separated)", default=default_include).split(",")
        if p.strip()
    ]
    exclude = [
        p.strip()
        for p in click.prompt("  Exclude patterns (comma-separated)", default=default_exclude).split(",")
        if p.strip()
    ]
    output = click.prompt("  Output graph path", default=f"graph/{name}_graph.json")
    extensions = [
        e.strip()
        for e in click.prompt("  Resolve extensions (comma-separated)", default=default_ext).split(",")
        if e.strip()
    ]
    return {
        "type": lang,
        "name": name,
        "root": str(Path(root).resolve()),
        "output": output,
        "include": include,
        "exclude": exclude,
        "max_depth": 10,
        "extract": {
            "imports": True,
            "exports": True,
            "functions": True,
            "calls": True,
            "classes": lang == "javascript",
            "types": lang == "typescript",
        },
        "resolve": {"extensions": extensions, "tsconfig": None, "alias": {}},
        "labels": [],
    }


def _prompt_target(kind: str) -> dict:
    if kind == "ddl":
        return _prompt_ddl_target()
    if kind == "python":
        return _prompt_python_target()
    return _prompt_jsts_target(kind)


@cli.command("init")
def init_cmd() -> None:
    """Create the user config file and add the first target."""
    path = _active_config_path()
    if path.exists():
        click.echo(f"Config already exists: {path}")
        click.echo("Use `bindwood add` to add another target, or `bindwood delete <name>` to remove one.")
        if not click.confirm("Overwrite existing config?", default=False):
            return
    click.echo("\n=== bindwood config setup ===\n")
    ollama_url = click.prompt("  Ollama URL", default="http://localhost:11434")
    embedding_model = click.prompt("  Embedding model", default="nomic-embed-text")
    auxiliary_model = click.prompt("  Auxiliary (summary) model", default="gemma4:e4b")
    db_path = click.prompt("  Database path", default="graph/code_graph.db")
    cfg = {
        "version": 1,
        "ollama": {
            "url": ollama_url,
            "embedding_model": embedding_model,
            "auxiliary_model": auxiliary_model,
        },
        "database": {"path": db_path},
        "targets": [],
    }
    if click.confirm("\n  Add a target now?", default=True):
        target_type = click.prompt(
            "  Target type",
            type=click.Choice(["ddl", "javascript", "typescript", "python"], case_sensitive=False),
        )
        cfg["targets"].append(_prompt_target(target_type))
    _save_config_file(path, cfg)
    click.echo(f"\nConfig saved: {path}")


@cli.command("add")
def add_cmd() -> None:
    """Add a new target, or overwrite an existing one."""
    path = _active_config_path()
    cfg = _load_config_file(path)
    existing = {t.get("name") for t in cfg.get("targets", [])}

    click.echo("\n=== Add target ===\n")
    mode = click.prompt(
        "  New project or overwrite an existing one?",
        type=click.Choice(["new", "existing"], case_sensitive=False),
        default="new",
    )
    if mode == "existing":
        if not existing:
            click.echo("  No existing targets to overwrite. Use `new` instead.")
            return
        name_choices = sorted(n for n in existing if n)
        click.echo("\n  Existing targets:")
        for n in name_choices:
            click.echo(f"    - {n}")
        chosen = click.prompt("\n  Name of target to overwrite", type=click.Choice(name_choices))
        # Pre-fill the name by asking for a new definition; drop the old first.
        cfg["targets"] = [t for t in cfg["targets"] if t.get("name") != chosen]

    target_type = click.prompt(
        "  Target type",
        type=click.Choice(["ddl", "javascript", "typescript", "python"], case_sensitive=False),
    )
    target = _prompt_target(target_type)

    if mode == "new" and target["name"] in existing:
        click.echo(f"\n  A target named '{target['name']}' already exists.")
        if not click.confirm("  Replace it?", default=False):
            return
        cfg["targets"] = [t for t in cfg["targets"] if t.get("name") != target["name"]]

    cfg["targets"].append(target)
    _save_config_file(path, cfg)
    click.echo(f"\nTarget '{target['name']}' saved. ({len(cfg['targets'])} total in {path})")


@cli.command("list")
def list_cmd() -> None:
    """Print the active config: source path, Ollama settings, and targets."""
    resolved = resolve_config_path()
    if not resolved:
        click.echo("No config found. Run `bindwood init` to create one.")
        return
    cfg = _load_config_file(resolved)
    click.echo(f"=== Config: {resolved} ===\n")

    ollama = cfg.get("ollama") or {}
    click.echo("  Ollama:")
    click.echo(f"    url:             {ollama.get('url', '-')}")
    click.echo(f"    embedding_model: {ollama.get('embedding_model', '-')}")
    click.echo(f"    auxiliary_model: {ollama.get('auxiliary_model', '-')}")
    click.echo(f"  Database:          {(cfg.get('database') or {}).get('path', '-')}")

    targets = cfg.get("targets") or []
    click.echo(f"\n  Targets ({len(targets)}):")
    if not targets:
        click.echo("    (none — run `bindwood add`)")
        return
    for i, t in enumerate(targets, 1):
        ttype = t.get("type", "?")
        name = t.get("name", "unnamed")
        click.echo(f"    {i}. [{ttype}] {name}")
        if ttype == "ddl":
            click.echo(f"       file:    {t.get('file', '-')}")
            click.echo(f"       dialect: {t.get('dialect', 'postgres')}")
        elif ttype in ("javascript", "typescript", "python"):
            click.echo(f"       root:    {t.get('root', '-')}")
            include = t.get("include", [])
            click.echo(f"       include: {', '.join(include[:4])}")
            if len(include) > 4:
                click.echo(f"                ... +{len(include) - 4} more")
        click.echo(f"       output:  {t.get('output', '-')}")


@cli.command("delete")
@click.argument("name", required=False)
def delete_cmd(name: str | None) -> None:
    """Remove a target from the config by name.

    If NAME is omitted, show an interactive selector. Rerun `bindwood scan`
    afterwards — the database is rebuilt from scratch on every scan, so
    the deleted target's rows will be purged then.
    """
    resolved = resolve_config_path()
    if not resolved:
        click.echo("No config found. Nothing to delete.")
        return
    cfg = _load_config_file(resolved)
    targets = cfg.get("targets") or []
    if not targets:
        click.echo("Config has no targets.")
        return

    if not name:
        names = [t.get("name", "") for t in targets if t.get("name")]
        click.echo("Existing targets:")
        for n in names:
            click.echo(f"  - {n}")
        name = click.prompt("Name to delete", type=click.Choice(names))

    match = [t for t in targets if t.get("name") == name]
    if not match:
        click.echo(f"No target named '{name}'.")
        return
    if not click.confirm(f"Remove target '{name}' ({match[0].get('type', '?')})?", default=False):
        return

    cfg["targets"] = [t for t in targets if t.get("name") != name]
    _save_config_file(resolved, cfg)
    click.echo(f"Removed '{name}'. ({len(cfg['targets'])} target(s) remaining)")
    click.echo("Run `bindwood scan` to rebuild the database without it.")


@cli.command("apikey")
@click.option("--show", is_flag=True, default=False, help="Print the current key (if any) and exit.")
@click.option("--clear", is_flag=True, default=False, help="Remove the stored key from config.")
def apikey_cmd(show: bool, clear: bool) -> None:
    """Generate, show, or clear the HTTP server API key.

    The key is stored under ``server.api_key`` in the config. The
    ``BINDWOOD_API_KEY`` env var always wins over the config value.
    """
    resolved = resolve_config_path()
    path = resolved if resolved else _active_config_path()
    cfg = _load_config_file(path)

    if show:
        current = (cfg.get("server") or {}).get("api_key")
        if current:
            click.echo(current)
        else:
            click.echo("No API key set.")
        return

    if clear:
        if "server" in cfg and "api_key" in cfg["server"]:
            del cfg["server"]["api_key"]
            if not cfg["server"]:
                del cfg["server"]
            _save_config_file(path, cfg)
            click.echo("API key cleared.")
        else:
            click.echo("No API key set — nothing to clear.")
        return

    import secrets
    key = secrets.token_urlsafe(32)
    cfg.setdefault("server", {})["api_key"] = key
    _save_config_file(path, cfg)
    click.echo(f"API key saved to {path} (server.api_key)")
    click.echo(f"Key: {key}")
    click.echo(
        "\nClients must send `Authorization: Bearer <key>`. "
        "Env var BINDWOOD_API_KEY always wins over this value if set."
    )


# ── Pipeline / server commands ───────────────────────────────


@cli.command("scan")
@click.option("--verbose", "-v", is_flag=True, default=False, help="Print full tracebacks on error.")
def scan(verbose: bool) -> None:
    """Extract graphs from configured targets and rebuild the database."""
    if scan_targets(verbose=verbose):
        click.echo("Project scanning completed")
    else:
        click.echo("Project scanning failed")


@cli.command("mcp")
def mcp_command() -> None:
    """Start the MCP stdio server."""
    from bindwood.servers.mcp import run as run_mcp

    run_mcp()


@cli.command("serve")
@click.option("--host", default="127.0.0.1", help="Bind host.")
@click.option("--port", default=8765, type=int, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Reload on code changes (dev).")
def serve(host: str, port: int, reload: bool) -> None:
    """Start the HTTP server. Requires the [http] extra."""
    try:
        from bindwood.servers.http import run as run_http
    except ImportError as e:
        click.echo(f"Error: {e}")
        raise SystemExit(1)
    click.echo(f"Serving HTTP on http://{host}:{port}  (docs: /docs)")
    run_http(host=host, port=port, reload=reload)


def _mark(ok: bool) -> str:
    return "[ OK ]" if ok else "[FAIL]"


@cli.command("doctor")
def doctor_cmd() -> None:
    """End-to-end health check: config, database, Ollama, models, targets."""
    from bindwood.db.embeddings import check_model, check_ollama

    problems = 0

    # ── Config ───────────────────────────────────────────────
    cfg_path = resolve_config_path()
    cfg: dict = {}
    click.echo("Config:")
    if not cfg_path:
        click.echo(f"  {_mark(False)} no config found — run `bindwood init`")
        problems += 1
    else:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            click.echo(f"  {_mark(True)} {cfg_path}")
        except (OSError, json.JSONDecodeError) as e:
            click.echo(f"  {_mark(False)} {cfg_path} — unreadable: {e}")
            problems += 1

    # ── Targets ──────────────────────────────────────────────
    targets = cfg.get("targets") or []
    click.echo("\nTargets:")
    if not targets:
        click.echo(f"  {_mark(False)} none configured — run `bindwood add`")
        problems += 1
    else:
        click.echo(f"  {_mark(True)} {len(targets)} configured")
        for t in targets:
            click.echo(f"         - [{t.get('type', '?')}] {t.get('name', '?')}")

    # ── Database ─────────────────────────────────────────────
    click.echo("\nDatabase:")
    db_path = resolve_db_path(config=cfg)
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        click.echo(f"  {_mark(True)} {db_path} ({size_mb:.1f} MB)")
    else:
        click.echo(f"  {_mark(False)} {db_path} — run `bindwood scan` to build it")
        problems += 1

    # ── Ollama ───────────────────────────────────────────────
    settings = get_ollama_settings(cfg)
    url = settings["url"]
    embedding_model = settings["embedding_model"]
    auxiliary_model = settings["auxiliary_model"]

    click.echo("\nOllama:")
    reachable = check_ollama(url)
    click.echo(f"  {_mark(reachable)} reachable at {url}")
    if not reachable:
        click.echo("         embeddings + summaries will be skipped on scan")
        problems += 1
        click.echo(f"\n{problems} issue(s) found.")
        raise SystemExit(1 if problems else 0)

    emb_ok = check_model(url, embedding_model)
    click.echo(f"  {_mark(emb_ok)} embedding model: {embedding_model}")
    if not emb_ok:
        click.echo("         scan will attempt to pull it automatically")
        problems += 1

    aux_ok = check_model(url, auxiliary_model)
    click.echo(f"  {_mark(aux_ok)} auxiliary model: {auxiliary_model}")
    if not aux_ok:
        click.echo(
            f"         summaries will be skipped. Install with: "
            f"`ollama pull {auxiliary_model}`"
        )

    # ── Summary ──────────────────────────────────────────────
    if problems == 0:
        click.echo("\nAll checks passed.")
    else:
        click.echo(f"\n{problems} issue(s) found.")
    raise SystemExit(1 if problems else 0)


@cli.command("ollama-status", hidden=True)
@click.pass_context
def ollama_status(ctx: click.Context) -> None:
    """Deprecated alias — use `bindwood doctor`."""
    ctx.invoke(doctor_cmd)


# ── query subgroup ───────────────────────────────────────────


@cli.group(help="Query the code graph database.")
@click.option("--db", default=None, help="Override database path.")
@click.pass_context
def query(ctx: click.Context, db: str | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["index"] = CodeIndex(db_path=db)


@query.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show database statistics."""
    idx: CodeIndex = ctx.obj["index"]
    o = idx.overview()

    click.echo("=== Targets ===")
    for t in o["targets"]:
        click.echo(f"  {t['name']} ({t['type']}) -> {t['root']}")
    click.echo("\n=== Node counts by type ===")
    for type_, cnt in o["node_counts_by_type"].items():
        click.echo(f"  {type_:25s} {cnt:>6d}")
    click.echo("\n=== Edge counts by type ===")
    for type_, cnt in o["edge_counts_by_type"].items():
        click.echo(f"  {type_:25s} {cnt:>6d}")
    click.echo("\n=== Summary ===")
    click.echo(f"  Total nodes:      {o['total_nodes']}")
    click.echo(f"  With source_text: {o['nodes_with_source_text']}")
    click.echo(f"  With summary:     {o['nodes_with_summary']}")
    click.echo(f"  With embeddings:  {o['nodes_with_embeddings']}")


@query.command()
@click.argument("query_text")
@click.option("--limit", "-n", default=10)
@click.option("--target", "-t", default=None)
@click.pass_context
def search(ctx: click.Context, query_text: str, limit: int, target: str | None) -> None:
    """Semantic similarity search."""
    idx: CodeIndex = ctx.obj["index"]
    try:
        results = idx.search(query_text, limit=limit, target=target)
    except RuntimeError as e:
        click.echo(f"Error: {e}")
        return
    click.echo(f'=== Semantic search: "{query_text}" ===\n')
    for i, r in enumerate(results, 1):
        click.echo(f"  {i}. [{r['type']}] {r['name']}")
        click.echo(f"     file: {r['file'] or '-'}:{r['line'] or ''}")
        click.echo(f"     target: {r['target']} | distance: {r['distance']}")
        if r.get("summary"):
            click.echo(f"     summary: {r['summary']}")
        if r.get("source_preview"):
            preview = r["source_preview"][:200].replace("\n", "\n     ")
            click.echo(f"     code: {preview}...")
        click.echo()


@query.command()
@click.argument("node_id")
@click.option("--target", "-t", default=None)
@click.pass_context
def node(ctx: click.Context, node_id: str, target: str | None) -> None:
    """Look up a specific node by ID (or partial match)."""
    idx: CodeIndex = ctx.obj["index"]
    rows = idx.get_node(node_id, target=target)
    if not rows:
        click.echo(f"No node found matching: {node_id}")
        return
    for row in rows[:10]:
        click.echo(f"=== {row['node_id']} ===")
        click.echo(f"  target:     {row['target']}")
        click.echo(f"  type:       {row['type']}")
        click.echo(f"  name:       {row['name']}")
        click.echo(f"  file:       {row['file'] or '-'}:{row['line'] or ''}")
        if row.get("summary"):
            click.echo(f"  summary:    {row['summary']}")
        if row.get("properties"):
            for k, v in row["properties"].items():
                if k == "source_text":
                    continue
                val = json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                if len(val) > 120:
                    val = val[:120] + "..."
                click.echo(f"  {k:12s} {val}")
        if row.get("source_text"):
            click.echo("\n  --- source ---")
            for line in row["source_text"][:1000].split("\n"):
                click.echo(f"  {line}")
        click.echo()
    if len(rows) > 10:
        click.echo(f"  ... and {len(rows) - 10} more matches")


@query.command()
@click.argument("node_id")
@click.option("--target", "-t", default=None)
@click.option("--direction", type=click.Choice(["in", "out", "both"]), default="both")
@click.option("--edge-type", default=None)
@click.pass_context
def neighbors(
    ctx: click.Context,
    node_id: str,
    target: str | None,
    direction: str,
    edge_type: str | None,
) -> None:
    """Show edges connected to a node (in and/or out)."""
    idx: CodeIndex = ctx.obj["index"]
    r = idx.get_neighbors(node_id, target=target, direction=direction, edge_type=edge_type)
    if r.get("not_found"):
        click.echo(f"No node found matching: {node_id}")
        return
    click.echo(f"=== Neighbors of {r['node_id']} ({r['target']}) ===\n")
    if r["outgoing"]:
        click.echo("  Outgoing edges:")
        for e in r["outgoing"]:
            label = f"[{e['node_type'] or '?'}] {e['name'] or e['node_id']}"
            click.echo(f"    --{e['edge_type']}--> {label}")
    if r["incoming"]:
        click.echo("  Incoming edges:")
        for e in r["incoming"]:
            label = f"[{e['node_type'] or '?'}] {e['name'] or e['node_id']}"
            click.echo(f"    <--{e['edge_type']}-- {label}")
    if not r["outgoing"] and not r["incoming"]:
        click.echo("  No edges found.")


@query.command("slice")
@click.argument("seeds", nargs=-1, required=True)
@click.option("--depth", "-d", default=2)
@click.option("--direction", type=click.Choice(["out", "in", "both"]), default="out")
@click.option("--edge-kinds", default=None, help="Comma-separated edge types.")
@click.option("--max-nodes", default=200)
@click.option("--target", "-t", default=None)
@click.option("--json", "as_json", is_flag=True, default=False)
@click.pass_context
def slice_cmd(
    ctx: click.Context,
    seeds: tuple[str, ...],
    depth: int,
    direction: str,
    edge_kinds: str | None,
    max_nodes: int,
    target: str | None,
    as_json: bool,
) -> None:
    """Dependency slice: BFS transitive closure around seed nodes."""
    idx: CodeIndex = ctx.obj["index"]
    kinds = [k.strip() for k in edge_kinds.split(",")] if edge_kinds else None
    result = idx.slice(
        list(seeds),
        target=target,
        depth=depth,
        direction=direction,
        edge_kinds=kinds,
        max_nodes=max_nodes,
    )

    if result.get("not_found"):
        click.echo(f"No nodes matched seeds: {', '.join(seeds)}")
        return
    if as_json:
        click.echo(json.dumps(result, indent=2, default=str))
        return

    s = result["stats"]
    click.echo(f'=== Slice: {len(result["seeds"])} seed(s), depth={depth}, dir={direction} ===')
    if kinds:
        click.echo(f"    edge-kinds: {', '.join(kinds)}")
    click.echo(
        f'    nodes: {s["node_count"]}  edges: {s["edge_count"]}  '
        f'max-depth-reached: {s["max_depth_reached"]}'
        f'{"  (TRUNCATED)" if result["truncated"] else ""}\n'
    )

    click.echo("  Seeds:")
    for seed in result["seeds"]:
        click.echo(f"    [{seed.get('type') or '?'}] {seed.get('name') or seed['id']}  ({seed['target']})")
    click.echo()

    by_depth: dict[int, list[dict]] = {}
    for n in result["nodes"]:
        by_depth.setdefault(n["depth"], []).append(n)
    for d in sorted(by_depth):
        if d == 0:
            continue
        click.echo(f"  -- depth {d} --")
        for n in by_depth[d]:
            loc = f"{n['file'] or '-'}:{n['line'] or ''}"
            click.echo(f"    [{n['type'] or '?'}] {n['name'] or n['id']}  ({loc})")
            if n["summary"]:
                summary = n["summary"]
                if len(summary) > 140:
                    summary = summary[:140] + "..."
                click.echo(f"        {summary}")
        click.echo()

    if result["edges"]:
        click.echo("  Edges:")
        for e in result["edges"][:50]:
            click.echo(f"    {e['source']}  --{e['type']}-->  {e['target']}")
        if len(result["edges"]) > 50:
            click.echo(f"    ... {len(result['edges']) - 50} more edges")


@query.command()
@click.option("--type", "node_type", default=None)
@click.option("--name", default=None)
@click.option("--target", "-t", default=None)
@click.option("--file", default=None)
@click.option("--label", default=None)
@click.option("--limit", "-n", default=20)
@click.pass_context
def find(
    ctx: click.Context,
    node_type: str | None,
    name: str | None,
    target: str | None,
    file: str | None,
    label: str | None,
    limit: int,
) -> None:
    """Find nodes by type, name, target, file, or label."""
    idx: CodeIndex = ctx.obj["index"]
    try:
        rows = idx.find_nodes(
            type=node_type, name=name, target=target, file=file, label=label, limit=limit
        )
    except ValueError as e:
        click.echo(f"Error: {e}")
        return
    if not rows:
        click.echo("No nodes found.")
        return
    click.echo(f"=== Found {len(rows)} node(s) ===\n")
    for row in rows:
        click.echo(f"  [{row['type']}] {row['name']}")
        click.echo(f"    id: {row['node_id']}")
        click.echo(f"    file: {row['file'] or '-'}:{row['line'] or ''} | target: {row['target']}")
        if row.get("summary"):
            click.echo(f"    summary: {row['summary']}")
        click.echo()


@query.command()
@click.argument("query_text")
@click.option("--limit", "-n", default=5)
@click.pass_context
def context(ctx: click.Context, query_text: str, limit: int) -> None:
    """Semantic search + expand graph context around each result."""
    idx: CodeIndex = ctx.obj["index"]
    try:
        hits = idx.search(query_text, limit=limit)
    except RuntimeError as e:
        click.echo(f"Error: {e}")
        return
    click.echo(f'=== Context search: "{query_text}" ===\n')
    for i, h in enumerate(hits, 1):
        click.echo("-" * 60)
        click.echo(f"  {i}. [{h['type']}] {h['name']}  (dist={h['distance']})")
        click.echo(f"     {h['file'] or '-'}:{h['line'] or ''} | {h['target']}")
        nb = idx.get_neighbors(h["node_id"], target=h["target"])
        for e in nb["incoming"][:5]:
            click.echo(
                f"     <-- {e['edge_type']} -- [{e['node_type'] or '?'}] "
                f"{e['name'] or e['node_id']}"
            )
        for e in nb["outgoing"][:5]:
            click.echo(
                f"     --> {e['edge_type']} --> [{e['node_type'] or '?'}] "
                f"{e['name'] or e['node_id']}"
            )
        if h.get("source_preview"):
            click.echo("\n     --- source (preview) ---")
            for line in h["source_preview"][:400].split("\n"):
                click.echo(f"     {line}")
        click.echo()


@query.command()
@click.argument("from_node")
@click.argument("to_node")
@click.option("--max-depth", default=3)
@click.option("--from-target", default=None)
@click.option("--to-target", default=None)
@click.pass_context
def trace(
    ctx: click.Context,
    from_node: str,
    to_node: str,
    max_depth: int,
    from_target: str | None,
    to_target: str | None,
) -> None:
    """Find how two nodes connect via BFS."""
    idx: CodeIndex = ctx.obj["index"]
    r = idx.trace_path(
        from_node,
        to_node,
        from_target=from_target,
        to_target=to_target,
        max_depth=max_depth,
    )
    click.echo(json.dumps(r, indent=2))


@query.command()
@click.pass_context
def tables(ctx: click.Context) -> None:
    """List all DDL tables with their columns."""
    idx: CodeIndex = ctx.obj["index"]
    rows = idx.find_nodes(type="table", limit=10000)
    if not rows:
        click.echo("No tables found.")
        return
    click.echo(f"=== {len(rows)} tables ===\n")
    for row in rows:
        schema = idx.get_table_schema(row["name"])
        if not schema.get("found"):
            continue
        cols = schema.get("columns", [])
        pk = schema.get("primary_key", [])
        col_names = [c["name"] for c in cols[:8]]
        suffix = f" ... +{len(cols) - 8}" if len(cols) > 8 else ""
        pk_str = f" (PK: {', '.join(pk)})" if pk else ""
        click.echo(f"  {schema['table']}{pk_str}")
        click.echo(f"    columns: {', '.join(col_names)}{suffix}")
        click.echo()


# ── Entry ────────────────────────────────────────────────────


def main() -> None:
    """Console-script entry point (``bindwood``)."""
    cli()


if __name__ == "__main__":
    main()

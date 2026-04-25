"""Public library API for bindwood.

Import :class:`Bindwood` to use bindwood programmatically from another
application without going through the CLI::

    from bindwood import Bindwood

    bw = Bindwood()
    results = bw.search("authentication middleware")
    for r in results:
        print(r["name"], r["file"])
"""

from __future__ import annotations

import inspect
import json
import secrets
from pathlib import Path
from typing import Any


class Bindwood:
    """Programmatic interface to a bindwood database.

    Wraps :class:`~bindwood.core.CodeIndex` for queries and the scan
    pipeline for extraction. All query methods return plain
    JSON-serialisable dicts/lists — no serialisation happens here.

    Parameters
    ----------
    db_path:
        Path to the SQLite database. Omit to use the default resolver
        chain (``BINDWOOD_DB`` env → config file → ``./graph/code_graph.db``).
    config_path:
        Path to the config JSON. Omit to use the default resolver chain
        (``BINDWOOD_CONFIG`` env → user config dir → ``./bindwood.json``).
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        config_path: str | Path | None = None,
    ) -> None:
        self._db_path = db_path
        self._config_path = config_path
        self._index: Any = None  # lazy — created on first query

    # ── Internal ─────────────────────────────────────────────

    def _get_index(self):
        if self._index is None:
            from bindwood.core import CodeIndex
            self._index = CodeIndex(
                db_path=self._db_path,
                config_path=self._config_path,
            )
        return self._index

    # ── Pipeline ─────────────────────────────────────────────

    def scan(self, *, verbose: bool = False) -> bool:
        """Run the full extraction pipeline.

        Extracts graphs from all configured targets, rebuilds the
        SQLite database, generates per-node summaries (auxiliary model),
        and produces vector embeddings (embedding model).

        Parameters
        ----------
        verbose:
            Print full tracebacks on error instead of short messages.

        Returns
        -------
        bool
            ``True`` on success, ``False`` if any stage failed.
        """
        from bindwood.scan import init as _scan
        return _scan(verbose=verbose)

    def rescan(self, name: str, *, verbose: bool = False) -> bool:
        """Re-run the pipeline for a single target.

        Only the named target's graph, summaries, and embeddings are
        rebuilt; other targets in the database are untouched. Use this
        to recover one project after a failed extraction or to pick up
        config edits without wiping the entire database.

        Parameters
        ----------
        name:
            Target name (must already exist in the config).
        verbose:
            Print full tracebacks on error instead of short messages.

        Returns
        -------
        bool
            ``True`` on success, ``False`` if the pipeline failed.

        Raises
        ------
        ValueError
            If no target with that name exists in the config.
        """
        if not any(t.get("name") == name for t in self.get_config().get("targets") or []):
            raise ValueError(f"No target named '{name}' in the config.")
        from bindwood.scan import rescan as _rescan
        return _rescan(name, verbose=verbose)

    # ── Overview ─────────────────────────────────────────────

    def overview(self) -> dict:
        """Database summary: targets, node/edge counts, coverage stats.

        Returns
        -------
        dict
            ``{targets, node_counts_by_type, edge_counts_by_type,
            total_nodes, nodes_with_source_text, nodes_with_summary,
            nodes_with_embeddings}``
        """
        return self._get_index().overview()

    # ── Search ───────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        target: str | None = None,
    ) -> list[dict]:
        """Semantic similarity search using vector embeddings.

        Requires Ollama to be running with the configured embedding model.

        Parameters
        ----------
        query:
            Natural-language description, e.g. ``"user authentication"``.
        limit:
            Maximum number of results (default 10).
        target:
            Restrict results to this target name.

        Returns
        -------
        list[dict]
            Each entry: ``{node_id, target, type, name, file, line,
            distance, summary, source_preview}``.

        Raises
        ------
        RuntimeError
            If Ollama is unreachable or embedding generation fails.
        """
        return self._get_index().search(query, limit=limit, target=target)

    # ── Structured lookup ────────────────────────────────────

    def find(
        self,
        *,
        type: str | None = None,
        name: str | None = None,
        target: str | None = None,
        file: str | None = None,
        label: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Find nodes by structured filters.

        At least one filter is required.

        Parameters
        ----------
        type:
            Node type: ``function``, ``class``, ``call``, ``file``,
            ``table``, ``view``, ``interface``, ``export``, etc.
        name:
            Name pattern. ``%`` is the SQL wildcard
            (e.g. ``"login%"`` matches ``login``, ``loginUser``).
        target:
            Target name.
        file:
            File path pattern (``%`` wildcard).
        label:
            Semantic label on call nodes, e.g. ``"http_route"``,
            ``"db_access"``, ``"auth_check"``.
        limit:
            Maximum results (default 20).

        Returns
        -------
        list[dict]
            Each entry: ``{node_id, target, type, name, file, line, summary}``.

        Raises
        ------
        ValueError
            If no filters are provided.
        """
        return self._get_index().find_nodes(
            type=type, name=name, target=target, file=file, label=label, limit=limit
        )

    # ── Single node ──────────────────────────────────────────

    def node(self, node_id: str, *, target: str | None = None) -> list[dict]:
        """Look up a node by ID, with partial-match fallback.

        Parameters
        ----------
        node_id:
            Full ID (e.g. ``"func::src/auth.ts::login"``) or a
            substring (e.g. ``"login"``).
        target:
            Optional target for disambiguation when IDs are ambiguous.

        Returns
        -------
        list[dict]
            Matching nodes with ``{node_id, target, type, name, file,
            line, summary, properties, source_text}``.
        """
        return self._get_index().get_node(node_id, target=target)

    # ── Neighbors ────────────────────────────────────────────

    def neighbors(
        self,
        node_id: str,
        *,
        target: str | None = None,
        direction: str = "both",
        edge_type: str | None = None,
    ) -> dict:
        """One-hop graph traversal from a node.

        Parameters
        ----------
        node_id:
            Full or partial node ID.
        target:
            Optional target name.
        direction:
            ``"out"`` (outgoing edges), ``"in"`` (incoming), or
            ``"both"`` (default).
        edge_type:
            Filter to a single edge type: ``imports``, ``exports``,
            ``contains``, ``fk``, ``depends_on``, ``extends``.

        Returns
        -------
        dict
            ``{node_id, target, outgoing: [...], incoming: [...]}``.
            Each edge entry includes the neighbour's type, name, and file.
        """
        return self._get_index().get_neighbors(
            node_id, target=target, direction=direction, edge_type=edge_type
        )

    # ── Slice ────────────────────────────────────────────────

    def slice(
        self,
        seeds: list[str] | str,
        *,
        depth: int = 2,
        direction: str = "out",
        edge_kinds: list[str] | None = None,
        max_nodes: int = 200,
        target: str | None = None,
    ) -> dict:
        """BFS transitive closure around one or more seed nodes.

        Parameters
        ----------
        seeds:
            One or more node IDs (full or partial) to start from.
        depth:
            Maximum number of hops (default 2).
        direction:
            ``"out"`` (dependencies), ``"in"`` (dependents), or ``"both"``.
        edge_kinds:
            Restrict traversal to these edge types, e.g.
            ``["imports", "contains"]``. ``None`` follows all edges.
        max_nodes:
            Hard cap on discovered nodes to prevent runaway traversals
            (default 200).
        target:
            Optional target name for seed resolution.

        Returns
        -------
        dict
            ``{seeds, nodes, edges, stats{node_count, edge_count,
            max_depth_reached}, truncated}``.
        """
        return self._get_index().slice(
            seeds,
            depth=depth,
            direction=direction,
            edge_kinds=edge_kinds,
            max_nodes=max_nodes,
            target=target,
        )

    # ── Trace ────────────────────────────────────────────────

    def trace(
        self,
        from_node: str,
        to_node: str,
        *,
        from_target: str | None = None,
        to_target: str | None = None,
        max_depth: int = 3,
    ) -> dict:
        """Find the shortest path between two nodes via BFS.

        Parameters
        ----------
        from_node:
            Origin node ID (full or partial).
        to_node:
            Destination node ID (full or partial).
        from_target:
            Optional target for origin disambiguation.
        to_target:
            Optional target for destination disambiguation.
        max_depth:
            Maximum hops to search (default 3, hard-capped at 5).

        Returns
        -------
        dict
            ``{found: bool, hops: int, path: [...]}``.
            Each path step includes the node and the edge traversed.
            If not found: ``{found: False, message: str}``.
        """
        return self._get_index().trace_path(
            from_node,
            to_node,
            from_target=from_target,
            to_target=to_target,
            max_depth=max_depth,
        )

    # ── Table schema ─────────────────────────────────────────

    def table_schema(self, table_name: str) -> dict:
        """Full DDL schema for a table.

        Parameters
        ----------
        table_name:
            Exact table name or a substring for fuzzy matching.

        Returns
        -------
        dict
            ``{found, table, columns, primary_key, unique_constraints,
            references, referenced_by}``.
        """
        return self._get_index().get_table_schema(table_name)

    # ── Servers ──────────────────────────────────────────────

    def serve_mcp(self) -> None:
        """Start the MCP stdio server (blocking).

        This is the same server that Claude Code spawns automatically
        when configured via ``mcpServers``. Call this directly only for
        testing or non-Claude MCP clients.
        """
        from bindwood.servers.mcp import run as _run_mcp
        _run_mcp()

    def serve_http(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        reload: bool = False,
    ) -> None:
        """Start the FastAPI HTTP server (blocking).

        Requires the ``[http]`` extra (``pip install bindwood[http]``).

        Parameters
        ----------
        host:
            Bind address (default ``"127.0.0.1"``).
        port:
            Bind port (default ``8765``).
        reload:
            Enable auto-reload on code changes (development only).
        """
        try:
            from bindwood.servers.http import run as _run_http
        except ImportError as exc:
            raise ImportError(
                "HTTP server requires the [http] extra: "
                "pip install 'bindwood[http]'"
            ) from exc
        _run_http(host=host, port=port, reload=reload)

    # ── Config management ────────────────────────────────────

    @staticmethod
    def _config_write_path() -> Path:
        from bindwood.config.resolver import user_config_path
        return user_config_path()

    @staticmethod
    def _load_cfg(path: Path) -> dict:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "version": 1,
            "ollama": {},
            "database": {"path": "graph/code_graph.db"},
            "targets": [],
        }

    @staticmethod
    def _save_cfg(path: Path, cfg: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def reset_config(self, *, force: bool = False) -> Path:
        """Reset the config file to factory defaults.

        The existing file is backed up as ``config.json.bak`` before
        being overwritten, unless ``force=True``.

        Parameters
        ----------
        force:
            Skip the backup and overwrite directly.

        Returns
        -------
        Path
            Path to the reset config file.
        """
        import shutil
        path = self._config_write_path()
        if path.exists() and not force:
            shutil.copy2(path, path.with_suffix(".json.bak"))
        defaults = {
            "version": 1,
            "ollama": {
                "url": "http://localhost:11434",
                "embedding_model": "nomic-embed-text",
                "auxiliary_model": "qwen2.5-coder:1.5b",
            },
            "database": {"path": "graph/code_graph.db"},
            "targets": [],
        }
        self._save_cfg(path, defaults)
        return path

    def get_config(self) -> dict:
        """Return the active config as a dict.

        Reads from the same resolver chain used by the CLI
        (env var → user config dir → ``./bindwood.json`` → defaults).

        Returns
        -------
        dict
            The full config including ``ollama``, ``database``,
            ``server``, and ``targets`` sections.
        """
        from bindwood.config.resolver import resolve_config_path
        from bindwood.config import load_raw_config
        path = resolve_config_path(self._config_path)
        return load_raw_config(path) if path else {}

    def create_config(
        self,
        *,
        ollama_url: str = "http://localhost:11434",
        embedding_model: str = "nomic-embed-text",
        auxiliary_model: str = "qwen2.5-coder:1.5b",
        db_path: str = "graph/code_graph.db",
        overwrite: bool = False,
    ) -> Path:
        """Create the user config file.

        Writes to the canonical user config directory
        (``$XDG_CONFIG_HOME/bindwood/config.json`` on Linux/macOS,
        ``%APPDATA%\\bindwood\\config.json`` on Windows).

        Parameters
        ----------
        ollama_url:
            Ollama API endpoint (default ``http://localhost:11434``).
        embedding_model:
            Model used for vector embeddings (default ``nomic-embed-text``).
        auxiliary_model:
            Model used for per-node summaries (default ``qwen2.5-coder:1.5b``).
        db_path:
            SQLite output path, relative to workspace root or absolute
            (default ``graph/code_graph.db``).
        overwrite:
            Replace an existing config file if one exists. Raises
            ``FileExistsError`` when ``False`` and the file is present.

        Returns
        -------
        Path
            Path to the written config file.

        Raises
        ------
        FileExistsError
            If a config already exists and ``overwrite=False``.
        """
        path = self._config_write_path()
        if path.exists() and not overwrite:
            raise FileExistsError(
                f"Config already exists: {path}. Pass overwrite=True to replace it."
            )
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
        self._save_cfg(path, cfg)
        return path

    def add_target(self, target: dict, *, overwrite: bool = False) -> None:
        """Add a target to the config, or replace an existing one.

        Parameters
        ----------
        target:
            Target definition dict. Must contain at minimum ``"type"``
            and ``"name"``. See the configuration reference for the full
            schema per type:

            - :doc:`DDL </configuration/ddl-targets>` — ``type: "ddl"``
            - :doc:`JS/TS </configuration/jsts-targets>` — ``type: "javascript"`` or ``"typescript"``
            - :doc:`Python </configuration/python-targets>` — ``type: "python"``

        overwrite:
            Replace an existing target with the same name. Raises
            ``ValueError`` when ``False`` and the name is already present.

        Raises
        ------
        ValueError
            If ``target`` is missing ``"type"`` or ``"name"``, or if a
            target with the same name already exists and ``overwrite=False``.
        """
        if not target.get("type"):
            raise ValueError("target dict must include 'type'")
        if not target.get("name"):
            raise ValueError("target dict must include 'name'")

        path = self._config_write_path()
        cfg = self._load_cfg(path)
        targets: list[dict] = cfg.setdefault("targets", [])
        existing = [t for t in targets if t.get("name") == target["name"]]

        if existing and not overwrite:
            raise ValueError(
                f"Target '{target['name']}' already exists. Pass overwrite=True to replace it."
            )
        cfg["targets"] = [t for t in targets if t.get("name") != target["name"]]
        cfg["targets"].append(target)
        self._save_cfg(path, cfg)

    def get_target(self, name: str) -> dict | None:
        """Return a target's definition from the config by name.

        Parameters
        ----------
        name:
            Target name.

        Returns
        -------
        dict | None
            The target definition dict, or ``None`` if not found.
        """
        for t in self.get_config().get("targets") or []:
            if t.get("name") == name:
                return dict(t)
        return None

    def update_target(self, name: str, updates: dict) -> dict:
        """Update fields on an existing target in-place.

        The target name is immutable — database rows are keyed by name
        and a rename would orphan them. Use :meth:`delete_target` +
        :meth:`add_target` to rebuild under a new name instead.

        ``updates`` is shallow-merged onto the existing definition:
        keys present in ``updates`` replace the corresponding values;
        keys absent from ``updates`` are kept as-is. To fully replace
        the definition, pass every field you want to keep.

        Parameters
        ----------
        name:
            Name of the target to update.
        updates:
            Dict of fields to merge onto the existing definition. A
            ``"name"`` key in ``updates`` must match ``name`` if present.

        Returns
        -------
        dict
            The updated target definition.

        Raises
        ------
        ValueError
            If no target with that name exists, or if ``updates["name"]``
            differs from ``name``.
        """
        if "name" in updates and updates["name"] != name:
            raise ValueError(
                f"target name is immutable (got updates[name]={updates['name']!r}, "
                f"target is {name!r}). Use delete_target + add_target to rename."
            )
        path = self._config_write_path()
        cfg = self._load_cfg(path)
        targets: list[dict] = cfg.get("targets") or []
        idx = next((i for i, t in enumerate(targets) if t.get("name") == name), -1)
        if idx < 0:
            raise ValueError(f"No target named '{name}' in the config.")
        merged = {**targets[idx], **updates, "name": name}
        targets[idx] = merged
        cfg["targets"] = targets
        self._save_cfg(path, cfg)
        return merged

    def delete_target(self, name: str) -> bool:
        """Remove a target from the config by name.

        The database is rebuilt from scratch on the next ``scan()`` call,
        so the deleted target's rows are purged then.

        Parameters
        ----------
        name:
            Name of the target to remove.

        Returns
        -------
        bool
            ``True`` if the target was found and removed, ``False`` if no
            target with that name existed.
        """
        path = self._config_write_path()
        cfg = self._load_cfg(path)
        targets: list[dict] = cfg.get("targets") or []
        before = len(targets)
        cfg["targets"] = [t for t in targets if t.get("name") != name]
        if len(cfg["targets"]) == before:
            return False
        self._save_cfg(path, cfg)
        return True

    def set_api_key(self, key: str | None = None) -> str:
        """Generate (or store a provided) HTTP server API key.

        The key is stored under ``server.api_key`` in the config file.
        The ``BINDWOOD_API_KEY`` environment variable always takes
        precedence over the stored value at runtime.

        Parameters
        ----------
        key:
            A specific key to store. If ``None`` (default), a random
            URL-safe 32-byte token is generated automatically.

        Returns
        -------
        str
            The key that was stored.
        """
        path = self._config_write_path()
        cfg = self._load_cfg(path)
        if key is None:
            key = secrets.token_urlsafe(32)
        cfg.setdefault("server", {})["api_key"] = key
        self._save_cfg(path, cfg)
        return key

    def get_api_key(self) -> str | None:
        """Return the currently stored HTTP server API key, or ``None``.

        Returns
        -------
        str | None
            The key stored under ``server.api_key`` in the config, or
            ``None`` if no key has been set.
        """
        from bindwood.config.resolver import resolve_config_path
        path = resolve_config_path(self._config_path)
        if not path:
            return None
        cfg = self._load_cfg(path)
        return (cfg.get("server") or {}).get("api_key")

    def clear_api_key(self) -> bool:
        """Remove the stored HTTP server API key from the config.

        Returns
        -------
        bool
            ``True`` if a key was present and removed, ``False`` if there
            was nothing to remove.
        """
        path = self._config_write_path()
        cfg = self._load_cfg(path)
        server = cfg.get("server") or {}
        if "api_key" not in server:
            return False
        del server["api_key"]
        if not server:
            cfg.pop("server", None)
        else:
            cfg["server"] = server
        self._save_cfg(path, cfg)
        return True

    # ── Utilities ────────────────────────────────────────────

    @staticmethod
    def mcp_path() -> Path:
        """Return the absolute path to the MCP server file.

        Use this to build a Claude Code ``mcpServers`` config entry
        without hard-coding install locations. The CLI command
        ``bindwood mcp-path`` prints this path together with a
        ready-to-paste JSON snippet. Programmatic equivalent::

            import json
            from bindwood import Bindwood

            path = Bindwood.mcp_path()
            config = {
                "mcpServers": {
                    "code-graph": {
                        "command": "python",
                        "args": [str(path)],
                        "env": {"BINDWOOD_DB": "/path/to/code_graph.db"},
                    }
                }
            }
            print(json.dumps(config, indent=2))

        Returns
        -------
        Path
            Absolute path to ``bindwood/servers/mcp.py``.
        """
        import bindwood.servers.mcp as _mcp_module
        return Path(inspect.getfile(_mcp_module)).resolve()

    def close(self) -> None:
        """Close the database connection for the current thread."""
        if self._index is not None:
            self._index.close()

    def __enter__(self) -> "Bindwood":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        db = self._db_path or "(default)"
        return f"Bindwood(db_path={db!r})"

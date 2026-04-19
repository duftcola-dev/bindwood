"""CodeIndex — the read-side engine.

Owns one ``SqliteConnector`` plus the Ollama URL/model and exposes every
retrieval operation (search, lookup, neighbors, slice, trace, schema,
overview). All three wrappers (CLI, MCP, HTTP) sit on top of this class
so the query logic lives in exactly one place.

Return values are plain JSON-serializable dicts/lists. Each wrapper is
responsible for its own serialization (MCP → json.dumps, HTTP → FastAPI
response, CLI → pretty-print).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bindwood.config import get_ollama_settings, load_raw_config
from bindwood.config.resolver import (
    resolve_config_path,
    resolve_db_path,
)
from bindwood.core.connection import SqliteConnector
from bindwood.db.embeddings import embed_text
from bindwood.db.slicing import resolve_seeds, slice_graph


class CodeIndex:
    """Read-side facade over the code graph database.

    Parameters
    ----------
    db_path:
        Explicit path to the sqlite database. If omitted, resolved via
        ``BINDWOOD_DB`` env, the loaded config, or the default
        ``./graph/code_graph.db``.
    config_path:
        Explicit config file. If omitted, resolved via ``BINDWOOD_CONFIG``
        env, the user config dir, ``./bindwood.json``, or the in-repo
        legacy path.
    ollama_url / embedding_model:
        Override settings from config.

    Use ``CodeIndex()`` for the zero-config default, or pass explicit
    values for tests and non-default layouts.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        config_path: str | Path | None = None,
        ollama_url: str | None = None,
        embedding_model: str | None = None,
    ):
        cfg_path = resolve_config_path(config_path)
        cfg = load_raw_config(cfg_path) if cfg_path else {}
        settings = get_ollama_settings(cfg)

        self._ollama_url = ollama_url or settings["url"]
        self._embedding_model = embedding_model or settings["embedding_model"]
        self._db_path = resolve_db_path(db_path, config=cfg, config_path=cfg_path)
        self._connector = SqliteConnector(self._db_path)

    # ── Lifecycle ────────────────────────────────────────────

    def close(self) -> None:
        """Close the calling thread's connection."""
        self._connector.close_all()

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ── Overview ─────────────────────────────────────────────

    def overview(self) -> dict:
        """Targets, node/edge counts, and coverage stats."""
        conn = self._connector()

        targets = [
            {"name": r["name"], "type": r["type"], "root": r["root"]}
            for r in conn.execute("SELECT name, type, root FROM targets")
        ]
        node_counts = {
            r["type"]: r["cnt"]
            for r in conn.execute(
                "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type ORDER BY cnt DESC"
            )
        }
        edge_counts = {
            r["type"]: r["cnt"]
            for r in conn.execute(
                "SELECT type, COUNT(*) as cnt FROM edges GROUP BY type ORDER BY cnt DESC"
            )
        }
        total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        with_source = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE source_text IS NOT NULL"
        ).fetchone()[0]
        with_summary = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE summary IS NOT NULL AND summary != ''"
        ).fetchone()[0]
        with_emb = conn.execute("SELECT COUNT(*) FROM vec_embeddings").fetchone()[0]

        return {
            "targets": targets,
            "node_counts_by_type": node_counts,
            "edge_counts_by_type": edge_counts,
            "total_nodes": total,
            "nodes_with_source_text": with_source,
            "nodes_with_summary": with_summary,
            "nodes_with_embeddings": with_emb,
        }

    # ── Search ───────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 10,
        target: str | None = None,
    ) -> list[dict]:
        """Semantic vector search across embedded nodes."""
        vector = embed_text(self._ollama_url, self._embedding_model, query)
        if not vector:
            raise RuntimeError(
                "Could not generate embedding. Is Ollama running at "
                f"{self._ollama_url!r}?"
            )

        conn = self._connector()
        k = limit * 3 if target else limit
        rows = conn.execute(
            "SELECT node_id, target, distance FROM vec_embeddings "
            "WHERE embedding MATCH ? AND k = ?",
            [json.dumps(vector), k],
        ).fetchall()

        results: list[dict] = []
        for r in rows:
            tgt = r["target"]
            if target and tgt != target:
                continue
            orig_id = r["node_id"][len(tgt) + 2:]
            node = conn.execute(
                "SELECT type, name, file, line, source_text, summary "
                "FROM nodes WHERE id = ? AND target = ?",
                (orig_id, tgt),
            ).fetchone()
            if not node:
                continue
            entry = {
                "node_id": orig_id,
                "target": tgt,
                "type": node["type"],
                "name": node["name"],
                "file": node["file"],
                "line": node["line"],
                "distance": round(r["distance"], 4),
                "summary": node["summary"],
            }
            if node["source_text"]:
                entry["source_preview"] = node["source_text"][:500]
            results.append(entry)
            if len(results) >= limit:
                break

        return results

    # ── Structured lookup ────────────────────────────────────

    def find_nodes(
        self,
        *,
        type: str | None = None,
        name: str | None = None,
        target: str | None = None,
        file: str | None = None,
        label: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Filter the ``nodes`` table by any combination of fields."""
        conditions: list[str] = []
        params: list[Any] = []

        if type:
            conditions.append("type = ?")
            params.append(type)
        if name:
            conditions.append("name LIKE ?")
            params.append(name if "%" in name else f"%{name}%")
        if target:
            conditions.append("target = ?")
            params.append(target)
        if file:
            conditions.append("file LIKE ?")
            params.append(file if "%" in file else f"%{file}%")
        if label:
            conditions.append("properties LIKE ?")
            params.append(f'%"{label}"%')

        if not conditions:
            raise ValueError(
                "At least one filter required (type, name, target, file, or label)"
            )

        where = " AND ".join(conditions)
        conn = self._connector()
        rows = conn.execute(
            f"SELECT id, target, type, name, file, line, summary, properties "
            f"FROM nodes WHERE {where} LIMIT ?",
            params + [limit],
        ).fetchall()

        out: list[dict] = []
        for row in rows:
            entry = {
                "node_id": row["id"],
                "target": row["target"],
                "type": row["type"],
                "name": row["name"],
                "file": row["file"],
                "line": row["line"],
                "summary": row["summary"],
            }
            if row["properties"]:
                props = json.loads(row["properties"])
                for key in ("labels", "captured_arg", "params", "kind"):
                    if key in props:
                        entry[key] = props[key]
            out.append(entry)
        return out

    # ── Single node lookup ───────────────────────────────────

    def get_node(
        self, node_id: str, target: str | None = None
    ) -> list[dict]:
        """Look up a node by exact ID, with LIKE fallback."""
        conn = self._connector()
        cols = "id, target, type, name, file, line, source_text, summary, properties"

        if target:
            rows = conn.execute(
                f"SELECT {cols} FROM nodes WHERE id = ? AND target = ?",
                (node_id, target),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols} FROM nodes WHERE id = ?", (node_id,)
            ).fetchall()

        if not rows:
            like = f"%{node_id}%"
            if target:
                rows = conn.execute(
                    f"SELECT {cols} FROM nodes WHERE id LIKE ? AND target = ? LIMIT 5",
                    (like, target),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {cols} FROM nodes WHERE id LIKE ? LIMIT 5", (like,)
                ).fetchall()

        out: list[dict] = []
        for row in rows:
            entry = {
                "node_id": row["id"],
                "target": row["target"],
                "type": row["type"],
                "name": row["name"],
                "file": row["file"],
                "line": row["line"],
                "summary": row["summary"],
            }
            if row["properties"]:
                entry["properties"] = json.loads(row["properties"])
            if row["source_text"]:
                entry["source_text"] = row["source_text"]
            out.append(entry)
        return out

    # ── Neighbors ────────────────────────────────────────────

    def get_neighbors(
        self,
        node_id: str,
        target: str | None = None,
        direction: str = "both",
        edge_type: str | None = None,
    ) -> dict:
        """One-hop edges into and/or out of a node."""
        if direction not in ("in", "out", "both"):
            raise ValueError(f"direction must be in/out/both, got {direction!r}")

        conn = self._connector()
        if target:
            row = conn.execute(
                "SELECT id, target FROM nodes WHERE id = ? AND target = ?",
                (node_id, target),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, target FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id, target FROM nodes WHERE id LIKE ? LIMIT 1",
                (f"%{node_id}%",),
            ).fetchone()
        if not row:
            return {"node_id": node_id, "target": target, "outgoing": [], "incoming": [],
                    "not_found": True}

        nid, tgt = row["id"], row["target"]
        result: dict = {"node_id": nid, "target": tgt, "outgoing": [], "incoming": []}

        base_select = (
            "SELECT {ref} AS neighbor, e.type, e.properties, "
            "n.type AS n_type, n.name AS n_name, n.file AS n_file, n.line AS n_line "
            "FROM edges e LEFT JOIN nodes n ON n.id = {ref} AND n.target = e.target "
            "WHERE {where} AND e.target = ?"
        )

        def _collect(direction_key: str, ref_col: str, where_col: str, bucket: str):
            query = base_select.format(ref=f"e.{ref_col}", where=f"e.{where_col} = ?")
            params = [nid, tgt]
            if edge_type:
                query += " AND e.type = ?"
                params.append(edge_type)
            for e in conn.execute(query, params).fetchall():
                entry = {
                    "node_id": e["neighbor"],
                    "edge_type": e["type"],
                    "node_type": e["n_type"],
                    "name": e["n_name"],
                    "file": e["n_file"],
                    "line": e["n_line"],
                }
                if e["properties"]:
                    entry["edge_properties"] = json.loads(e["properties"])
                result[bucket].append(entry)

        if direction in ("out", "both"):
            _collect("out", "target_node", "source", "outgoing")
        if direction in ("in", "both"):
            _collect("in", "source", "target_node", "incoming")

        return result

    # ── Slicing ──────────────────────────────────────────────

    def slice(
        self,
        seeds: list[str] | str,
        *,
        target: str | None = None,
        depth: int = 2,
        direction: str = "out",
        edge_kinds: list[str] | None = None,
        max_nodes: int = 200,
    ) -> dict:
        """BFS transitive closure around seed nodes. Delegates to
        :func:`bindwood.db.slicing.slice_graph`."""
        conn = self._connector()
        resolved = resolve_seeds(conn, seeds, target=target)
        if not resolved:
            return {
                "seeds": [],
                "nodes": [],
                "edges": [],
                "truncated": False,
                "stats": {"node_count": 0, "edge_count": 0, "max_depth_reached": 0},
                "not_found": True,
            }
        return slice_graph(
            conn,
            resolved,
            depth=depth,
            direction=direction,
            edge_kinds=edge_kinds,
            max_nodes=max_nodes,
        )

    # ── Trace ────────────────────────────────────────────────

    def trace_path(
        self,
        from_node: str,
        to_node: str,
        *,
        from_target: str | None = None,
        to_target: str | None = None,
        max_depth: int = 3,
    ) -> dict:
        """Shortest path between two nodes via BFS over the edge graph."""
        conn = self._connector()
        max_depth = min(max_depth, 5)

        def _resolve(nid: str, tgt: str | None):
            if tgt:
                r = conn.execute(
                    "SELECT id, target FROM nodes WHERE id = ? AND target = ?",
                    (nid, tgt),
                ).fetchone()
            else:
                r = conn.execute(
                    "SELECT id, target FROM nodes WHERE id = ?", (nid,)
                ).fetchone()
            if not r:
                r = conn.execute(
                    "SELECT id, target FROM nodes WHERE id LIKE ? LIMIT 1",
                    (f"%{nid}%",),
                ).fetchone()
            return (r["id"], r["target"]) if r else (None, None)

        start_id, start_tgt = _resolve(from_node, from_target)
        end_id, end_tgt = _resolve(to_node, to_target)
        if not start_id:
            return {"found": False, "error": f"from_node not found: {from_node}"}
        if not end_id:
            return {"found": False, "error": f"to_node not found: {to_node}"}

        visited: set[tuple[str, str]] = {(start_id, start_tgt)}
        queue: list[list[tuple[str, str, str | None, str | None]]] = [
            [(start_id, start_tgt, None, None)]
        ]

        for _ in range(max_depth):
            next_queue: list[list[tuple[str, str, str | None, str | None]]] = []
            for path in queue:
                cur_id, cur_tgt, _, _ = path[-1]

                for r in conn.execute(
                    "SELECT target_node, type FROM edges WHERE source = ? AND target = ?",
                    (cur_id, cur_tgt),
                ):
                    key = (r["target_node"], cur_tgt)
                    if key in visited:
                        continue
                    visited.add(key)
                    new_path = path + [(r["target_node"], cur_tgt, r["type"], "->")]
                    if r["target_node"] == end_id:
                        return self._format_path(new_path)
                    next_queue.append(new_path)

                for r in conn.execute(
                    "SELECT source, type FROM edges WHERE target_node = ? AND target = ?",
                    (cur_id, cur_tgt),
                ):
                    key = (r["source"], cur_tgt)
                    if key in visited:
                        continue
                    visited.add(key)
                    new_path = path + [(r["source"], cur_tgt, r["type"], "<-")]
                    if r["source"] == end_id:
                        return self._format_path(new_path)
                    next_queue.append(new_path)

            queue = next_queue
            if not queue:
                break

        return {
            "found": False,
            "from": from_node,
            "to": to_node,
            "message": f"No path found within {max_depth} hops.",
        }

    def _format_path(self, path: list[tuple[str, str, str | None, str | None]]) -> dict:
        conn = self._connector()
        steps: list[dict] = []
        for node_id, tgt, edge_type, direction in path:
            n = conn.execute(
                "SELECT type, name, file, line FROM nodes WHERE id = ? AND target = ?",
                (node_id, tgt),
            ).fetchone()
            step = {
                "node_id": node_id,
                "target": tgt,
                "type": n["type"] if n else "unknown",
                "name": n["name"] if n else node_id,
                "file": n["file"] if n else None,
            }
            if edge_type:
                step["edge"] = f"{direction} {edge_type}"
            steps.append(step)
        return {"found": True, "hops": len(steps) - 1, "path": steps}

    # ── Table schema ─────────────────────────────────────────

    def get_table_schema(self, table_name: str) -> dict:
        """Full DDL schema for a table including FK relationships."""
        conn = self._connector()
        node_id = f"table::{table_name}"
        row = conn.execute(
            "SELECT id, name, source_text, properties FROM nodes "
            "WHERE id = ? AND type = 'table'",
            (node_id,),
        ).fetchone()

        if not row:
            rows = conn.execute(
                "SELECT id, name, source_text, properties FROM nodes "
                "WHERE type = 'table' AND name LIKE ?",
                (f"%{table_name}%",),
            ).fetchall()
            if not rows:
                return {"found": False, "error": f"No table found matching: {table_name}"}
            if len(rows) > 1:
                return {
                    "found": False,
                    "message": "Multiple tables match. Be more specific.",
                    "matches": [r["name"] for r in rows[:20]],
                }
            row = rows[0]

        result: dict = {
            "found": True,
            "table": row["name"],
            "description": row["source_text"],
        }
        if row["properties"]:
            props = json.loads(row["properties"])
            result["columns"] = props.get("columns", [])
            result["primary_key"] = props.get("primary_key", [])
            result["unique_constraints"] = props.get("unique_constraints", [])

        outgoing = conn.execute(
            "SELECT target_node, properties FROM edges WHERE source = ? AND type = 'fk'",
            (row["id"],),
        ).fetchall()
        incoming = conn.execute(
            "SELECT source, properties FROM edges WHERE target_node = ? AND type = 'fk'",
            (row["id"],),
        ).fetchall()

        if outgoing:
            result["references"] = []
            for e in outgoing:
                ref = {"table": e["target_node"].replace("table::", "")}
                if e["properties"]:
                    ref.update(json.loads(e["properties"]))
                result["references"].append(ref)
        if incoming:
            result["referenced_by"] = []
            for e in incoming:
                ref = {"table": e["source"].replace("table::", "")}
                if e["properties"]:
                    ref.update(json.loads(e["properties"]))
                result["referenced_by"].append(ref)

        return result

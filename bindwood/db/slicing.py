"""Graph slicing — BFS transitive closure over the edges table.

A "slice" is the subgraph reachable from a set of seed nodes within a
given hop budget. It's the primary retrieval unit we want to hand to an
LLM: a semantic-search hit is rarely self-contained, but the hit plus
its immediate callers/callees usually is.

Single-target only for now — cross-target traversal belongs in a
follow-up that walks the `cross_references` table.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict


Seed = tuple[str, str]  # (id, target)


def resolve_seeds(
    conn: sqlite3.Connection,
    seeds: list[str] | str,
    target: str | None = None,
) -> list[Seed]:
    """Resolve string seeds to (id, target) pairs.

    Accepts exact node IDs; falls back to a single LIKE match. Matches
    the lookup behavior of the existing `query node` CLI so users can
    paste partial IDs from other commands.
    """
    if isinstance(seeds, str):
        seeds = [seeds]

    resolved: list[Seed] = []
    for s in seeds:
        if target:
            row = conn.execute(
                "SELECT id, target FROM nodes WHERE id = ? AND target = ?",
                (s, target),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, target FROM nodes WHERE id = ?", (s,)
            ).fetchone()

        if not row:
            pattern = f"%{s}%"
            if target:
                row = conn.execute(
                    "SELECT id, target FROM nodes WHERE id LIKE ? AND target = ? LIMIT 1",
                    (pattern, target),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id, target FROM nodes WHERE id LIKE ? LIMIT 1",
                    (pattern,),
                ).fetchone()

        if row:
            resolved.append((row[0], row[1]))

    return resolved


def _hydrate_nodes(
    conn: sqlite3.Connection, ids_by_target: dict[str, list[str]]
) -> dict[Seed, dict]:
    """Fetch compact node records for a set of (id, target) pairs."""
    out: dict[Seed, dict] = {}
    for tgt, ids in ids_by_target.items():
        if not ids:
            continue
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id, target, type, name, file, line, summary "
            f"FROM nodes WHERE target = ? AND id IN ({placeholders})",
            [tgt, *ids],
        ).fetchall()
        for r in rows:
            out[(r[0], r[1])] = {
                "id": r[0],
                "target": r[1],
                "type": r[2],
                "name": r[3],
                "file": r[4],
                "line": r[5],
                "summary": r[6],
            }
    return out


def _expand_frontier(
    conn: sqlite3.Connection,
    frontier: list[Seed],
    direction: str,
    edge_kinds: list[str] | None,
) -> list[tuple[Seed, Seed, str]]:
    """Return (src, dst, edge_type) triples for edges leaving the frontier.

    Works single-target: all seeds in the frontier share a target (BFS
    preserves this because every discovered node carries its target).
    For 'both', unions the two directed queries.
    """
    triples: list[tuple[Seed, Seed, str]] = []

    by_target: dict[str, list[str]] = defaultdict(list)
    for nid, tgt in frontier:
        by_target[tgt].append(nid)

    for tgt, ids in by_target.items():
        placeholders = ",".join("?" * len(ids))
        kind_clause = ""
        kind_params: list[str] = []
        if edge_kinds:
            kind_ph = ",".join("?" * len(edge_kinds))
            kind_clause = f" AND type IN ({kind_ph})"
            kind_params = list(edge_kinds)

        if direction in ("out", "both"):
            rows = conn.execute(
                f"SELECT source, target_node, type FROM edges "
                f"WHERE target = ? AND source IN ({placeholders}){kind_clause}",
                [tgt, *ids, *kind_params],
            ).fetchall()
            for src, dst, etype in rows:
                triples.append(((src, tgt), (dst, tgt), etype))

        if direction in ("in", "both"):
            rows = conn.execute(
                f"SELECT source, target_node, type FROM edges "
                f"WHERE target = ? AND target_node IN ({placeholders}){kind_clause}",
                [tgt, *ids, *kind_params],
            ).fetchall()
            for src, dst, etype in rows:
                triples.append(((src, tgt), (dst, tgt), etype))

    return triples


def slice_graph(
    conn: sqlite3.Connection,
    seeds: list[Seed],
    *,
    depth: int = 2,
    direction: str = "out",
    edge_kinds: list[str] | None = None,
    max_nodes: int = 200,
) -> dict:
    """Return the BFS closure around `seeds` up to `depth` hops.

    direction:
      'out'  — follow source -> target_node (downstream / callees / deps)
      'in'   — follow target_node -> source (upstream / callers / referrers)
      'both' — union of the two

    edge_kinds: if given, only traverse edges whose `type` is in the list.
    max_nodes: hard cap on distinct nodes in the result; BFS stops early
               and sets `truncated=True` when hit.
    """
    if direction not in ("out", "in", "both"):
        raise ValueError(f"direction must be out/in/both, got {direction!r}")

    if not seeds:
        return {
            "seeds": [],
            "nodes": [],
            "edges": [],
            "truncated": False,
            "stats": {"node_count": 0, "edge_count": 0, "max_depth_reached": 0},
        }

    # depth map: (id, target) -> first-seen depth
    node_depth: dict[Seed, int] = {s: 0 for s in seeds}
    edges_found: list[tuple[Seed, Seed, str]] = []
    truncated = False
    max_depth_reached = 0

    frontier = list(seeds)
    for d in range(1, depth + 1):
        if not frontier:
            break

        triples = _expand_frontier(conn, frontier, direction, edge_kinds)
        next_frontier: list[Seed] = []

        for src, dst, etype in triples:
            edges_found.append((src, dst, etype))
            # The *new* node is whichever end hasn't been seen yet.
            for candidate in (src, dst):
                if candidate in node_depth:
                    continue
                if len(node_depth) >= max_nodes:
                    truncated = True
                    continue
                node_depth[candidate] = d
                next_frontier.append(candidate)

        if next_frontier:
            max_depth_reached = d
        frontier = next_frontier

        if truncated:
            break

    # Hydrate all discovered nodes.
    ids_by_target: dict[str, list[str]] = defaultdict(list)
    for nid, tgt in node_depth:
        ids_by_target[tgt].append(nid)
    hydrated = _hydrate_nodes(conn, ids_by_target)

    nodes_out: list[dict] = []
    for pair, d in node_depth.items():
        rec = hydrated.get(pair)
        if not rec:
            # Edge pointed at a node we don't have a row for — surface it
            # minimally so the caller can still see the reference.
            rec = {
                "id": pair[0],
                "target": pair[1],
                "type": None,
                "name": None,
                "file": None,
                "line": None,
                "summary": None,
            }
        nodes_out.append({**rec, "depth": d})
    nodes_out.sort(key=lambda r: (r["depth"], r["target"], r["id"]))

    # Deduplicate edges — the same edge can surface twice when direction
    # is 'both' or when both endpoints are rediscovered at the boundary.
    seen_edges: set[tuple[Seed, Seed, str]] = set()
    edges_out: list[dict] = []
    for src, dst, etype in edges_found:
        key = (src, dst, etype)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        # Keep only edges whose *both* endpoints survived the budget.
        if src not in node_depth or dst not in node_depth:
            continue
        edges_out.append({
            "source": src[0],
            "target": dst[0],
            "target_name": dst[1],  # the sqlite column `target` = scope name
            "source_target": src[1],
            "type": etype,
            "from_depth": node_depth[src],
            "to_depth": node_depth[dst],
        })

    seeds_out = [
        {
            "id": s[0],
            "target": s[1],
            **{k: hydrated.get(s, {}).get(k) for k in ("type", "name", "file", "line", "summary")},
        }
        for s in seeds
    ]

    return {
        "seeds": seeds_out,
        "nodes": nodes_out,
        "edges": edges_out,
        "truncated": truncated,
        "stats": {
            "node_count": len(nodes_out),
            "edge_count": len(edges_out),
            "max_depth_reached": max_depth_reached,
        },
    }

"""Generate embeddings via Ollama and store in sqlite-vec."""

from __future__ import annotations

import json
import sqlite3
import urllib.request
import urllib.error


def check_ollama(base_url: str) -> bool:
    """Check if Ollama is reachable."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def check_model(base_url: str, model: str) -> bool:
    """Check if the specified model is available in Ollama."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            model_names = [m["name"] for m in data.get("models", [])]
            # Match with or without :latest tag
            return model in model_names or f"{model}:latest" in model_names
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return False


def pull_model(base_url: str, model: str) -> bool:
    """Pull a model from Ollama registry."""
    try:
        payload = json.dumps({"name": model, "stream": False}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def embed_text(base_url: str, model: str, text: str) -> list[float] | None:
    """Generate an embedding vector for a text string."""
    try:
        payload = json.dumps({"model": model, "input": text}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["embeddings"][0]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError, IndexError):
        return None


def embed_batch(base_url: str, model: str, texts: list[str]) -> list[list[float]] | None:
    """Generate embeddings for a batch of texts."""
    try:
        payload = json.dumps({"model": model, "input": texts}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data["embeddings"]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return None


MAX_EMBED_CHARS = 6000


def _compose_embed_text(
    kind: str,
    name: str | None,
    source_text: str | None,
    summary: str | None,
    properties_json: str | None,
) -> str | None:
    """Build the string we embed from signature + docstring + summary.

    We intentionally avoid embedding the raw body: large bodies either
    overflow the embedding context or produce diffuse vectors. The summary
    plus signature is dense, semantic, and always fits.
    """
    try:
        props = json.loads(properties_json) if properties_json else {}
    except (json.JSONDecodeError, TypeError):
        props = {}

    # source_preview is the first line of the body (signature for functions,
    # CREATE TABLE for tables, etc.). Fall back to the first line of
    # source_text when extractors didn't populate it.
    preview = props.get("source_preview")
    if not preview and source_text:
        preview = source_text.splitlines()[0] if source_text else ""

    docstring = props.get("docstring") or ""

    parts: list[str] = []
    header = f"{kind} {name}".strip() if name else kind
    parts.append(header)
    if preview:
        parts.append(str(preview).strip())
    if docstring:
        parts.append(str(docstring).strip())
    if summary:
        parts.append(summary.strip())

    text = "\n".join(p for p in parts if p).strip()
    if not text:
        return None
    # Cap defensively — we should be well under nomic-embed-text's 8192-token
    # window, but a huge docstring could in principle blow past it.
    return text if len(text) <= MAX_EMBED_CHARS else text[:MAX_EMBED_CHARS]


def generate_embeddings(
    conn: sqlite3.Connection,
    base_url: str,
    model: str,
    batch_size: int = 32,
    target_name: str | None = None,
) -> int:
    """Generate embeddings for all embeddable nodes.

    A node is embeddable if we can compose a non-empty search key for it
    (see _compose_embed_text). The embedding input is NOT the raw body.

    When ``target_name`` is given, only rows belonging to that target are
    embedded — used by the per-target rescan flow so we don't collide with
    the ``vec_embeddings`` primary key on unchanged targets.
    """
    sql = (
        "SELECT id, target, type, name, source_text, summary, properties "
        "FROM nodes "
        "WHERE source_text IS NOT NULL AND source_text != ''"
    )
    params: tuple = ()
    if target_name is not None:
        sql += " AND target = ?"
        params = (target_name,)
    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    if not rows:
        return 0

    prepared: list[tuple[str, str, str]] = []  # (node_id, target, embed_text)
    for node_id, target, kind, name, source_text, summary, properties in rows:
        text = _compose_embed_text(kind, name, source_text, summary, properties)
        if text:
            prepared.append((node_id, target, text))

    if not prepared:
        return 0

    total = 0
    for i in range(0, len(prepared), batch_size):
        batch = prepared[i : i + batch_size]
        texts = [b[2] for b in batch]

        vectors = embed_batch(base_url, model, texts)
        if vectors is None:
            print(f"  Warning: embedding batch {i // batch_size + 1} failed, skipping")
            continue

        insert_rows = []
        for (node_id, target, _), vector in zip(batch, vectors):
            vec_key = f"{target}::{node_id}"
            insert_rows.append((vec_key, target, json.dumps(vector)))

        conn.executemany(
            "INSERT INTO vec_embeddings (node_id, target, embedding) VALUES (?, ?, ?)",
            insert_rows,
        )
        total += len(insert_rows)

        if (i // batch_size + 1) % 10 == 0:
            print(f"  Embedded {total}/{len(prepared)} nodes...")

    conn.commit()
    return total

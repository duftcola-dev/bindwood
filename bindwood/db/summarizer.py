"""Generate per-node code summaries via an Ollama auxiliary model.

The summary is stored on the `summary` column of each node and later used
(alongside the signature and docstring) as the text input to the embedding
model. Summaries are semantically dense, so retrieval works well even when
the raw source would overflow the embedding model's context window.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


USER_TEMPLATE = """Describe what this code does. Use as few words as possible —
a short fragment is fine for trivial code; use up to 100 words only if the
logic genuinely needs it. No preamble, no markdown, no code. Focus on
domain concepts: what it computes, what it operates on, and any important
side effects. Do not restate the name.

[{kind}] {name}{location}
---
{source}
---"""


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    return text if len(text) <= max_chars else text[:max_chars] + "\n... [truncated]"


def summarize_text(
    base_url: str,
    model: str,
    kind: str,
    name: str | None,
    source: str,
    file: str | None = None,
    line: int | None = None,
    max_input_chars: int = 6000,
    timeout: int = 120,
) -> str | None:
    """Call the auxiliary model and return a summary string.

    Uses /api/chat so Ollama applies the model's chat template.
    """
    location = f"  ({file}:{line})" if file else ""
    user_msg = USER_TEMPLATE.format(
        kind=kind,
        name=name or "(unnamed)",
        location=location,
        source=_truncate(source, max_input_chars),
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": user_msg}],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 200},
    }).encode()
    try:
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None

    content = (data.get("message") or {}).get("content") or ""
    text = content.replace("\n", " ").strip()
    if text.lower().startswith("summary:"):
        text = text[len("summary:"):].strip()
    return text or None


def generate_summaries(
    conn: sqlite3.Connection,
    base_url: str,
    model: str,
    max_workers: int = 4,
    target_name: str | None = None,
) -> int:
    """Summarize each node that has source_text but no summary yet.

    Summary calls are fanned out across `max_workers` threads. The real
    parallelism ceiling is set by Ollama's `OLLAMA_NUM_PARALLEL` (default 4)
    and available VRAM — raising `max_workers` above that just queues on the
    server. DB writes stay on the calling thread.

    When ``target_name`` is given, only rows belonging to that target are
    processed — used by the per-target rescan flow.
    """
    sql = (
        "SELECT id, target, type, name, file, line, source_text "
        "FROM nodes "
        "WHERE source_text IS NOT NULL AND source_text != '' "
        "  AND (summary IS NULL OR summary = '')"
    )
    params: tuple = ()
    if target_name is not None:
        sql += " AND target = ?"
        params = (target_name,)
    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()
    if not rows:
        return 0

    total = 0
    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_row = {
            pool.submit(
                summarize_text, base_url, model, kind, name, source, file, line
            ): (node_id, target)
            for node_id, target, kind, name, file, line, source in rows
        }
        for future in as_completed(future_to_row):
            node_id, target = future_to_row[future]
            summary = future.result()
            if summary:
                conn.execute(
                    "UPDATE nodes SET summary = ? WHERE id = ? AND target = ?",
                    (summary, node_id, target),
                )
                total += 1

            done += 1
            if done % 10 == 0:
                conn.commit()
                print(f"  Summarized {done}/{len(rows)} nodes ({total} succeeded)")

    conn.commit()
    return total

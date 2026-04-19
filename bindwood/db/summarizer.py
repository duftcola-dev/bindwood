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


USER_TEMPLATE = """Write ONE sentence (max 30 words) describing what this code does.
No preamble, no markdown, no code. Focus on domain concepts: what it
computes, what it operates on, and any important side effects. Do not
restate the name.

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
    """Call the auxiliary model and return a single-sentence summary.

    Uses /api/chat so Ollama applies the model's chat template. Using
    /api/generate with an instruction-tuned model (e.g. gemma4:e4b) sends
    the prompt raw, and the model returns an empty response.
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
        # Reasoning models (e.g. gemma4:e4b) default to emitting thinking
        # tokens into a separate `thinking` channel. Without `think: false`
        # they burn the whole num_predict budget on thinking and content
        # comes back empty.
        "think": False,
        "options": {"temperature": 0.0, "num_predict": 160},
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
) -> int:
    """Summarize each node that has source_text but no summary yet."""
    cursor = conn.execute(
        "SELECT id, target, type, name, file, line, source_text "
        "FROM nodes "
        "WHERE source_text IS NOT NULL AND source_text != '' "
        "  AND (summary IS NULL OR summary = '')"
    )
    rows = cursor.fetchall()
    if not rows:
        return 0

    total = 0
    for i, row in enumerate(rows, 1):
        node_id, target, kind, name, file, line, source = row
        summary = summarize_text(base_url, model, kind, name, source, file, line)
        if summary:
            conn.execute(
                "UPDATE nodes SET summary = ? WHERE id = ? AND target = ?",
                (summary, node_id, target),
            )
            total += 1

        if i % 10 == 0:
            conn.commit()
            print(f"  Summarized {i}/{len(rows)} nodes ({total} succeeded)")

    conn.commit()
    return total

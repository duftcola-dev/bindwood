"""Shared config access — single source of truth for Ollama model names."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_AUXILIARY_MODEL = "gemma4:e4b"


def load_raw_config(config_path: str | Path) -> dict:
    """Load the full config JSON, or return an empty skeleton if missing."""
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_ollama_settings(cfg: dict) -> dict:
    """Return a normalized Ollama settings dict.

    Accepts both the legacy shape (`ollama.model` = embedding model) and the
    new shape (`ollama.embedding_model` + `ollama.auxiliary_model`).
    """
    ollama = cfg.get("ollama", {}) if cfg else {}
    # Prefer the new key, fall back to the legacy `model` field so existing
    # configs keep working without migration.
    embedding_model = (
        ollama.get("embedding_model")
        or ollama.get("model")
        or DEFAULT_EMBEDDING_MODEL
    )
    auxiliary_model = ollama.get("auxiliary_model") or DEFAULT_AUXILIARY_MODEL
    url = ollama.get("url") or DEFAULT_OLLAMA_URL
    return {
        "url": url,
        "embedding_model": embedding_model,
        "auxiliary_model": auxiliary_model,
    }

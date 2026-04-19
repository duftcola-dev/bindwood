"""Unified graph extractor + database pipeline.

Usage:
    bindwood scan                         # run all targets
    bindwood scan --target hub4retail-db  # run specific target(s)
    bindwood scan --no-embeddings         # skip embedding generation
    bindwood scan --config custom.json    # custom config file
    bindwood scan --verbose               # print full tracebacks on error
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

from bindwood.config import get_ollama_settings
from bindwood.config.resolver import resolve_config_path
from bindwood.registry import load_targets, run_target
from bindwood.db.schema import create_database
from bindwood.db.loader import load_jsts_graph, load_ddl_graph, load_python_graph
from bindwood.db.embeddings import (
    check_ollama,
    check_model,
    pull_model,
    generate_embeddings,
)
from bindwood.db.summarizer import generate_summaries


def load_config(config_path: Path) -> dict:
    """Load the full config file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_target_paths(targets: list[dict], workspace_root: Path) -> list[dict]:
    """Validate that target paths exist on disk. Returns only valid targets."""
    valid = []
    for t in targets:
        target_type = t.get("type", "").lower()
        name = t.get("name", "unknown")

        if target_type == "ddl":
            raw_path = Path(t["file"])
            file_path = raw_path if raw_path.is_absolute() else (workspace_root / t["file"]).resolve()
            if not file_path.exists():
                print(f"  SKIP {name}: DDL file not found: {file_path}")
                continue
        elif target_type in ("javascript", "typescript", "python"):
            raw_root = Path(t["root"])
            root_path = raw_root if raw_root.is_absolute() else (workspace_root / t["root"]).resolve()
            if not root_path.exists():
                print(f"  SKIP {name}: root directory not found: {root_path}")
                continue
        else:
            print(f"  SKIP {name}: unknown type '{target_type}'")
            continue

        valid.append(t)

    return valid


def init(verbose: bool = False) -> bool:
    try:
        workspace_root = Path.cwd()
        config_path = resolve_config_path()
        if config_path is None:
            print("Config not found. Run `bindwood init` to create one.")
            return False

        config = load_config(config_path)

        # ── 1. Ollama check ──────────────────────────────────────────
        ollama_settings = get_ollama_settings(config)
        ollama_url = ollama_settings["url"]
        embedding_model = ollama_settings["embedding_model"]
        auxiliary_model = ollama_settings["auxiliary_model"]
        do_embeddings = True
        do_summaries = False

        if do_embeddings:
            print(f"Checking Ollama at {ollama_url}...")
            if check_ollama(ollama_url):
                print(f"  Ollama: OK")
                if check_model(ollama_url, embedding_model):
                    print(f"  Embedding model '{embedding_model}': OK")
                else:
                    print(f"  Embedding model '{embedding_model}' not found. Pulling...")
                    if pull_model(ollama_url, embedding_model):
                        print(f"  Embedding model '{embedding_model}': pulled successfully")
                    else:
                        print(f"  Failed to pull '{embedding_model}'. Embeddings will be skipped.")
                        do_embeddings = False
                # Probe for auxiliary model without pulling automatically — it can
                # be several GB and the user may not want it eagerly fetched.
                if check_model(ollama_url, auxiliary_model):
                    print(f"  Auxiliary model '{auxiliary_model}': OK")
                    do_summaries = True
                else:
                    print(f"  Auxiliary model '{auxiliary_model}': not installed (summaries will be skipped)")
            else:
                print("  Ollama not reachable. Embeddings will be skipped.")
                do_embeddings = False
        else:
            print("Embeddings: disabled via --no-embeddings")

        # ── 2. Load and validate targets ─────────────────────────────
        targets = load_targets(config_path, workspace_root)
        print(f"\nValidating {len(targets)} target(s)...")
        targets = validate_target_paths(targets, workspace_root)

        if not targets:
            print("No valid targets found.")
            return False

        print(f"  {len(targets)} target(s) ready")

        # ── 3. Extract graphs ────────────────────────────────────────
        graphs: list[tuple[dict, dict]] = []  # (target_config, graph_data)

        for target in targets:
            graph = run_target(target, workspace_root)
            if graph:
                graphs.append((target, graph))

        if not graphs:
            print("\nNo graphs extracted.")
            return False

        # ── 4. Create database and load graphs ───────────────────────
        db_config = config.get("database", {})
        db_path_raw = db_config.get("path", "graph/code_graph.db")
        db_path = Path(db_path_raw) if Path(db_path_raw).is_absolute() else (workspace_root / db_path_raw).resolve()

        print(f"\n{'=' * 60}")
        print(f"Database: {db_path}")
        print(f"{'=' * 60}")

        conn = create_database(db_path)

        total_nodes = 0
        total_edges = 0

        for target, graph in graphs:
            target_type = target.get("type", "").lower()
            target_name = target["name"]

            if target_type == "ddl":
                n, e = load_ddl_graph(conn, graph, target_name)
            elif target_type == "python":
                n, e = load_python_graph(conn, graph, target_name)
            else:
                n, e = load_jsts_graph(conn, graph, target_name, target_type)

            total_nodes += n
            total_edges += e
            print(f"  Loaded {target_name}: {n} nodes, {e} edges")

        print(f"\nTotal: {total_nodes} nodes, {total_edges} edges")

        # ── 5. Generate per-node summaries (auxiliary model) ─────────
        if do_summaries:
            print(f"\n{'=' * 60}")
            print(f"Generating summaries ({auxiliary_model})")
            print(f"{'=' * 60}")
            summary_count = generate_summaries(conn, ollama_url, auxiliary_model)
            print(f"  Summarized {summary_count} nodes")
        else:
            print("\nSummaries: skipped (auxiliary model unavailable)")

        # ── 6. Generate embeddings ───────────────────────────────────
        if do_embeddings:
            print(f"\n{'=' * 60}")
            print(f"Generating embeddings ({embedding_model})")
            print(f"{'=' * 60}")

            count = generate_embeddings(conn, ollama_url, embedding_model)
            print(f"  Embedded {count} nodes")
        else:
            print("\nEmbeddings: skipped")

        conn.close()
        print(f"\nDone. Database: {db_path}")
        return True
    except Exception as error:
        if verbose:
            traceback.print_exc()
        else:
            print(f"{type(error).__name__}: {error}")
            print("Re-run with `bindwood scan --verbose` for the full traceback.")
        return False




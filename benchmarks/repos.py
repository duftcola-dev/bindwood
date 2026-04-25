"""Fixture repo definitions and MCP config generation.

Fixtures are declared in ``benchmarks/fixtures.toml`` (see fixtures.example.toml).
The bindwood MCP server resolves its own DB from the bindwood config, so the
harness just spawns ``bindwood mcp`` with no env override.
"""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


VALID_TYPES = {"ddl", "python", "javascript", "typescript"}


@dataclass
class Repo:
    name: str
    type: str           # ddl | python | javascript | typescript
    path: Path          # project root (code) or .sql file (ddl)
    target: str         # bindwood target name for MCP scoping


@dataclass
class FixtureConfig:
    repos: list[Repo]


def load_fixtures(path: Path) -> FixtureConfig:
    """Load and validate fixtures from a TOML file.

    Exits with a helpful error if any fixture path is missing — the harness
    depends on every referenced file existing before it runs.
    """
    if not path.exists():
        print(
            f"Error: fixtures file not found: {path}\n"
            f"Copy {path.parent / 'fixtures.example.toml'} to {path} and fill it in.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(path, "rb") as f:
        data = tomllib.load(f)

    repos: list[Repo] = []
    for entry in data.get("repos", []):
        name = entry.get("name")
        rtype = entry.get("type")
        repo_path = Path(entry["path"])
        target = entry.get("target") or name

        if rtype not in VALID_TYPES:
            print(
                f"Error: repo '{name}' has invalid type '{rtype}'. "
                f"Expected one of {sorted(VALID_TYPES)}.",
                file=sys.stderr,
            )
            sys.exit(1)

        # Code fixtures need a directory; DDL needs a file.
        if rtype == "ddl":
            if not repo_path.is_file():
                print(f"Error: DDL file for '{name}' missing: {repo_path}", file=sys.stderr)
                sys.exit(1)
        else:
            if not repo_path.is_dir():
                print(f"Error: repo path for '{name}' missing: {repo_path}", file=sys.stderr)
                sys.exit(1)

        repos.append(Repo(name=name, type=rtype, path=repo_path, target=target))

    if not repos:
        print(f"Error: no [[repos]] entries in {path}", file=sys.stderr)
        sys.exit(1)

    return FixtureConfig(repos=repos)


def write_shared_mcp_config(cache_dir: Path) -> Path:
    """Write the shared .mcp.json that points Claude at the bindwood MCP server.

    No DB path is passed — bindwood resolves its DB from its own config file.
    Overwritten on every call so stale configs don't linger across runs.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / "bindwood.mcp.json"
    config = {
        "mcpServers": {
            "bindwood": {
                "command": "bindwood",
                "args": ["mcp"],
            }
        }
    }
    out.write_text(json.dumps(config, indent=2))
    return out


def allowed_dirs(repo: Repo) -> list[Path]:
    """Return the directories to expose to Claude via --add-dir.

    For code fixtures, that's the project root. For DDL, it's the file's parent
    directory (Claude needs to be able to Read the .sql file in the baseline).
    """
    if repo.type == "ddl":
        return [repo.path.parent]
    return [repo.path]

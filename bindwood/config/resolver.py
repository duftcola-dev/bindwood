"""Config and database path resolution for library/CLI consumers.

Priority (highest first) for both the config file and the DB path:

    1. Explicit argument passed by the caller
    2. Environment variable (``BINDWOOD_CONFIG`` / ``BINDWOOD_DB``)
    3. User config dir (``$XDG_CONFIG_HOME/bindwood/config.json`` or
       ``%APPDATA%\\bindwood\\config.json`` on Windows)
    4. ``./bindwood.json`` in the current working directory
    5. The in-repo default (for source checkouts)

The CLI writes exclusively to the user config dir — humans shouldn't
hand-edit config files, they should go through ``bindwood init``,
``bindwood add``, ``bindwood delete``. The cwd / in-repo fallbacks
exist for source checkouts and for power users who pin a repo-local
config via ``BINDWOOD_CONFIG``.

Legacy ``gtg.json`` / ``GTG_CONFIG`` / ``GTG_DB`` names are still
accepted for one deprecation cycle so existing installs don't break.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


CONFIG_FILENAME = "bindwood.json"
CONFIG_ENV = "BINDWOOD_CONFIG"
DB_ENV = "BINDWOOD_DB"
API_KEY_ENV = "BINDWOOD_API_KEY"
APP_DIR_NAME = "bindwood"

LEGACY_CONFIG_FILENAME = "gtg.json"
LEGACY_CONFIG_ENV = "GTG_CONFIG"
LEGACY_DB_ENV = "GTG_DB"
LEGACY_API_KEY_ENV = "GTG_API_KEY"
LEGACY_REPO_CONFIG = Path("bindwood") / "config" / "config.json"

DEFAULT_DB_REL = Path("graph") / "code_graph.db"


def user_config_dir() -> Path:
    """Return the OS-appropriate user config directory for this app."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def user_config_path() -> Path:
    """Return the canonical file path the CLI writes to."""
    return user_config_dir() / "config.json"


def resolve_config_path(explicit: str | Path | None = None) -> Path | None:
    """Return the first existing config file in the priority chain.

    Returns ``None`` when no file is found anywhere — callers should
    treat that as "use built-in defaults".
    """
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    env_val = os.environ.get(CONFIG_ENV) or os.environ.get(LEGACY_CONFIG_ENV)
    if env_val:
        candidates.append(Path(env_val))
    candidates.append(user_config_path())
    candidates.append(Path.cwd() / CONFIG_FILENAME)
    candidates.append(Path.cwd() / LEGACY_CONFIG_FILENAME)
    candidates.append(Path.cwd() / LEGACY_REPO_CONFIG)

    for p in candidates:
        if p.is_file():
            return p.resolve()
    return None


def resolve_db_path(
    explicit: str | Path | None = None,
    config: dict | None = None,
    config_path: Path | None = None,  # kept for API symmetry; currently unused
) -> Path:
    """Return the database path to use for reads/writes.

    Priority: explicit arg → ``BINDWOOD_DB`` env (or legacy ``GTG_DB``) →
    ``database.path`` in the loaded config (resolved relative to cwd) →
    ``./graph/code_graph.db``.
    """
    if explicit:
        return Path(explicit).resolve()
    env_val = os.environ.get(DB_ENV) or os.environ.get(LEGACY_DB_ENV)
    if env_val:
        return Path(env_val).resolve()

    if config:
        db_raw = (config.get("database") or {}).get("path")
        if db_raw:
            p = Path(db_raw)
            if p.is_absolute():
                return p.resolve()
            return (Path.cwd() / p).resolve()

    return (Path.cwd() / DEFAULT_DB_REL).resolve()

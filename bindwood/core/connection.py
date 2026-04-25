"""Per-thread sqlite+vec connection manager.

The MCP stdio loop is single-threaded, so one connection is reused for
the life of the process. FastAPI dispatches SQL work through
`run_in_threadpool`; each worker thread gets its own connection via
`threading.local`, which keeps sqlite happy (connections are not
shareable across threads) and avoids reloading the sqlite-vec extension
on every request.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import sqlite_vec


class SqliteConnector:
    """Lazy per-thread connection factory.

    Usage:
        connector = SqliteConnector("graph/code_graph.db")
        conn = connector()          # first call per thread opens
        conn = connector()          # same thread → same connection
        connector.close_all()       # close the connection for *this* thread
    """

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._local = threading.local()

    def __call__(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
        return conn

    def _open(self) -> sqlite3.Connection:
        if not self._db_path.exists():
            raise FileNotFoundError(
                f"Database not found: {self._db_path}. Run `bindwood scan` first."
            )
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        # Per-connection; required for ON DELETE CASCADE on targets(name).
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def close_all(self) -> None:
        """Close the connection for the calling thread, if any.

        Only closes *this* thread's connection — sqlite3 cannot close a
        connection from a different thread than the one that opened it.
        Call this from each worker's shutdown hook if you need a clean
        exit.
        """
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    @property
    def db_path(self) -> Path:
        return self._db_path

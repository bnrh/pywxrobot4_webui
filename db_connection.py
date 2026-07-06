"""SQLite 连接复用（线程局部）。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

_thread_state = threading.local()


def get_sqlite_connection(db_path: str | Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    resolved_path = Path(db_path).resolve()
    cache_key = str(resolved_path)
    connections: dict[str, sqlite3.Connection] | None = getattr(_thread_state, "connections", None)
    if connections is None:
        connections = {}
        _thread_state.connections = connections

    connection = connections.get(cache_key)
    if connection is None:
        connection = sqlite3.connect(resolved_path, timeout=timeout, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        connections[cache_key] = connection
    return connection

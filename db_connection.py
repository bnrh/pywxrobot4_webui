"""SQLite 连接复用（线程局部）与写批处理。

FastAPI 异步场景下通过 check_same_thread=False + WAL 共享连接；
写操作使用进程内锁串行化，并以批量 commit 降低 fsync 频率。
消息量进一步增大时可再演进为独立写队列或 aiosqlite。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

_thread_state = threading.local()
_write_locks: dict[str, threading.RLock] = {}
_write_locks_guard = threading.Lock()
_pending_writes: dict[str, int] = {}
_pending_guard = threading.Lock()

DEFAULT_WRITE_FLUSH_EVERY = 8

# writer 返回此对象时，sqlite_execute_write 会立即 commit。
FLUSH_NOW = object()

T = TypeVar("T")


def _resolve_path(db_path: str | Path) -> str:
    return str(Path(db_path).resolve())


def _is_connection_closed(connection: sqlite3.Connection) -> bool:
    try:
        connection.total_changes
    except sqlite3.ProgrammingError:
        return True
    return False


def _write_lock_for(cache_key: str) -> threading.RLock:
    with _write_locks_guard:
        lock = _write_locks.get(cache_key)
        if lock is None:
            lock = threading.RLock()
            _write_locks[cache_key] = lock
        return lock


def _get_pending(cache_key: str) -> int:
    with _pending_guard:
        return int(_pending_writes.get(cache_key, 0))


def _set_pending(cache_key: str, value: int) -> None:
    with _pending_guard:
        if value <= 0:
            _pending_writes.pop(cache_key, None)
        else:
            _pending_writes[cache_key] = value


def get_pending_write_count(db_path: str | Path) -> int:
    return _get_pending(_resolve_path(db_path))


def get_sqlite_connection(db_path: str | Path, *, timeout: float = 5.0) -> sqlite3.Connection:
    cache_key = _resolve_path(db_path)
    connections: dict[str, sqlite3.Connection] | None = getattr(_thread_state, "connections", None)
    if connections is None:
        connections = {}
        _thread_state.connections = connections

    connection = connections.get(cache_key)
    if connection is not None and _is_connection_closed(connection):
        connections.pop(cache_key, None)
        connection = None

    if connection is None:
        Path(cache_key).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(cache_key, timeout=timeout, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = NORMAL")
        connections[cache_key] = connection
    return connection


def flush_sqlite_writes(db_path: str | Path) -> None:
    """将指定库上尚未提交的批量写立刻 commit。"""
    cache_key = _resolve_path(db_path)
    with _write_lock_for(cache_key):
        if _get_pending(cache_key) <= 0:
            return
        connection = get_sqlite_connection(cache_key)
        connection.commit()
        _set_pending(cache_key, 0)


def sqlite_execute_write(
    db_path: str | Path,
    writer: Callable[[sqlite3.Connection], T],
    *,
    flush_every: int = DEFAULT_WRITE_FLUSH_EVERY,
    immediate: bool = False,
) -> T:
    """在写锁内执行 writer；默认按 flush_every 批量 commit。

    writer 可返回 FLUSH_NOW，强制立刻提交（例如刚完成 trim）。
    """
    cache_key = _resolve_path(db_path)
    every = max(1, int(flush_every))
    with _write_lock_for(cache_key):
        connection = get_sqlite_connection(cache_key)
        result = writer(connection)
        force = immediate or result is FLUSH_NOW
        pending = _get_pending(cache_key) + 1
        if force or pending >= every:
            connection.commit()
            _set_pending(cache_key, 0)
        else:
            _set_pending(cache_key, pending)
        if result is FLUSH_NOW:
            return None  # type: ignore[return-value]
        return result


def sqlite_execute_read(db_path: str | Path, reader: Callable[[sqlite3.Connection], T]) -> T:
    """读前先 flush，保证读到本进程已缓冲的写入。"""
    flush_sqlite_writes(db_path)
    connection = get_sqlite_connection(db_path)
    return reader(connection)


def reset_sqlite_write_state_for_tests() -> None:
    """测试辅助：清空批量写计数（不断开连接）。"""
    with _pending_guard:
        _pending_writes.clear()

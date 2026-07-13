"""插件结构化日志 SQLite 持久化。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from config import SETTINGS_DB_PATH
from db_connection import get_sqlite_connection

PLUGIN_LOG_STORE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plugin_logs (
    internal_id INTEGER PRIMARY KEY,
    recorded_at TEXT NOT NULL,
    module TEXT NOT NULL DEFAULT '',
    plugin TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'INFO',
    scope TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    data_json TEXT NOT NULL DEFAULT 'null'
);
CREATE INDEX IF NOT EXISTS idx_plugin_logs_recorded_at
ON plugin_logs(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_plugin_logs_module
ON plugin_logs(module);
"""


class PluginLogStore:
    """高频写入时延迟清理：允许短暂超额，按批量阈值再裁剪到 limit。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        limit: int = 1000,
        trim_overflow: int | None = None,
        trim_every_writes: int | None = None,
    ):
        self.db_path = Path(db_path) if db_path else SETTINGS_DB_PATH
        self.limit = max(1, int(limit))
        self.trim_overflow = max(1, int(trim_overflow) if trim_overflow is not None else max(self.limit // 2, 32))
        self.trim_every_writes = max(
            1,
            int(trim_every_writes) if trim_every_writes is not None else max(self.limit // 4, 25),
        )
        self._writes_since_trim = 0
        self._approx_count = 0
        self._ensure_schema()
        self._approx_count = self._count_rows()

    def _ensure_schema(self) -> None:
        connection = get_sqlite_connection(self.db_path)
        connection.executescript(PLUGIN_LOG_STORE_SCHEMA_SQL)
        connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return get_sqlite_connection(self.db_path)

    def _count_rows(self) -> int:
        row = self._connect().execute("SELECT COUNT(*) AS total FROM plugin_logs").fetchone()
        return int(row["total"] or 0) if row else 0

    def _trim_to_limit(self, connection: sqlite3.Connection, *, commit: bool = True) -> None:
        connection.execute(
            """
            DELETE FROM plugin_logs
            WHERE internal_id NOT IN (
                SELECT internal_id FROM plugin_logs
                ORDER BY internal_id DESC
                LIMIT ?
            )
            """,
            (self.limit,),
        )
        if commit:
            connection.commit()
        self._approx_count = self._count_rows()
        self._writes_since_trim = 0

    def _maybe_trim(self, connection: sqlite3.Connection) -> None:
        soft_limit = self.limit + self.trim_overflow
        should_trim = self._approx_count > soft_limit or (
            self._writes_since_trim >= self.trim_every_writes and self._approx_count > self.limit
        )
        if should_trim:
            self._trim_to_limit(connection, commit=True)

    @staticmethod
    def _serialize_data(value: Any) -> str:
        if value in (None, "", [], {}):
            return "null"
        return json.dumps(value, ensure_ascii=False, default=str)

    def append_log(self, entry: dict[str, Any]) -> None:
        connection = self._connect()
        connection.execute(
            """
            INSERT OR REPLACE INTO plugin_logs(
                internal_id, recorded_at, module, plugin, level, scope, message, data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(entry["internal_id"]),
                str(entry.get("recorded_at") or ""),
                str(entry.get("module") or ""),
                str(entry.get("plugin") or entry.get("module") or ""),
                str(entry.get("level") or "INFO"),
                str(entry.get("scope") or ""),
                str(entry.get("message") or ""),
                self._serialize_data(entry.get("data")),
            ),
        )
        self._approx_count += 1
        self._writes_since_trim += 1
        connection.commit()
        self._maybe_trim(connection)

    def trim_now(self) -> None:
        """立即裁剪到 limit（测试或停机前可调用）。"""
        connection = self._connect()
        self._trim_to_limit(connection, commit=True)
        self._approx_count = self._count_rows()

    def load_recent(
        self,
        limit: int,
        *,
        module_name: str | None = None,
        level: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        effective_limit = max(1, min(int(limit), self.limit))
        normalized_level = str(level or "").strip().upper()
        normalized_keyword = str(keyword or "").strip().casefold()
        connection = self._connect()
        rows = connection.execute(
            """
            SELECT internal_id, recorded_at, module, plugin, level, scope, message, data_json
            FROM plugin_logs
            ORDER BY internal_id DESC
            LIMIT ?
            """,
            (self.limit,),
        ).fetchall()

        filtered: list[dict[str, Any]] = []
        for row in rows:
            item = {
                "internal_id": int(row["internal_id"]),
                "recorded_at": str(row["recorded_at"] or ""),
                "module": str(row["module"] or ""),
                "plugin": str(row["plugin"] or row["module"] or ""),
                "level": str(row["level"] or "INFO"),
                "scope": str(row["scope"] or ""),
                "message": str(row["message"] or ""),
                "data": json.loads(str(row["data_json"] or "null")) if str(row["data_json"] or "null") != "null" else None,
            }
            if module_name and item["module"] != module_name:
                continue
            if normalized_level and str(item.get("level") or "").upper() != normalized_level:
                continue
            if normalized_keyword:
                haystack = "\n".join(
                    part
                    for part in [
                        item.get("module") or "",
                        item.get("plugin") or "",
                        item.get("scope") or "",
                        item.get("message") or "",
                        json.dumps(item.get("data"), ensure_ascii=False, sort_keys=True, default=str) if item.get("data") is not None else "",
                    ]
                    if part
                ).casefold()
                if normalized_keyword not in haystack:
                    continue
            filtered.append(item)
        return filtered[:effective_limit], len(filtered)

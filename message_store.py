"""最近消息 SQLite 持久化。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from config import SETTINGS_DB_PATH
from db_connection import (
    DEFAULT_WRITE_FLUSH_EVERY,
    FLUSH_NOW,
    sqlite_execute_read,
    sqlite_execute_write,
)

MESSAGE_STORE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS recent_messages (
    internal_id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    processed_at TEXT,
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    msgid TEXT NOT NULL DEFAULT '',
    conversation_wxid TEXT NOT NULL DEFAULT '',
    sender_wxid TEXT NOT NULL DEFAULT '',
    msg_type INTEGER,
    local_type INTEGER,
    wxpid INTEGER,
    is_group_message INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL DEFAULT '',
    plugin_results_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_recent_messages_received_at
ON recent_messages(received_at DESC);
CREATE TABLE IF NOT EXISTS queue_rejections (
    internal_id INTEGER PRIMARY KEY,
    rejected_at TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT ''
);
"""


class RecentMessageStore:
    """高频写入时延迟清理：允许短暂超额，按批量阈值再裁剪到 limit。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        limit: int = 200,
        trim_overflow: int | None = None,
        trim_every_writes: int | None = None,
        write_flush_every: int | None = None,
    ):
        self.db_path = Path(db_path) if db_path else SETTINGS_DB_PATH
        self.limit = max(1, int(limit))
        # 允许超出 limit 的软缓冲，避免每条消息都 DELETE。
        self.trim_overflow = max(1, int(trim_overflow) if trim_overflow is not None else max(self.limit // 2, 32))
        self.trim_every_writes = max(
            1,
            int(trim_every_writes) if trim_every_writes is not None else max(self.limit // 4, 25),
        )
        self.write_flush_every = max(
            1,
            int(write_flush_every) if write_flush_every is not None else DEFAULT_WRITE_FLUSH_EVERY,
        )
        self._writes_since_trim = 0
        self._approx_count = 0
        self._ensure_schema()
        self._approx_count = self._count_rows()

    def _ensure_schema(self) -> None:
        def writer(connection: sqlite3.Connection) -> object:
            connection.executescript(MESSAGE_STORE_SCHEMA_SQL)
            return FLUSH_NOW

        sqlite_execute_write(self.db_path, writer, immediate=True)

    def _count_rows(self) -> int:
        def reader(connection: sqlite3.Connection) -> int:
            row = connection.execute("SELECT COUNT(*) AS total FROM recent_messages").fetchone()
            return int(row["total"] or 0) if row else 0

        return sqlite_execute_read(self.db_path, reader)

    def _trim_to_limit(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM recent_messages
            WHERE internal_id NOT IN (
                SELECT internal_id FROM recent_messages
                ORDER BY internal_id DESC
                LIMIT ?
            )
            """,
            (self.limit,),
        )
        row = connection.execute("SELECT COUNT(*) AS total FROM recent_messages").fetchone()
        self._approx_count = int(row["total"] or 0) if row else 0
        self._writes_since_trim = 0

    def _should_trim(self) -> bool:
        soft_limit = self.limit + self.trim_overflow
        return self._approx_count > soft_limit or (
            self._writes_since_trim >= self.trim_every_writes and self._approx_count > self.limit
        )

    @staticmethod
    def _serialize_json(value: Any, default: Any) -> str:
        try:
            return json.dumps(value if value is not None else default, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return json.dumps(default, ensure_ascii=False)

    @staticmethod
    def _deserialize_json(value: str, default: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    def load_recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        effective_limit = self.limit if limit is None else max(1, int(limit))

        def reader(connection: sqlite3.Connection) -> list[dict[str, Any]]:
            rows = connection.execute(
                """
                SELECT * FROM recent_messages
                ORDER BY internal_id DESC
                LIMIT ?
                """,
                (effective_limit,),
            ).fetchall()
            items: list[dict[str, Any]] = []
            for row in rows:
                items.append(
                    {
                        "internal_id": int(row["internal_id"]),
                        "received_at": str(row["received_at"] or ""),
                        "processed_at": row["processed_at"],
                        "status": str(row["status"] or ""),
                        "error": str(row["error"] or ""),
                        "msgid": str(row["msgid"] or ""),
                        "conversation_wxid": str(row["conversation_wxid"] or ""),
                        "sender_wxid": str(row["sender_wxid"] or ""),
                        "msg_type": row["msg_type"],
                        "local_type": row["local_type"],
                        "wxpid": row["wxpid"],
                        "is_group_message": bool(row["is_group_message"]),
                        "content": str(row["content"] or ""),
                        "plugin_results": self._deserialize_json(str(row["plugin_results_json"] or "[]"), []),
                        "payload": self._deserialize_json(str(row["payload_json"] or "{}"), {}),
                    }
                )
            return items

        return sqlite_execute_read(self.db_path, reader)

    def upsert_message(self, message: dict[str, Any]) -> None:
        internal_id = int(message["internal_id"])

        def writer(connection: sqlite3.Connection) -> object:
            connection.execute(
                """
                INSERT OR REPLACE INTO recent_messages(
                    internal_id, received_at, processed_at, status, error,
                    msgid, conversation_wxid, sender_wxid, msg_type, local_type, wxpid,
                    is_group_message, content, plugin_results_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    internal_id,
                    str(message.get("received_at") or ""),
                    message.get("processed_at"),
                    str(message.get("status") or ""),
                    str(message.get("error") or ""),
                    str(message.get("msgid") or ""),
                    str(message.get("conversation_wxid") or ""),
                    str(message.get("sender_wxid") or ""),
                    message.get("msg_type"),
                    message.get("local_type"),
                    message.get("wxpid"),
                    1 if message.get("is_group_message") else 0,
                    str(message.get("content") or ""),
                    self._serialize_json(message.get("plugin_results"), []),
                    self._serialize_json(message.get("payload"), {}),
                ),
            )
            # 新消息占绝大多数；偶发 REPLACE 导致计数略高可接受，裁剪时会纠正。
            self._approx_count += 1
            self._writes_since_trim += 1
            if self._should_trim():
                self._trim_to_limit(connection)
                return FLUSH_NOW
            return None

        sqlite_execute_write(self.db_path, writer, flush_every=self.write_flush_every)

    def trim_now(self) -> None:
        """立即裁剪到 limit（测试或停机前可调用）。"""

        def writer(connection: sqlite3.Connection) -> object:
            self._trim_to_limit(connection)
            return FLUSH_NOW

        sqlite_execute_write(self.db_path, writer, immediate=True)
        self._approx_count = self._count_rows()

    def record_queue_rejection(self, internal_id: int, reason: str) -> None:
        def writer(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT OR REPLACE INTO queue_rejections(internal_id, rejected_at, reason)
                VALUES (?, datetime('now', 'localtime'), ?)
                """,
                (int(internal_id), str(reason or "")),
            )

        sqlite_execute_write(self.db_path, writer, flush_every=self.write_flush_every)

    def count_queue_rejections(self) -> int:
        def reader(connection: sqlite3.Connection) -> int:
            row = connection.execute("SELECT COUNT(*) AS total FROM queue_rejections").fetchone()
            return int(row["total"] or 0) if row else 0

        return sqlite_execute_read(self.db_path, reader)

    def patch_message(self, internal_id: int, **updates: Any) -> None:
        if not updates:
            return
        allowed_fields = {
            "processed_at",
            "status",
            "error",
            "plugin_results",
            "content",
        }
        set_parts: list[str] = []
        values: list[Any] = []
        for key, value in updates.items():
            if key not in allowed_fields:
                continue
            if key == "plugin_results":
                set_parts.append("plugin_results_json = ?")
                values.append(self._serialize_json(value, []))
            else:
                set_parts.append(f"{key} = ?")
                values.append(value)
        if not set_parts:
            return
        values.append(int(internal_id))

        def writer(connection: sqlite3.Connection) -> None:
            connection.execute(
                f"UPDATE recent_messages SET {', '.join(set_parts)} WHERE internal_id = ?",
                values,
            )

        sqlite_execute_write(self.db_path, writer, flush_every=self.write_flush_every)

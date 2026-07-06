"""最近消息 SQLite 持久化。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from config import SETTINGS_DB_PATH
from db_connection import get_sqlite_connection

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
    def __init__(self, db_path: str | Path | None = None, *, limit: int = 200):
        self.db_path = Path(db_path) if db_path else SETTINGS_DB_PATH
        self.limit = max(1, int(limit))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        connection = get_sqlite_connection(self.db_path)
        connection.executescript(MESSAGE_STORE_SCHEMA_SQL)
        connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return get_sqlite_connection(self.db_path)

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
        connection = self._connect()
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

    def upsert_message(self, message: dict[str, Any]) -> None:
        internal_id = int(message["internal_id"])
        connection = self._connect()
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
        connection.commit()

    def record_queue_rejection(self, internal_id: int, reason: str) -> None:
        connection = self._connect()
        connection.execute(
            """
            INSERT OR REPLACE INTO queue_rejections(internal_id, rejected_at, reason)
            VALUES (?, datetime('now', 'localtime'), ?)
            """,
            (int(internal_id), str(reason or "")),
        )
        connection.commit()

    def count_queue_rejections(self) -> int:
        connection = self._connect()
        row = connection.execute("SELECT COUNT(*) AS total FROM queue_rejections").fetchone()
        return int(row["total"] or 0) if row else 0

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
        connection = self._connect()
        connection.execute(
            f"UPDATE recent_messages SET {', '.join(set_parts)} WHERE internal_id = ?",
            values,
        )
        connection.commit()

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from core.client import WxRobotApiClient
from core.config import SETTINGS_DB_PATH, PluginServiceSettings
from core.db_connection import (
    DEFAULT_WRITE_FLUSH_EVERY,
    FLUSH_NOW,
    get_sqlite_connection,
    sqlite_execute_read,
    sqlite_execute_write,
)


PLUGIN_STATE_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
CREATE TABLE IF NOT EXISTS plugin_state (
    plugin_id TEXT NOT NULL,
    namespace TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(plugin_id, namespace, key)
);
CREATE INDEX IF NOT EXISTS idx_plugin_state_plugin_namespace
ON plugin_state(plugin_id, namespace);
"""


def _ensure_parent_directory(file_path: Path) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_namespace(namespace: str | None) -> str:
    normalized = str(namespace or "default").strip()
    return normalized or "default"


class PluginStateStore:
    _initialization_lock = threading.Lock()
    _initialized_paths: set[Path] = set()

    def __init__(
        self,
        plugin_id: str,
        namespace: str = "default",
        storage_path: Path = SETTINGS_DB_PATH,
        *,
        write_flush_every: int | None = None,
    ):
        self.plugin_id = str(plugin_id)
        self.namespace_name = _normalize_namespace(namespace)
        self.storage_path = Path(storage_path)
        self.write_flush_every = max(
            1,
            int(write_flush_every) if write_flush_every is not None else DEFAULT_WRITE_FLUSH_EVERY,
        )
        self._ensure_initialized(self.storage_path)

    @classmethod
    def _ensure_initialized(cls, storage_path: Path) -> None:
        resolved_path = Path(storage_path)
        if resolved_path in cls._initialized_paths:
            return
        with cls._initialization_lock:
            if resolved_path in cls._initialized_paths:
                return
            _ensure_parent_directory(resolved_path)

            def writer(connection: sqlite3.Connection) -> object:
                connection.executescript(PLUGIN_STATE_SCHEMA_SQL)
                return FLUSH_NOW

            sqlite_execute_write(resolved_path, writer, immediate=True)
            cls._initialized_paths.add(resolved_path)

    def _connect(self) -> sqlite3.Connection:
        return get_sqlite_connection(self.storage_path)

    @staticmethod
    def _serialize(value: Any) -> str:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        return serialized if serialized is not None else "null"

    @staticmethod
    def _deserialize(value_json: str, default: Any = None) -> Any:
        try:
            return json.loads(value_json)
        except json.JSONDecodeError:
            return default

    def get(self, key: str, default: Any = None) -> Any:
        def reader(connection: sqlite3.Connection) -> Any:
            row = connection.execute(
                "SELECT value_json FROM plugin_state WHERE plugin_id = ? AND namespace = ? AND key = ?",
                (self.plugin_id, self.namespace_name, str(key)),
            ).fetchone()
            if row is None:
                return default
            return self._deserialize(str(row["value_json"]), default)

        return sqlite_execute_read(self.storage_path, reader)

    def set(self, key: str, value: Any) -> Any:
        def writer(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT OR REPLACE INTO plugin_state(plugin_id, namespace, key, value_json, updated_at)
                VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (self.plugin_id, self.namespace_name, str(key), self._serialize(value)),
            )

        sqlite_execute_write(self.storage_path, writer, flush_every=self.write_flush_every)
        return value

    def delete(self, key: str) -> bool:
        def writer(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                "DELETE FROM plugin_state WHERE plugin_id = ? AND namespace = ? AND key = ?",
                (self.plugin_id, self.namespace_name, str(key)),
            )
            return cursor.rowcount > 0

        return bool(sqlite_execute_write(self.storage_path, writer, flush_every=self.write_flush_every))

    def has(self, key: str) -> bool:
        def reader(connection: sqlite3.Connection) -> bool:
            row = connection.execute(
                "SELECT 1 FROM plugin_state WHERE plugin_id = ? AND namespace = ? AND key = ? LIMIT 1",
                (self.plugin_id, self.namespace_name, str(key)),
            ).fetchone()
            return row is not None

        return sqlite_execute_read(self.storage_path, reader)

    def keys(self) -> list[str]:
        def reader(connection: sqlite3.Connection) -> list[str]:
            rows = connection.execute(
                "SELECT key FROM plugin_state WHERE plugin_id = ? AND namespace = ? ORDER BY key",
                (self.plugin_id, self.namespace_name),
            ).fetchall()
            return [str(row["key"]) for row in rows]

        return sqlite_execute_read(self.storage_path, reader)

    def values(self) -> list[Any]:
        def reader(connection: sqlite3.Connection) -> list[Any]:
            rows = connection.execute(
                "SELECT value_json FROM plugin_state WHERE plugin_id = ? AND namespace = ? ORDER BY key",
                (self.plugin_id, self.namespace_name),
            ).fetchall()
            return [self._deserialize(str(row["value_json"])) for row in rows]

        return sqlite_execute_read(self.storage_path, reader)

    def entries(self) -> list[tuple[str, Any]]:
        def reader(connection: sqlite3.Connection) -> list[tuple[str, Any]]:
            rows = connection.execute(
                "SELECT key, value_json FROM plugin_state WHERE plugin_id = ? AND namespace = ? ORDER BY key",
                (self.plugin_id, self.namespace_name),
            ).fetchall()
            return [(str(row["key"]), self._deserialize(str(row["value_json"]))) for row in rows]

        return sqlite_execute_read(self.storage_path, reader)

    def get_all(self) -> dict[str, Any]:
        return dict(self.entries())

    def clear(self) -> int:
        def writer(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                "DELETE FROM plugin_state WHERE plugin_id = ? AND namespace = ?",
                (self.plugin_id, self.namespace_name),
            )
            return int(cursor.rowcount or 0)

        return int(sqlite_execute_write(self.storage_path, writer, flush_every=self.write_flush_every))

    def increment(self, key: str, amount: int | float = 1) -> int | float:
        current_value = self.get(key, 0)
        try:
            numeric_value = float(current_value)
        except (TypeError, ValueError):
            numeric_value = 0.0
        next_value = numeric_value + (float(amount) if isinstance(amount, float) else int(amount))
        if float(next_value).is_integer():
            next_value = int(next_value)
        return self.set(key, next_value)

    def namespace(self, namespace: str) -> "PluginStateStore":
        return PluginStateStore(
            self.plugin_id,
            namespace=namespace,
            storage_path=self.storage_path,
            write_flush_every=self.write_flush_every,
        )


class PluginLogger:
    def __init__(
        self,
        plugin_module: str,
        plugin_name: str,
        log_sink: Callable[[dict[str, Any]], None] | None = None,
        scope: str = "",
    ):
        self.plugin_module = plugin_module
        self.plugin_name = plugin_name
        self.log_sink = log_sink
        self.scope_name = str(scope or "").strip()

    def _emit(self, level: str, message: str, data: Any = None) -> None:
        normalized_level = str(level or "INFO").upper()
        normalized_message = str(message or "").strip()
        prefix = f"py-plugin {self.plugin_module}"
        if self.scope_name:
            prefix = f"{prefix} [{self.scope_name}]"

        if data in (None, "", [], {}):
            logger.log(normalized_level, "{} {}", prefix, normalized_message)
        else:
            logger.log(normalized_level, "{} {} | {}", prefix, normalized_message, json.dumps(data, ensure_ascii=False, default=str))

        if self.log_sink is not None:
            self.log_sink(
                {
                    "module": self.plugin_module,
                    "plugin": self.plugin_name,
                    "level": normalized_level,
                    "scope": self.scope_name,
                    "message": normalized_message,
                    "data": data,
                }
            )

    def debug(self, message: str, data: Any = None) -> None:
        self._emit("DEBUG", message, data)

    def info(self, message: str, data: Any = None) -> None:
        self._emit("INFO", message, data)

    def warning(self, message: str, data: Any = None) -> None:
        self._emit("WARNING", message, data)

    def warn(self, message: str, data: Any = None) -> None:
        self.warning(message, data)

    def error(self, message: str, data: Any = None) -> None:
        self._emit("ERROR", message, data)

    def scope(self, scope_name: str) -> "PluginLogger":
        next_scope = str(scope_name or "").strip()
        combined_scope = f"{self.scope_name}:{next_scope}" if self.scope_name and next_scope else next_scope or self.scope_name
        return PluginLogger(self.plugin_module, self.plugin_name, self.log_sink, combined_scope)


@dataclass(slots=True)
class PluginContext:
    settings: PluginServiceSettings
    api_client: WxRobotApiClient
    login_account_cache_getter: Callable[[], list[dict[str, Any]]] | None = None
    login_account_cache_refresher: Callable[[list[dict[str, Any]] | None], Awaitable[list[dict[str, Any]]]] | None = None
    login_account_serializer: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None

    @property
    def api(self) -> WxRobotApiClient:
        return self.api_client

    def get_cached_login_accounts(self) -> list[dict[str, Any]]:
        if not callable(self.login_account_cache_getter):
            return []
        cached_accounts = self.login_account_cache_getter()
        return list(cached_accounts) if isinstance(cached_accounts, list) else []

    async def refresh_cached_login_accounts(self, users: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if callable(self.login_account_cache_refresher):
            refreshed_accounts = await self.login_account_cache_refresher(users)
            return list(refreshed_accounts) if isinstance(refreshed_accounts, list) else []
        return self.serialize_login_accounts(users)

    def serialize_login_accounts(self, users: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        normalized_users = users if isinstance(users, list) else []
        if callable(self.login_account_serializer):
            serialized_accounts = self.login_account_serializer(normalized_users)
            return list(serialized_accounts) if isinstance(serialized_accounts, list) else []
        return list(normalized_users)


@dataclass(slots=True)
class PluginExecutionContext:
    settings: PluginServiceSettings
    api: WxRobotApiClient
    config: dict[str, Any]
    logger: PluginLogger
    state: PluginStateStore
    plugin_name: str
    plugin_module: str
    hot_reload: dict[str, Any] | None = None
    login_account_cache_getter: Callable[[], list[dict[str, Any]]] | None = None
    login_account_cache_refresher: Callable[[list[dict[str, Any]] | None], Awaitable[list[dict[str, Any]]]] | None = None
    login_account_serializer: Callable[[list[dict[str, Any]]], list[dict[str, Any]]] | None = None

    @property
    def api_client(self) -> WxRobotApiClient:
        return self.api

    @property
    def pluginName(self) -> str:
        return self.plugin_name

    def get_cached_login_accounts(self) -> list[dict[str, Any]]:
        if not callable(self.login_account_cache_getter):
            return []
        cached_accounts = self.login_account_cache_getter()
        return list(cached_accounts) if isinstance(cached_accounts, list) else []

    async def refresh_cached_login_accounts(self, users: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if callable(self.login_account_cache_refresher):
            refreshed_accounts = await self.login_account_cache_refresher(users)
            return list(refreshed_accounts) if isinstance(refreshed_accounts, list) else []
        return self.serialize_login_accounts(users)

    def serialize_login_accounts(self, users: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        normalized_users = users if isinstance(users, list) else []
        if callable(self.login_account_serializer):
            serialized_accounts = self.login_account_serializer(normalized_users)
            return list(serialized_accounts) if isinstance(serialized_accounts, list) else []
        return list(normalized_users)

    @property
    def pluginModule(self) -> str:
        return self.plugin_module


@dataclass(slots=True)
class PluginResult:
    handled: bool = False
    stop_processing: bool = False
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def skipped(cls, detail: str = "") -> "PluginResult":
        return cls(handled=False, detail=detail)

    @classmethod
    def handled_result(
        cls,
        detail: str = "",
        *,
        stop_processing: bool = False,
        data: dict[str, Any] | None = None,
    ) -> "PluginResult":
        return cls(
            handled=True,
            stop_processing=stop_processing,
            detail=detail,
            data=data or {},
        )

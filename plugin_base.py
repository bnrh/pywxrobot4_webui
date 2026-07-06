import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from client import WxRobotApiClient
from config import SETTINGS_DB_PATH, PluginServiceSettings
from db_connection import get_sqlite_connection


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
    ):
        self.plugin_id = str(plugin_id)
        self.namespace_name = _normalize_namespace(namespace)
        self.storage_path = Path(storage_path)
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
            connection = get_sqlite_connection(resolved_path)
            connection.executescript(PLUGIN_STATE_SCHEMA_SQL)
            connection.commit()
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
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM plugin_state WHERE plugin_id = ? AND namespace = ? AND key = ?",
                (self.plugin_id, self.namespace_name, str(key)),
            ).fetchone()
        if row is None:
            return default
        return self._deserialize(str(row["value_json"]), default)

    def set(self, key: str, value: Any) -> Any:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO plugin_state(plugin_id, namespace, key, value_json, updated_at)
                VALUES(?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (self.plugin_id, self.namespace_name, str(key), self._serialize(value)),
            )
            connection.commit()
        return value

    def delete(self, key: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM plugin_state WHERE plugin_id = ? AND namespace = ? AND key = ?",
                (self.plugin_id, self.namespace_name, str(key)),
            )
            connection.commit()
            return cursor.rowcount > 0

    def has(self, key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM plugin_state WHERE plugin_id = ? AND namespace = ? AND key = ? LIMIT 1",
                (self.plugin_id, self.namespace_name, str(key)),
            ).fetchone()
        return row is not None

    def keys(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key FROM plugin_state WHERE plugin_id = ? AND namespace = ? ORDER BY key",
                (self.plugin_id, self.namespace_name),
            ).fetchall()
        return [str(row["key"]) for row in rows]

    def values(self) -> list[Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT value_json FROM plugin_state WHERE plugin_id = ? AND namespace = ? ORDER BY key",
                (self.plugin_id, self.namespace_name),
            ).fetchall()
        return [self._deserialize(str(row["value_json"])) for row in rows]

    def entries(self) -> list[tuple[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, value_json FROM plugin_state WHERE plugin_id = ? AND namespace = ? ORDER BY key",
                (self.plugin_id, self.namespace_name),
            ).fetchall()
        return [(str(row["key"]), self._deserialize(str(row["value_json"]))) for row in rows]

    def get_all(self) -> dict[str, Any]:
        return dict(self.entries())

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM plugin_state WHERE plugin_id = ? AND namespace = ?",
                (self.plugin_id, self.namespace_name),
            )
            connection.commit()
            return int(cursor.rowcount or 0)

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
        return PluginStateStore(self.plugin_id, namespace=namespace, storage_path=self.storage_path)


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

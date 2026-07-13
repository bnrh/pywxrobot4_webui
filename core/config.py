import configparser
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.db_connection import get_sqlite_connection


def resolve_project_root() -> Path:
    """源码运行取仓库根；Nuitka/冻结运行取可执行文件所在目录。"""
    executable = Path(sys.executable).resolve()
    if executable.name.lower() not in {"python.exe", "pythonw.exe", "python", "python3"}:
        # onefile 模式下资源在临时目录，可写数据仍放回原始 exe 旁
        onefile_dir = os.environ.get("NUITKA_ONEFILE_DIRECTORY") or os.environ.get("NUITKA_ONEFILE_PARENT")
        if onefile_dir:
            return Path(onefile_dir).resolve()
        return executable.parent
    return Path(__file__).resolve().parents[1]


PROJECT_ROOT = resolve_project_root()
CONFIG_PATH = PROJECT_ROOT / "config.ini"
SETTINGS_DB_PATH = PROJECT_ROOT / "webui.sqlite3"
WEBUI_SECTION = "webui"
PLUGIN_PACKAGE = "plugins"
PLUGIN_PACKAGE_ALIASES = tuple(dict.fromkeys((PLUGIN_PACKAGE, "plugins", "webui.plugins")))
DEFAULT_PLUGIN_MODULES = [
    f"{PLUGIN_PACKAGE}.auto_download_image",
    f"{PLUGIN_PACKAGE}.global_blacklist_guard",
]
SYSTEM_SETTING_FIELDS = (
    "host",
    "port",
    "callback_path",
    "wxrobot_api_base_url",
    "request_timeout",
    "worker_count",
    "queue_size",
    "queue_enqueue_wait_seconds",
    "heartbeat_interval_seconds",
    "image_download_flag",
    "image_download_wait",
    "image_download_timeout",
    "api_token",
    "callback_secret",
)


def _parse_plugins(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if item and item.strip()]
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _parse_plugin_settings(value: str | None) -> dict[str, dict[str, Any]]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("插件配置数据不是合法 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("插件配置数据必须是 JSON 对象")
    return parsed


def normalize_plugin_module_name(value: Any) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    for package_name in PLUGIN_PACKAGE_ALIASES:
        prefix = f"{package_name}."
        if normalized.startswith(prefix):
            return f"{PLUGIN_PACKAGE}.{normalized[len(prefix):]}"
    return normalized


def normalize_plugin_module_names(values: list[str] | None) -> list[str]:
    normalized_items: list[str] = []
    for value in values or []:
        normalized = normalize_plugin_module_name(value)
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
    return normalized_items


def normalize_plugin_settings_map(value: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    normalized_settings: dict[str, dict[str, Any]] = {}
    for raw_key, raw_config in (value or {}).items():
        normalized_key = normalize_plugin_module_name(raw_key) or str(raw_key or "").strip()
        if not normalized_key:
            continue
        normalized_settings[normalized_key] = dict(raw_config) if isinstance(raw_config, dict) else {}
    return normalized_settings


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value in (None, ""):
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _read_legacy_webui_config(config_path: str | Path | None = None) -> dict[str, Any]:
    resolved_path = Path(config_path) if config_path else CONFIG_PATH
    parser = configparser.ConfigParser()
    parser.read(resolved_path, encoding="utf-8")
    base_config = dict(parser.items("base")) if parser.has_section("base") else {}
    webui_config = dict(parser.items(WEBUI_SECTION)) if parser.has_section(WEBUI_SECTION) else {}

    api_port = int(base_config.get("api_port", 23235))
    plugins = normalize_plugin_module_names(
        _parse_plugins(webui_config.get("plugins", ",".join(DEFAULT_PLUGIN_MODULES)))
    ) or DEFAULT_PLUGIN_MODULES.copy()
    plugin_settings = normalize_plugin_settings_map(
        _parse_plugin_settings(webui_config.get("plugin_settings_json", "{}"))
    )
    return {
        "host": webui_config.get("host", "127.0.0.1"),
        "port": int(webui_config.get("port", 28080)),
        "callback_path": webui_config.get("callback_path", "/messages"),
        "wxrobot_api_base_url": webui_config.get("api_base_url", f"http://127.0.0.1:{api_port}"),
        "plugins": plugins,
        "plugin_settings": plugin_settings,
        "request_timeout": float(webui_config.get("request_timeout", 10)),
        "worker_count": int(webui_config.get("worker_count", 2)),
        "queue_size": int(webui_config.get("queue_size", 1000)),
        "queue_enqueue_wait_seconds": float(webui_config.get("queue_enqueue_wait_seconds", 0.5)),
        "heartbeat_interval_seconds": int(webui_config.get("heartbeat_interval_seconds", 30)),
        "image_download_flag": int(webui_config.get("image_download_flag", 3)),
        "image_download_wait": _parse_bool(webui_config.get("image_download_wait", True), True),
        "image_download_timeout": int(webui_config.get("image_download_timeout", 15)),
        "api_token": str(webui_config.get("api_token", "") or "").strip(),
        "callback_secret": str(webui_config.get("callback_secret", "") or "").strip(),
    }


class WebuiSettingsStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else SETTINGS_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return get_sqlite_connection(self.db_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plugin_configs (
                    plugin_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

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
            )
            has_settings = connection.execute("SELECT 1 FROM system_settings LIMIT 1").fetchone() is not None
            has_plugins = connection.execute("SELECT 1 FROM plugin_configs LIMIT 1").fetchone() is not None

        if not has_settings and not has_plugins:
            self._migrate_from_legacy_config()

        self._migrate_legacy_plugin_ids()

    def _migrate_legacy_plugin_ids(self) -> None:
        with self._connect() as connection:
            self._migrate_plugin_config_ids(connection)
            self._migrate_plugin_state_ids(connection)

    @staticmethod
    def _migrate_plugin_config_ids(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT plugin_id, enabled, config_json, updated_at FROM plugin_configs ORDER BY plugin_id"
        ).fetchall()
        for row in rows:
            legacy_plugin_id = str(row["plugin_id"] or "").strip()
            normalized_plugin_id = normalize_plugin_module_name(legacy_plugin_id)
            if not normalized_plugin_id or normalized_plugin_id == legacy_plugin_id:
                continue

            current_row = connection.execute(
                "SELECT enabled, config_json, updated_at FROM plugin_configs WHERE plugin_id = ?",
                (normalized_plugin_id,),
            ).fetchone()

            merged_config = {
                **_parse_json_object(row["config_json"]),
                **(_parse_json_object(current_row["config_json"]) if current_row is not None else {}),
            }
            merged_enabled = int(bool(row["enabled"]) or bool(current_row["enabled"]) if current_row is not None else bool(row["enabled"]))
            updated_at_candidates = [str(row["updated_at"] or "").strip()]
            if current_row is not None:
                updated_at_candidates.append(str(current_row["updated_at"] or "").strip())
            merged_updated_at = max((item for item in updated_at_candidates if item), default="")

            connection.execute(
                """
                INSERT OR REPLACE INTO plugin_configs(plugin_id, enabled, config_json, updated_at)
                VALUES(?, ?, ?, ?)
                """,
                (
                    normalized_plugin_id,
                    merged_enabled,
                    json.dumps(merged_config, ensure_ascii=False),
                    merged_updated_at or str(row["updated_at"] or "").strip() or "1970-01-01 00:00:00",
                ),
            )
            connection.execute("DELETE FROM plugin_configs WHERE plugin_id = ?", (legacy_plugin_id,))

    @staticmethod
    def _migrate_plugin_state_ids(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT plugin_id, namespace, key, value_json, updated_at FROM plugin_state ORDER BY plugin_id, namespace, key"
        ).fetchall()
        for row in rows:
            legacy_plugin_id = str(row["plugin_id"] or "").strip()
            normalized_plugin_id = normalize_plugin_module_name(legacy_plugin_id)
            if not normalized_plugin_id or normalized_plugin_id == legacy_plugin_id:
                continue

            namespace = str(row["namespace"] or "default")
            state_key = str(row["key"] or "")
            legacy_updated_at = str(row["updated_at"] or "").strip()
            current_row = connection.execute(
                """
                SELECT value_json, updated_at FROM plugin_state
                WHERE plugin_id = ? AND namespace = ? AND key = ?
                """,
                (normalized_plugin_id, namespace, state_key),
            ).fetchone()

            should_replace_current = current_row is None
            if current_row is not None:
                current_updated_at = str(current_row["updated_at"] or "").strip()
                should_replace_current = not current_updated_at or (bool(legacy_updated_at) and legacy_updated_at > current_updated_at)

            if should_replace_current:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO plugin_state(plugin_id, namespace, key, value_json, updated_at)
                    VALUES(?, ?, ?, ?, ?)
                    """,
                    (
                        normalized_plugin_id,
                        namespace,
                        state_key,
                        str(row["value_json"] or "null"),
                        legacy_updated_at or "1970-01-01 00:00:00",
                    ),
                )

            connection.execute(
                "DELETE FROM plugin_state WHERE plugin_id = ? AND namespace = ? AND key = ?",
                (legacy_plugin_id, namespace, state_key),
            )

    def _migrate_from_legacy_config(self) -> None:
        legacy = _read_legacy_webui_config()
        with self._connect() as connection:
            for field in SYSTEM_SETTING_FIELDS:
                connection.execute(
                    "INSERT OR REPLACE INTO system_settings(key, value) VALUES(?, ?)",
                    (field, json.dumps(legacy[field], ensure_ascii=False)),
                )

            plugin_ids = set(DEFAULT_PLUGIN_MODULES) | set(legacy["plugins"]) | set(legacy["plugin_settings"])
            for plugin_id in plugin_ids:
                config_json = json.dumps(legacy["plugin_settings"].get(plugin_id, {}), ensure_ascii=False)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO plugin_configs(plugin_id, enabled, config_json, updated_at)
                    VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (plugin_id, 1 if plugin_id in legacy["plugins"] else 0, config_json),
                )

    def load_payload(self) -> dict[str, Any]:
        defaults = _read_legacy_webui_config()
        with self._connect() as connection:
            settings_rows = connection.execute("SELECT key, value FROM system_settings").fetchall()
            plugin_rows = connection.execute(
                "SELECT plugin_id, enabled, config_json FROM plugin_configs ORDER BY plugin_id"
            ).fetchall()

        settings_map = {
            row["key"]: json.loads(row["value"])
            for row in settings_rows
        }
        plugin_settings: dict[str, dict[str, Any]] = {}
        enabled_plugins: list[str] = []
        stored_plugin_ids: set[str] = set()
        for row in plugin_rows:
            plugin_id = str(row["plugin_id"] or "").strip()
            normalized_plugin_id = normalize_plugin_module_name(plugin_id) or plugin_id
            if normalized_plugin_id:
                stored_plugin_ids.add(normalized_plugin_id)
            config = _parse_json_object(row["config_json"])
            if normalized_plugin_id not in plugin_settings or plugin_id == normalized_plugin_id:
                plugin_settings[normalized_plugin_id] = config
            if int(row["enabled"]) and normalized_plugin_id not in enabled_plugins:
                enabled_plugins.append(normalized_plugin_id)

        for default_plugin_id in normalize_plugin_module_names(DEFAULT_PLUGIN_MODULES):
            if default_plugin_id in stored_plugin_ids or default_plugin_id in enabled_plugins:
                continue
            enabled_plugins.append(default_plugin_id)

        return {
            **defaults,
            **settings_map,
            "plugins": normalize_plugin_module_names(enabled_plugins) or defaults["plugins"],
            "plugin_settings": {**defaults["plugin_settings"], **normalize_plugin_settings_map(plugin_settings)},
        }

    def save_settings(self, settings: "PluginServiceSettings") -> None:
        payload = settings.model_dump(mode="python")
        with self._connect() as connection:
            for field in SYSTEM_SETTING_FIELDS:
                connection.execute(
                    "INSERT OR REPLACE INTO system_settings(key, value) VALUES(?, ?)",
                    (field, json.dumps(payload[field], ensure_ascii=False)),
                )

            existing_rows = connection.execute(
                "SELECT plugin_id, config_json FROM plugin_configs"
            ).fetchall()
            existing_configs: dict[str, dict[str, Any]] = {}
            for row in existing_rows:
                plugin_id = str(row["plugin_id"] or "").strip()
                normalized_plugin_id = normalize_plugin_module_name(plugin_id) or plugin_id
                if normalized_plugin_id not in existing_configs or plugin_id == normalized_plugin_id:
                    existing_configs[normalized_plugin_id] = _parse_json_object(row["config_json"])

            normalized_plugins = normalize_plugin_module_names(settings.plugins)
            normalized_plugin_settings = normalize_plugin_settings_map(settings.plugin_settings)
            all_plugin_ids = set(existing_configs) | set(normalized_plugins) | set(normalized_plugin_settings) | set(normalize_plugin_module_names(DEFAULT_PLUGIN_MODULES))
            if not all_plugin_ids:
                all_plugin_ids = set(DEFAULT_PLUGIN_MODULES)

            for plugin_id in all_plugin_ids:
                config = normalized_plugin_settings.get(plugin_id, existing_configs.get(plugin_id, {}))
                connection.execute(
                    """
                    INSERT OR REPLACE INTO plugin_configs(plugin_id, enabled, config_json, updated_at)
                    VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (plugin_id, 1 if plugin_id in normalized_plugins else 0, json.dumps(config, ensure_ascii=False)),
                )

    def get_json_setting(self, key: str, default: Any = None) -> Any:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return default
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM system_settings WHERE key = ?",
                (normalized_key,),
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (TypeError, ValueError, json.JSONDecodeError):
            return default

    def set_json_setting(self, key: str, value: Any) -> None:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            raise ValueError("配置键不能为空")
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO system_settings(key, value) VALUES(?, ?)",
                (normalized_key, json.dumps(value, ensure_ascii=False)),
            )

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        plugin_id = normalize_plugin_module_name(plugin_id) or str(plugin_id or "").strip()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT config_json FROM plugin_configs WHERE plugin_id = ?",
                (plugin_id,),
            ).fetchone()
            config_json = existing["config_json"] if existing is not None else "{}"
            connection.execute(
                """
                INSERT OR REPLACE INTO plugin_configs(plugin_id, enabled, config_json, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (plugin_id, 1 if enabled else 0, config_json),
            )

    def set_plugin_config(self, plugin_id: str, config: dict[str, Any]) -> None:
        plugin_id = normalize_plugin_module_name(plugin_id) or str(plugin_id or "").strip()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT enabled FROM plugin_configs WHERE plugin_id = ?",
                (plugin_id,),
            ).fetchone()
            enabled = int(existing["enabled"]) if existing is not None else 0
            connection.execute(
                """
                INSERT OR REPLACE INTO plugin_configs(plugin_id, enabled, config_json, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (plugin_id, enabled, json.dumps(config, ensure_ascii=False)),
            )


class PluginServiceSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = Field("127.0.0.1", description="插件服务监听地址")
    port: int = Field(28080, ge=1, le=65535, description="插件服务监听端口")
    callback_path: str = Field("/messages", description="微信消息推送路径")
    wxrobot_api_base_url: str = Field(
        "http://127.0.0.1:23235",
        description="当前 wxrobot_api 服务地址",
    )
    plugins: list[str] = Field(
        default_factory=lambda: DEFAULT_PLUGIN_MODULES.copy(),
        description="要加载的插件模块列表",
    )
    plugin_settings: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="插件配置，按模块名或插件名索引",
    )
    request_timeout: float = Field(10.0, gt=0, le=120, description="调用 wxrobot_api 接口的超时")
    worker_count: int = Field(2, ge=1, le=32, description="后台消息处理协程数")
    queue_size: int = Field(1000, ge=1, le=100000, description="消息队列长度")
    queue_enqueue_wait_seconds: float = Field(0.5, ge=0, le=30, description="队列满时等待入队的秒数，0 表示不等待")
    heartbeat_interval_seconds: int = Field(30, ge=0, le=3600, description="心跳检测间隔秒数，0 表示关闭")
    image_download_flag: int = Field(3, ge=1, le=3, description="图片下载类型，1 缩略图，2 压缩图，3 原图")
    image_download_wait: bool = Field(True, description="是否等待图片下载完成")
    image_download_timeout: int = Field(15, ge=1, le=120, description="图片下载等待超时")
    api_token: str = Field("", description="Web API 访问令牌，留空表示不启用鉴权")
    callback_secret: str = Field("", description="微信消息回调共享密钥，留空表示不校验")

    @field_validator("callback_path")
    @classmethod
    def normalize_callback_path(cls, value: str) -> str:
        if not value:
            return "/messages"
        if not value.startswith("/"):
            value = f"/{value}"
        return value.rstrip("/") or "/messages"

    @field_validator("wxrobot_api_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("api_token", "callback_secret", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("plugins", mode="before")
    @classmethod
    def normalize_plugins(cls, value: Any) -> list[str]:
        return normalize_plugin_module_names(_parse_plugins(value)) or DEFAULT_PLUGIN_MODULES.copy()

    @field_validator("plugin_settings", mode="before")
    @classmethod
    def normalize_plugin_settings(cls, value: Any) -> dict[str, dict[str, Any]]:
        return normalize_plugin_settings_map(value if isinstance(value, dict) else {})

    @property
    def callback_url(self) -> str:
        host = self.host
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        return f"http://{host}:{self.port}{self.callback_path}"

    @classmethod
    def from_storage(cls, db_path: str | Path | None = None) -> "PluginServiceSettings":
        payload = WebuiSettingsStore(db_path).load_payload()
        return cls(**payload)

    @classmethod
    def from_config(cls, config_path: str | Path | None = None) -> "PluginServiceSettings":
        return cls.from_storage(config_path if config_path and str(config_path).endswith(".sqlite3") else None)

    def save_to_storage(self, db_path: str | Path | None = None) -> None:
        WebuiSettingsStore(db_path).save_settings(self)

    def save_to_config(self, config_path: str | Path | None = None) -> None:
        self.save_to_storage(config_path if config_path and str(config_path).endswith(".sqlite3") else None)
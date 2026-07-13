"""Web UI 应用级常量与启动配置清理。"""

from __future__ import annotations

from pathlib import Path

from config import PROJECT_ROOT, SETTINGS_DB_PATH, normalize_plugin_module_name
from config import PluginServiceSettings

FRONTEND_DIR = Path(__file__).with_name("frontend")
FRONTEND_INDEX_PAGE = FRONTEND_DIR / "index.html"
STATIC_DIR = Path(__file__).with_name("static")
LOG_DIR = SETTINGS_DB_PATH.parent / "logs"
PLUGIN_ASSET_UPLOAD_ROOT = PROJECT_ROOT / "uploads"
PLUGIN_ASSET_MAX_BYTES = 10 * 1024 * 1024
PLUGIN_ASSET_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

RESTART_REQUIRED_FIELDS = {"host", "port", "callback_path", "worker_count", "queue_size"}
RUNTIME_LIGHT_REFRESH_FIELDS = {
    "api_token",
    "callback_secret",
    "request_timeout",
    "wxrobot_api_base_url",
    "heartbeat_interval_seconds",
    "queue_enqueue_wait_seconds",
    "image_download_flag",
    "image_download_wait",
    "image_download_timeout",
}
PLUGIN_MANAGER_RELOAD_FIELDS = {"plugins", "plugin_settings"}
SYSTEM_SETTINGS_FIELDS = (
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
SECRET_SETTINGS_PLACEHOLDER = "******"
REMOVED_PLUGIN_MODULES = {normalize_plugin_module_name("webui.plugins.monitor_biz")}
INVITE_TO_ROOM_PLUGIN_MODULE = normalize_plugin_module_name("plugins.invite_to_room")
INVITE_TO_TOOM_LEGACY_MODULE = normalize_plugin_module_name("plugins.invite_to_toom")
# 遗留拼写 → 正确模块名；遗留模块仅作兼容 shim，不在插件列表中展示。
LEGACY_PLUGIN_MODULE_ALIASES = {
    INVITE_TO_TOOM_LEGACY_MODULE: INVITE_TO_ROOM_PLUGIN_MODULE,
}
LEGACY_PLUGIN_ALIAS_MODULES = frozenset(LEGACY_PLUGIN_MODULE_ALIASES)
DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE = normalize_plugin_module_name("plugins.download_recent_user_images")
DONT_REVOKE_PLUGIN_MODULE = normalize_plugin_module_name("plugins.dont_revoke")
DIRECT_EXECUTE_PLUGIN_MODULES = {
    normalize_plugin_module_name("plugins.room_msg_summary"),
    normalize_plugin_module_name("plugins.user_msg_summary"),
    normalize_plugin_module_name("plugins.export_contacts"),
    DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE,
    DONT_REVOKE_PLUGIN_MODULE,
}
MESSAGE_SUMMARY_PLUGIN_MODULES = {
    normalize_plugin_module_name("plugins.room_msg_summary"),
    normalize_plugin_module_name("plugins.user_msg_summary"),
}


def resolve_canonical_plugin_module(module_name: str) -> str:
    normalized = normalize_plugin_module_name(module_name)
    return LEGACY_PLUGIN_MODULE_ALIASES.get(normalized, normalized)


def _migrate_plugin_state_ids() -> None:
    if not LEGACY_PLUGIN_MODULE_ALIASES:
        return
    from db_connection import get_sqlite_connection

    connection = get_sqlite_connection(SETTINGS_DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS plugin_state (
            plugin_id TEXT NOT NULL,
            namespace TEXT NOT NULL DEFAULT 'default',
            key TEXT NOT NULL,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(plugin_id, namespace, key)
        )
        """
    )
    for legacy_module, canonical_module in LEGACY_PLUGIN_MODULE_ALIASES.items():
        if legacy_module == canonical_module:
            continue
        rows = connection.execute(
            "SELECT namespace, key, value_json, updated_at FROM plugin_state WHERE plugin_id = ?",
            (legacy_module,),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO plugin_state(plugin_id, namespace, key, value_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (canonical_module, row["namespace"], row["key"], row["value_json"], row["updated_at"]),
            )
        connection.execute("DELETE FROM plugin_state WHERE plugin_id = ?", (legacy_module,))
    connection.commit()


def sanitize_stored_settings(settings: PluginServiceSettings) -> PluginServiceSettings:
    sanitized_plugins: list[str] = []
    seen_plugins: set[str] = set()
    for module_name in settings.plugins:
        if module_name in REMOVED_PLUGIN_MODULES:
            continue
        canonical = resolve_canonical_plugin_module(module_name)
        if canonical in REMOVED_PLUGIN_MODULES or canonical in seen_plugins:
            continue
        seen_plugins.add(canonical)
        sanitized_plugins.append(canonical)

    sanitized_plugin_settings: dict[str, dict] = {}
    for key, value in settings.plugin_settings.items():
        if key in REMOVED_PLUGIN_MODULES:
            continue
        canonical = resolve_canonical_plugin_module(key)
        if canonical in REMOVED_PLUGIN_MODULES:
            continue
        # 正确拼写优先；仅当目标键尚未写入时才采用遗留配置。
        if canonical in sanitized_plugin_settings and key != canonical:
            continue
        sanitized_plugin_settings[canonical] = value

    changed = (
        sanitized_plugins != list(settings.plugins)
        or sanitized_plugin_settings != settings.plugin_settings
    )
    _migrate_plugin_state_ids()
    if not changed:
        return settings

    next_settings = settings.model_copy(
        update={
            "plugins": sanitized_plugins,
            "plugin_settings": sanitized_plugin_settings,
        }
    )
    next_settings.save_to_storage()
    return next_settings

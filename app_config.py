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


def sanitize_stored_settings(settings: PluginServiceSettings) -> PluginServiceSettings:
    sanitized_plugins = [module_name for module_name in settings.plugins if module_name not in REMOVED_PLUGIN_MODULES]
    sanitized_plugin_settings = {
        key: value
        for key, value in settings.plugin_settings.items()
        if key not in REMOVED_PLUGIN_MODULES
    }
    if sanitized_plugins == settings.plugins and sanitized_plugin_settings == settings.plugin_settings:
        return settings
    next_settings = settings.model_copy(
        update={
            "plugins": sanitized_plugins,
            "plugin_settings": sanitized_plugin_settings,
        }
    )
    next_settings.save_to_storage()
    return next_settings

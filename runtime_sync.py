"""配置变更后的运行时热重载。"""

from __future__ import annotations

from app_builders import AppBuilders
from app_config import PLUGIN_MANAGER_RELOAD_FIELDS, RUNTIME_LIGHT_REFRESH_FIELDS
from config import PluginServiceSettings
from runtime import PluginRuntime


async def sync_runtime_with_config(runtime: PluginRuntime, configured_settings: PluginServiceSettings) -> dict:
    builders = AppBuilders(runtime)
    _effective_settings, changed_fields, hot_reload_fields, restart_required_fields = builders.plan_runtime_reload(
        configured_settings
    )
    manager_reload_needed = any(field in PLUGIN_MANAGER_RELOAD_FIELDS for field in hot_reload_fields)
    light_fields = [field for field in hot_reload_fields if field in RUNTIME_LIGHT_REFRESH_FIELDS]
    if manager_reload_needed:
        await runtime.reload(configured_settings)
    elif light_fields:
        await runtime.apply_light_settings(configured_settings, light_fields)
    return {
        "changed_fields": changed_fields,
        "applied_fields": hot_reload_fields,
        "restart_required_fields": restart_required_fields,
        "restart_required": bool(restart_required_fields),
    }

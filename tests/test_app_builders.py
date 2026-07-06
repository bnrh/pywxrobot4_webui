from app_builders import AppBuilders
from app_config import REMOVED_PLUGIN_MODULES, sanitize_stored_settings
from config import PluginServiceSettings
from runtime import PluginRuntime


def test_sanitize_stored_settings_removes_legacy_plugin() -> None:
    removed = next(iter(REMOVED_PLUGIN_MODULES))
    settings = PluginServiceSettings(plugins=[removed, "plugins.auto_download_image"])
    sanitized = sanitize_stored_settings(settings)
    assert removed not in sanitized.plugins


def test_build_plugin_payload_includes_enabled_flag() -> None:
    runtime = PluginRuntime(PluginServiceSettings())
    builders = AppBuilders(runtime)
    payload = builders.build_plugin_payload()
    assert isinstance(payload, list)
    if payload:
        assert "enabled" in payload[0]
        assert "loaded" in payload[0]

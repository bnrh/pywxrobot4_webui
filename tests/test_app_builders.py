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


def test_sort_option_items_orders_by_label() -> None:
    items = [
        {"label": "Beta", "value": "b"},
        {"label": "alpha", "value": "a"},
    ]
    sorted_items = AppBuilders.sort_option_items(items)
    assert [item["value"] for item in sorted_items] == ["a", "b"]


def test_build_room_member_options_deduplicates_and_sorts() -> None:
    members = AppBuilders.build_room_member_options(
        [
            {"username": "wxid_b", "nick_name": "Beta"},
            {"wxid": "wxid_b", "nick_name": "Duplicate"},
            {"username": "wxid_a", "room_nick_name": "Alpha"},
        ]
    )
    assert [item["wxid"] for item in members] == ["wxid_a", "wxid_b"]
    assert members[0]["label"] == "Alpha"
    assert members[1]["label"] == "Beta"

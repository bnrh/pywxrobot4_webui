from app_builders import AppBuilders
from app_config import REMOVED_PLUGIN_MODULES, SECRET_SETTINGS_PLACEHOLDER, sanitize_stored_settings
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
        assert "direct_execute" in payload[0]
        assert "message_summary" in payload[0]


def test_message_summary_flag_only_for_summary_plugins() -> None:
    runtime = PluginRuntime(PluginServiceSettings())
    builders = AppBuilders(runtime)
    payload = {item["module"]: item for item in builders.build_plugin_payload()}
    room_summary = payload.get("plugins.room_msg_summary")
    if room_summary is not None:
        assert room_summary["message_summary"] is True
        assert room_summary["direct_execute"] is True


def test_sort_option_items_orders_by_label() -> None:
    items = [
        {"label": "Beta", "value": "b"},
        {"label": "alpha", "value": "a"},
    ]
    sorted_items = AppBuilders.sort_option_items(items)
    assert [item["value"] for item in sorted_items] == ["a", "b"]


def test_build_overview_includes_runtime_metrics() -> None:
    runtime = PluginRuntime(PluginServiceSettings())
    builders = AppBuilders(runtime)
    overview = builders.build_overview()
    metrics = overview.get("runtime_metrics") or {}
    assert metrics.get("workers_configured") == runtime.settings.worker_count
    assert "queue_rejections" in metrics
    assert "recent_messages" in metrics
    assert "recent_plugin_logs" in metrics
    assert metrics.get("queue_capacity") == runtime.settings.queue_size


def test_merge_secret_settings_updates_preserves_existing_secrets() -> None:
    configured = PluginServiceSettings(api_token="stored-token", callback_secret="stored-secret")
    merged = AppBuilders.merge_secret_settings_updates(
        configured,
        {
            "api_token": "",
            "callback_secret": SECRET_SETTINGS_PLACEHOLDER,
        },
    )
    assert merged["api_token"] == "stored-token"
    assert merged["callback_secret"] == "stored-secret"


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

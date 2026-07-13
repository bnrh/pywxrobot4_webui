import asyncio

from app_builders import AppBuilders
from app_config import (
    INVITE_TO_ROOM_PLUGIN_MODULE,
    INVITE_TO_TOOM_LEGACY_MODULE,
    REMOVED_PLUGIN_MODULES,
    SECRET_SETTINGS_PLACEHOLDER,
    sanitize_stored_settings,
)
from config import PluginServiceSettings
from contact_directory_cache import PLUGIN_TARGETS_CACHE_TTL_SECONDS
from manager import PluginManager
from runtime import PluginRuntime


def test_sanitize_stored_settings_removes_legacy_plugin() -> None:
    removed = next(iter(REMOVED_PLUGIN_MODULES))
    settings = PluginServiceSettings(plugins=[removed, "plugins.auto_download_image"])
    sanitized = sanitize_stored_settings(settings)
    assert removed not in sanitized.plugins


def test_sanitize_stored_settings_migrates_invite_to_toom_alias() -> None:
    settings = PluginServiceSettings(
        plugins=[INVITE_TO_TOOM_LEGACY_MODULE, "plugins.auto_download_image"],
        plugin_settings={
            INVITE_TO_TOOM_LEGACY_MODULE: {"cooldown_seconds": 120},
        },
    )
    sanitized = sanitize_stored_settings(settings)
    assert INVITE_TO_TOOM_LEGACY_MODULE not in sanitized.plugins
    assert INVITE_TO_ROOM_PLUGIN_MODULE in sanitized.plugins
    assert INVITE_TO_TOOM_LEGACY_MODULE not in sanitized.plugin_settings
    assert sanitized.plugin_settings[INVITE_TO_ROOM_PLUGIN_MODULE]["cooldown_seconds"] == 120


def test_discover_plugin_modules_hides_invite_to_toom_alias() -> None:
    modules = PluginManager.discover_plugin_modules()
    assert INVITE_TO_ROOM_PLUGIN_MODULE in modules
    assert INVITE_TO_TOOM_LEGACY_MODULE not in modules


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


def test_build_plugin_target_payload_fetches_wxpids_in_parallel() -> None:
    runtime = PluginRuntime(PluginServiceSettings())
    builders = AppBuilders(runtime)

    active = 0
    max_active = 0

    async def get_logged_in_users():
        return [
            {"wxpid": 101, "wxid": "wxid_a", "nickname": "Alice"},
            {"wxpid": 202, "wxid": "wxid_b", "nickname": "Bob"},
        ]

    async def get_room_list(*, wxpid=None):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return [{"wxid": f"room_{wxpid}", "nickname": f"Room {wxpid}"}]

    async def get_labels(*, wxpid=None):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return {f"label_{wxpid}": True}

    runtime.api_client.get_logged_in_users = get_logged_in_users
    runtime.api_client.get_room_list = get_room_list
    runtime.api_client.get_labels = get_labels

    payload = asyncio.run(builders.build_plugin_target_payload())
    assert payload["default_wxpid"] == 101
    assert {item["value"] for item in payload["room_options"]} == {"room_101", "room_202"}
    assert {item["value"] for item in payload["label_options"]} == {"label_101", "label_202"}
    # 串行时同一时刻最多 2 个请求；并行后应同时覆盖多个 wxpid。
    assert max_active >= 3


def test_build_plugin_target_payload_uses_cache() -> None:
    runtime = PluginRuntime(PluginServiceSettings())
    builders = AppBuilders(runtime)
    calls = {"users": 0}

    async def get_logged_in_users():
        calls["users"] += 1
        return [{"wxpid": 1, "wxid": "wxid_a", "nickname": "Alice"}]

    async def get_room_list(*, wxpid=None):
        return []

    async def get_labels(*, wxpid=None):
        return {}

    runtime.api_client.get_logged_in_users = get_logged_in_users
    runtime.api_client.get_room_list = get_room_list
    runtime.api_client.get_labels = get_labels

    first = asyncio.run(builders.build_plugin_target_payload())
    second = asyncio.run(builders.build_plugin_target_payload())
    assert first == second
    assert calls["users"] == 1
    assert PLUGIN_TARGETS_CACHE_TTL_SECONDS >= 180

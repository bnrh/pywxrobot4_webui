from runtime import PLUGIN_LOG_LIMIT, RECENT_MESSAGE_LIMIT, PluginRuntime, now_iso


def test_runtime_limits() -> None:
    assert RECENT_MESSAGE_LIMIT == 200
    assert PLUGIN_LOG_LIMIT == 1000


def test_now_iso_format() -> None:
    value = now_iso()
    assert "T" in value


def test_plugin_runtime_initial_state() -> None:
    from config import PluginServiceSettings

    runtime = PluginRuntime(PluginServiceSettings())
    assert runtime.recent_messages.maxlen == RECENT_MESSAGE_LIMIT
    assert runtime.recent_plugin_logs.maxlen == PLUGIN_LOG_LIMIT
    assert runtime.started_at is None

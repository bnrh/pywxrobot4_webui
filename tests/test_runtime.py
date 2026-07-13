import tempfile
from pathlib import Path

import db_connection
from message_repository import MessageRepository
from plugin_log_repository import PluginLogRepository
from runtime import PLUGIN_LOG_LIMIT, RECENT_MESSAGE_LIMIT, PluginRuntime, now_iso


def _clear_connection_cache(db_path: Path) -> None:
    connection = db_connection.get_sqlite_connection(db_path)
    connection.close()
    cache_key = str(db_path.resolve())
    connections = getattr(db_connection._thread_state, "connections", None)
    if isinstance(connections, dict):
        connections.pop(cache_key, None)
    db_connection.reset_sqlite_write_state_for_tests()


def test_runtime_limits() -> None:
    assert RECENT_MESSAGE_LIMIT == 200
    assert PLUGIN_LOG_LIMIT == 1000


def test_now_iso_format() -> None:
    value = now_iso()
    assert "T" in value


def test_plugin_runtime_initial_state() -> None:
    from config import PluginServiceSettings

    runtime = PluginRuntime(PluginServiceSettings())
    assert runtime.recent_messages.maxlen is None or len(runtime.recent_messages) <= RECENT_MESSAGE_LIMIT
    assert len(runtime.message_repository) <= RECENT_MESSAGE_LIMIT
    assert len(runtime.plugin_log_repository) <= PLUGIN_LOG_LIMIT
    assert runtime.started_at is None
    assert runtime.recent_messages is runtime.message_repository.cached_messages
    assert runtime.recent_plugin_logs is runtime.plugin_log_repository.cached_logs


def test_build_runtime_event_metrics_shape() -> None:
    from config import PluginServiceSettings

    runtime = PluginRuntime(PluginServiceSettings())
    metrics = runtime.build_runtime_event_metrics()
    assert "queued_messages" in metrics
    assert "workers_active" in metrics
    assert "queue_rejections" in metrics
    assert "recent_messages" in metrics
    assert metrics["queue_capacity"] == runtime.settings.queue_size


def test_message_repository_upsert_patch_and_order() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "messages.sqlite3"
        repo = MessageRepository(limit=3, db_path=db_path)
        for index in range(1, 5):
            repo.upsert(
                {
                    "internal_id": index,
                    "received_at": f"2026-07-13T12:00:0{index}",
                    "processed_at": None,
                    "status": "queued",
                    "error": "",
                    "msgid": str(index),
                    "conversation_wxid": "wxid_a",
                    "sender_wxid": "wxid_b",
                    "msg_type": 1,
                    "local_type": 1,
                    "wxpid": 1,
                    "is_group_message": False,
                    "content": f"msg-{index}",
                    "plugin_results": [],
                    "payload": {"n": index},
                }
            )
        recent = repo.list_recent(10)
        assert [item["internal_id"] for item in recent] == [4, 3, 2]
        assert len(repo) == 3

        patched = repo.patch(4, status="processed", content="updated")
        assert patched is not None
        assert patched["status"] == "processed"
        assert repo.list_recent(1)[0]["content"] == "updated"

        # 重新加载应保持最新在前，且与 SQLite 一致。
        reloaded = MessageRepository(limit=3, db_path=db_path)
        assert [item["internal_id"] for item in reloaded.list_recent(10)] == [4, 3, 2]
        assert reloaded.list_recent(1)[0]["status"] == "processed"
        _clear_connection_cache(db_path)


def test_plugin_log_repository_append_and_reload() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "logs.sqlite3"
        repo = PluginLogRepository(limit=2, db_path=db_path)
        for index in range(1, 4):
            repo.append(
                {
                    "internal_id": index,
                    "recorded_at": f"2026-07-13T12:00:0{index}",
                    "module": "plugins.demo",
                    "plugin": "demo",
                    "level": "INFO",
                    "scope": "test",
                    "message": f"log-{index}",
                    "data": {"n": index},
                }
            )
        assert [item["internal_id"] for item in repo.cached_logs] == [3, 2]
        logs, total = repo.load_recent(10, module_name="plugins.demo")
        assert total == 2
        assert logs[0]["message"] == "log-3"
        reloaded = PluginLogRepository(limit=2, db_path=db_path)
        assert [item["internal_id"] for item in reloaded.cached_logs] == [3, 2]
        _clear_connection_cache(db_path)

import db_connection
import tempfile
from pathlib import Path

from db_connection import get_sqlite_connection
from plugin_log_store import PluginLogStore


def test_plugin_log_store_append_and_load() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "logs.sqlite3"
        store = PluginLogStore(db_path=db_path, limit=10)
        store.append_log(
            {
                "internal_id": 1,
                "recorded_at": "2026-07-06T12:00:00",
                "module": "plugins.demo",
                "plugin": "demo",
                "level": "INFO",
                "scope": "test",
                "message": "hello",
                "data": {"ok": True},
            }
        )
        logs, total = store.load_recent(5, module_name="plugins.demo")
        assert total == 1
        assert logs[0]["message"] == "hello"
        assert logs[0]["data"] == {"ok": True}
        connection = get_sqlite_connection(db_path)
        connection.close()
        cache_key = str(db_path.resolve())
        connections = getattr(db_connection._thread_state, "connections", None)
        if isinstance(connections, dict):
            connections.pop(cache_key, None)

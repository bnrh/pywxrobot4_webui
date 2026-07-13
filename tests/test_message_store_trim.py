import tempfile
from pathlib import Path

import db_connection
from message_store import RecentMessageStore
from plugin_log_store import PluginLogStore


def _clear_connection_cache(db_path: Path) -> None:
    connection = db_connection.get_sqlite_connection(db_path)
    connection.close()
    cache_key = str(db_path.resolve())
    connections = getattr(db_connection._thread_state, "connections", None)
    if isinstance(connections, dict):
        connections.pop(cache_key, None)
    db_connection.reset_sqlite_write_state_for_tests()


def _message_payload(internal_id: int) -> dict:
    return {
        "internal_id": internal_id,
        "received_at": f"2026-07-13T12:00:{internal_id:02d}",
        "processed_at": None,
        "status": "queued",
        "error": "",
        "msgid": str(internal_id),
        "conversation_wxid": "wxid_a",
        "sender_wxid": "wxid_b",
        "msg_type": 1,
        "local_type": 1,
        "wxpid": 1,
        "is_group_message": False,
        "content": f"msg-{internal_id}",
        "plugin_results": [],
        "payload": {"n": internal_id},
    }


def test_message_store_defers_trim_until_batch_or_overflow() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "messages.sqlite3"
        store = RecentMessageStore(db_path=db_path, limit=5, trim_overflow=3, trim_every_writes=100)

        for index in range(1, 8):  # 7 rows: still within soft_limit=8, and writes < 100
            store.upsert_message(_message_payload(index))

        assert store._count_rows() == 7
        assert len(store.load_recent(20)) == 7

        # 再写入触发 soft overflow（> 5+3）
        store.upsert_message(_message_payload(8))
        store.upsert_message(_message_payload(9))
        assert store._count_rows() == 5
        assert [item["internal_id"] for item in store.load_recent(20)] == [9, 8, 7, 6, 5]
        _clear_connection_cache(db_path)


def test_message_store_trim_every_writes() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "messages.sqlite3"
        store = RecentMessageStore(db_path=db_path, limit=3, trim_overflow=100, trim_every_writes=4)

        for index in range(1, 5):
            store.upsert_message(_message_payload(index))

        # 第 4 次写入时 writes_since_trim 达标且 count>limit，应裁剪
        assert store._count_rows() == 3
        assert [item["internal_id"] for item in store.load_recent(20)] == [4, 3, 2]
        _clear_connection_cache(db_path)


def test_message_store_trim_now() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "messages.sqlite3"
        store = RecentMessageStore(db_path=db_path, limit=2, trim_overflow=50, trim_every_writes=1000)
        for index in range(1, 6):
            store.upsert_message(_message_payload(index))
        assert store._count_rows() == 5
        store.trim_now()
        assert store._count_rows() == 2
        assert [item["internal_id"] for item in store.load_recent(20)] == [5, 4]
        _clear_connection_cache(db_path)


def test_plugin_log_store_defers_trim() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "logs.sqlite3"
        store = PluginLogStore(db_path=db_path, limit=3, trim_overflow=2, trim_every_writes=100)
        for index in range(1, 6):
            store.append_log(
                {
                    "internal_id": index,
                    "recorded_at": f"2026-07-13T12:00:0{index}",
                    "module": "plugins.demo",
                    "plugin": "demo",
                    "level": "INFO",
                    "scope": "test",
                    "message": f"log-{index}",
                    "data": None,
                }
            )
        # soft_limit=5，第 5 条后 count==5 未超额；第 6 条触发
        assert store._count_rows() == 5
        store.append_log(
            {
                "internal_id": 6,
                "recorded_at": "2026-07-13T12:00:06",
                "module": "plugins.demo",
                "plugin": "demo",
                "level": "INFO",
                "scope": "test",
                "message": "log-6",
                "data": None,
            }
        )
        assert store._count_rows() == 3
        logs, _ = store.load_recent(10)
        assert [item["internal_id"] for item in logs] == [6, 5, 4]
        _clear_connection_cache(db_path)

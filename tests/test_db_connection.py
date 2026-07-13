import sqlite3
from pathlib import Path

from db_connection import (
    FLUSH_NOW,
    get_pending_write_count,
    get_sqlite_connection,
    reset_sqlite_write_state_for_tests,
    sqlite_execute_read,
    sqlite_execute_write,
)
from message_store import RecentMessageStore
from plugin_base import PluginStateStore


def _external_count(db_path: Path, table: str = "items") -> int:
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0] if row else 0)
    finally:
        connection.close()


def test_sqlite_connection_reuse(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    first = get_sqlite_connection(db_path)
    second = get_sqlite_connection(db_path)
    assert first is second


def test_sqlite_connection_reopens_after_close(tmp_path) -> None:
    db_path = tmp_path / "reopen.sqlite3"
    first = get_sqlite_connection(db_path)
    first.close()
    second = get_sqlite_connection(db_path)
    assert second is not first
    assert second.execute("SELECT 1").fetchone()[0] == 1


def test_sqlite_write_batches_commits(tmp_path) -> None:
    reset_sqlite_write_state_for_tests()
    db_path = tmp_path / "batch.sqlite3"
    connection = get_sqlite_connection(db_path)
    connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    connection.commit()

    def write_one(item_id: int) -> None:
        def writer(conn):
            conn.execute("INSERT INTO items(id, name) VALUES (?, ?)", (item_id, f"n-{item_id}"))

        sqlite_execute_write(db_path, writer, flush_every=3)

    write_one(1)
    write_one(2)
    assert get_pending_write_count(db_path) == 2
    assert _external_count(db_path) == 0

    write_one(3)
    assert get_pending_write_count(db_path) == 0
    assert _external_count(db_path) == 3

    rows = sqlite_execute_read(
        db_path,
        lambda conn: [int(row[0]) for row in conn.execute("SELECT id FROM items ORDER BY id").fetchall()],
    )
    assert rows == [1, 2, 3]
    reset_sqlite_write_state_for_tests()


def test_sqlite_write_flush_now(tmp_path) -> None:
    reset_sqlite_write_state_for_tests()
    db_path = tmp_path / "flush_now.sqlite3"
    connection = get_sqlite_connection(db_path)
    connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY)")
    connection.commit()

    def writer(conn):
        conn.execute("INSERT INTO items(id) VALUES (1)")
        return FLUSH_NOW

    sqlite_execute_write(db_path, writer, flush_every=100)
    assert get_pending_write_count(db_path) == 0
    assert _external_count(db_path) == 1
    reset_sqlite_write_state_for_tests()


def test_message_store_batches_until_flush_every(tmp_path) -> None:
    reset_sqlite_write_state_for_tests()
    db_path = tmp_path / "messages.sqlite3"
    store = RecentMessageStore(
        db_path=db_path,
        limit=50,
        trim_overflow=50,
        trim_every_writes=1000,
        write_flush_every=3,
    )

    for index in range(1, 3):
        store.upsert_message(
            {
                "internal_id": index,
                "received_at": f"2026-07-13T12:00:{index:02d}",
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
                "payload": {},
            }
        )

    assert get_pending_write_count(db_path) == 2
    assert _external_count(db_path, "recent_messages") == 0

    store.upsert_message(
        {
            "internal_id": 3,
            "received_at": "2026-07-13T12:00:03",
            "processed_at": None,
            "status": "queued",
            "error": "",
            "msgid": "3",
            "conversation_wxid": "wxid_a",
            "sender_wxid": "wxid_b",
            "msg_type": 1,
            "local_type": 1,
            "wxpid": 1,
            "is_group_message": False,
            "content": "msg-3",
            "plugin_results": [],
            "payload": {},
        }
    )
    assert get_pending_write_count(db_path) == 0
    assert _external_count(db_path, "recent_messages") == 3
    assert [item["internal_id"] for item in store.load_recent(10)] == [3, 2, 1]
    reset_sqlite_write_state_for_tests()


def test_plugin_state_store_batches_and_read_flushes(tmp_path) -> None:
    reset_sqlite_write_state_for_tests()
    db_path = Path(tmp_path) / "state.sqlite3"
    store = PluginStateStore("demo.plugin", storage_path=db_path, write_flush_every=4)

    store.set("a", 1)
    store.set("b", 2)
    assert get_pending_write_count(db_path) == 2
    assert _external_count(db_path, "plugin_state") == 0

    assert store.get("a") == 1
    assert store.get("b") == 2
    assert get_pending_write_count(db_path) == 0
    assert _external_count(db_path, "plugin_state") == 2
    reset_sqlite_write_state_for_tests()

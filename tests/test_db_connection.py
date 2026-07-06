from db_connection import get_sqlite_connection


def test_sqlite_connection_reuse(tmp_path) -> None:
    db_path = tmp_path / "test.sqlite3"
    first = get_sqlite_connection(db_path)
    second = get_sqlite_connection(db_path)
    assert first is second

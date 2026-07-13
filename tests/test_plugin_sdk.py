from datetime import datetime
from pathlib import Path

from plugins._plugin_sdk import (
    extract_api_error,
    extract_sql_rows,
    get_mapping_value,
    is_success_ret,
    parse_datetime_value,
    parse_int,
    resolve_downloaded_file_path,
    resolve_local_path,
)


def test_parse_int_supports_hex_and_float_text() -> None:
    assert parse_int("0x10") == 16
    assert parse_int("12.9") == 12
    assert parse_int("") is None


def test_parse_datetime_value_accepts_common_formats() -> None:
    assert parse_datetime_value("2026-07-13 12:00:00") == datetime(2026, 7, 13, 12, 0, 0)
    assert parse_datetime_value(1_720_000_000).year >= 2024


def test_mapping_and_sql_row_helpers() -> None:
    assert get_mapping_value({"User_Name": "wxid_a"}, "user_name") == "wxid_a"
    rows = extract_sql_rows(
        {
            "columns": ["user_name", "update_time"],
            "rows": [["wxid_a", 123], ["wxid_b", 456]],
        }
    )
    assert rows == [{"user_name": "wxid_a", "update_time": 123}, {"user_name": "wxid_b", "update_time": 456}]


def test_api_error_helpers() -> None:
    assert is_success_ret(0) is True
    assert extract_api_error({"ret": 1, "errmsg": "boom"}) == "boom"
    assert extract_api_error({"ret": 0}) == ""


def test_resolve_downloaded_file_path(tmp_path: Path) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    resolved = resolve_downloaded_file_path({"data": {"path": str(image)}})
    assert resolved == image
    assert resolve_local_path(str(image)) == image

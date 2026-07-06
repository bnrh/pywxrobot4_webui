from datetime import datetime
from pathlib import Path

from log_reader import build_log_entries, filter_log_entries, parse_log_line
from upload_paths import resolve_project_relative_dir, sanitize_upload_path_segment


def test_parse_log_line() -> None:
    line = "2026-07-06 12:00:00.123 | INFO     | server:create_app:100 - started"
    parsed = parse_log_line(line)
    assert parsed is not None
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "started"


def test_filter_log_entries_by_level() -> None:
    entries = build_log_entries(
        [
            "2026-07-06 12:00:00.123 | INFO     | server:create_app:1 - ok",
            "2026-07-06 12:00:01.123 | ERROR    | server:create_app:2 - bad",
        ]
    )
    filtered = filter_log_entries(entries, "all", "ERROR", "", "")
    assert len(filtered) == 1
    assert filtered[0]["level"] == "ERROR"


def test_sanitize_upload_path_segment() -> None:
    assert sanitize_upload_path_segment("hello world") == "hello_world"


def test_resolve_project_relative_dir(tmp_path, monkeypatch) -> None:
    import upload_paths

    monkeypatch.setattr(upload_paths, "PROJECT_ROOT", tmp_path)
    resolved = resolve_project_relative_dir("uploads/assets")
    assert resolved == (tmp_path / "uploads" / "assets").resolve()

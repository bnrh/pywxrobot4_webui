"""服务日志文件解析与过滤。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException

LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| (?P<level>[A-Z]+)\s+\| (?P<module>[^:]+):(?P<function>[^:]+):(?P<line>\d+) - (?P<message>.*)$"
)
LOG_TIME_RANGE_TO_DELTA = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
}
def format_local_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def parse_log_line(line: str) -> dict[str, Any] | None:
    match = LOG_LINE_PATTERN.match(line)
    if not match:
        return None
    groups = match.groupdict()
    try:
        groups["parsed_timestamp"] = datetime.strptime(groups["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
    return groups


def build_log_entries(lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        parsed_line = parse_log_line(line)
        entries.append(
            {
                "line_number": line_number,
                "raw": line,
                "parsed": parsed_line is not None,
                "timestamp": parsed_line["timestamp"] if parsed_line is not None else "",
                "level": parsed_line["level"] if parsed_line is not None else "",
                "module": parsed_line["module"] if parsed_line is not None else "",
                "function": parsed_line["function"] if parsed_line is not None else "",
                "source_line": int(parsed_line["line"]) if parsed_line is not None else None,
                "message": parsed_line["message"] if parsed_line is not None else line,
                "_parsed_timestamp": parsed_line["parsed_timestamp"] if parsed_line is not None else None,
            }
        )
    return entries


def filter_log_entries(
    entries: list[dict[str, Any]],
    time_range: str,
    level: str,
    module_query: str,
    keyword: str,
) -> list[dict[str, Any]]:
    normalized_time_range = (time_range or "all").strip().lower()
    normalized_level = (level or "").strip().upper()
    normalized_module_query = (module_query or "").strip().lower()
    normalized_keyword = (keyword or "").strip().lower()
    cutoff_time = None
    if normalized_time_range in LOG_TIME_RANGE_TO_DELTA:
        cutoff_time = datetime.now() - LOG_TIME_RANGE_TO_DELTA[normalized_time_range]

    filtered_entries: list[dict[str, Any]] = []
    for entry in entries:
        parsed_timestamp = entry.get("_parsed_timestamp")
        if cutoff_time is not None:
            if parsed_timestamp is None or parsed_timestamp < cutoff_time:
                continue
        if normalized_level:
            if str(entry.get("level") or "").upper() != normalized_level:
                continue
        if normalized_module_query:
            searchable_target = " ".join(
                filter(
                    None,
                    [
                        str(entry.get("module") or ""),
                        str(entry.get("function") or ""),
                        str(entry.get("raw") or "") if not entry.get("parsed") else "",
                    ],
                )
            )
            if normalized_module_query not in searchable_target.lower():
                continue
        if normalized_keyword:
            searchable_message = " ".join(
                filter(
                    None,
                    [
                        str(entry.get("message") or ""),
                        str(entry.get("raw") or ""),
                        str(entry.get("module") or ""),
                        str(entry.get("function") or ""),
                    ],
                )
            )
            if normalized_keyword not in searchable_message.lower():
                continue
        filtered_entries.append(entry)
    return filtered_entries



def build_log_payload(
    log_dir: Path,
    *,
    file_name: str | None = None,
    limit: int = 200,
    time_range: str = "all",
    level: str = "",
    module_query: str = "",
    keyword: str = "",
) -> dict[str, Any]:
    if not log_dir.exists():
        return {"files": [], "active_file": None, "lines": []}

    limit = max(1, min(limit, 5000))
    log_files = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not log_files:
        return {"files": [], "active_file": None, "lines": []}

    if file_name:
        target_file = next((path for path in log_files if path.name == file_name), None)
        if target_file is None:
            raise HTTPException(status_code=404, detail="未找到指定日志文件")
    else:
        target_file = log_files[0]

    all_lines = target_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    all_entries = build_log_entries(all_lines)
    matched_entries = filter_log_entries(all_entries, time_range, level, module_query, keyword)
    visible_entries = list(reversed(matched_entries[-limit:]))
    return {
        "files": [path.name for path in log_files],
        "active_file": target_file.name,
        "lines": [entry["raw"] for entry in visible_entries],
        "entries": [{key: value for key, value in entry.items() if key != "_parsed_timestamp"} for entry in visible_entries],
        "line_count": len(visible_entries),
        "matched_line_count": len(matched_entries),
        "total_line_count": len(all_lines),
        "parsed_line_count": sum(1 for entry in all_entries if entry["parsed"]),
        "filters": {
            "time_range": time_range,
            "level": level,
            "module_query": module_query,
            "keyword": keyword,
        },
        "updated_at": datetime.fromtimestamp(target_file.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
    }

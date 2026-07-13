import asyncio
import random
import re
from datetime import datetime
from enum import IntEnum
from html import unescape
from pathlib import Path
from typing import Any, Mapping

from core.config import PROJECT_ROOT
from utils.http_client import get_bytes, get_text, post_json, request as http_request
from utils.normalize import collapse_whitespace, is_truthy, normalize_wxpid

# 插件侧沿用 collapse_whitespace 语义，对外仍导出 normalize_text / is_truthy。
normalize_text = collapse_whitespace

# 需要完整 Response（headers / cookies）时可直接使用。
async_http_request = http_request


class MESSAGE_TYPES(IntEnum):
    TEXT = 0x1
    IMAGE = 0x3
    ADDFRIEND = 0x25
    VIDEO = 0x2B
    XML = 0x31
    NOTICE = 0x2710
    SYSMSG = 0x2712
    FILE = 0x600000031


WXPID_OPTION_DEFAULT = "__default_first__"
WXPID_OPTION_ALL = "__all__"


def normalize_wxpid_selection(value: Any) -> int | str | None:
    normalized = normalize_text(value)
    if value in (None, "", 0, "0") or normalized == WXPID_OPTION_DEFAULT:
        return None
    if normalized == WXPID_OPTION_ALL:
        return WXPID_OPTION_ALL
    return normalize_wxpid(value)


async def resolve_wxpid_targets(api: Any, value: Any) -> list[int | None]:
    normalized = normalize_wxpid_selection(value)
    live_wxpids: list[int] = []
    try:
        payload = await api.get_wx_pids()
        for item in payload if isinstance(payload, list) else []:
            try:
                wxpid = int(item)
            except (TypeError, ValueError):
                continue
            if wxpid not in live_wxpids:
                live_wxpids.append(wxpid)
    except Exception:
        live_wxpids = []

    if normalized == WXPID_OPTION_ALL:
        return live_wxpids
    if normalized is None:
        return live_wxpids[:1] if live_wxpids else [None]
    if live_wxpids and normalized not in live_wxpids:
        return live_wxpids[:1]
    return [normalized]


def to_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(to_string_list(item))
        return items
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[\n,，]", value) if item.strip()]
    text = str(value).strip()
    return [text] if text else []


def unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for item in to_string_list(values):
        if item not in seen:
            seen.add(item)
            items.append(item)
    return items


def to_string_set(value: Any) -> set[str]:
    return set(unique_strings(value))


def get_room_scope(config: Any) -> tuple[str, list[str]]:
    scope_config = config if isinstance(config, dict) else {}
    mode = normalize_text(scope_config.get("_scope_room_mode") or "all").lower() or "all"
    if mode not in {"all", "selected", "none"}:
        mode = "all"
    return mode, unique_strings(scope_config.get("_scope_room_ids"))


def filter_room_entries(
    entries: list[dict[str, Any]],
    config: Any,
    *,
    roomid_key: str = "roomid",
    allow_missing_entries: bool = False,
) -> list[dict[str, Any]]:
    mode, selected_room_ids = get_room_scope(config)
    if mode == "none":
        return []
    if mode == "selected" and not selected_room_ids:
        return []
    if mode != "selected":
        return entries

    selected_set = set(selected_room_ids)
    filtered_entries = [
        item
        for item in entries
        if isinstance(item, dict) and normalize_text(item.get(roomid_key)) in selected_set
    ]
    if not allow_missing_entries:
        return filtered_entries

    existing_room_ids = {normalize_text(item.get(roomid_key)) for item in filtered_entries if isinstance(item, dict)}
    for roomid in selected_room_ids:
        if roomid not in existing_room_ids:
            filtered_entries.append({roomid_key: roomid})
    return filtered_entries


async def sleep(milliseconds: float | int) -> None:
    timeout = max(0.0, float(milliseconds or 0)) / 1000.0
    await asyncio.sleep(timeout)


def random_between(min_value: Any, max_value: Any) -> int:
    minimum = int(float(min_value or 0))
    maximum = int(float(max_value or 0))
    if maximum <= minimum:
        return minimum
    return random.randint(minimum, maximum)


def get_message_type(event: Any) -> int | None:
    candidates = [
        getattr(event, "normalized_local_type", None),
        getattr(event, "normalized_msg_type", None),
        getattr(event, "local_type", None),
        getattr(event, "msg_type", None),
    ]
    for value in candidates:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def decode_xml_entities(value: Any) -> str:
    return unescape(str(value or ""))


def parse_xml_attributes(xml_text: Any) -> dict[str, str]:
    source = str(xml_text or "")
    open_tag_match = re.match(r"^\s*<[^\s/>]+\s+([^>]+?)(?:/?>)", source, re.S)
    if not open_tag_match:
        return {}
    attributes: dict[str, str] = {}
    for key, raw_value in re.findall(r'([\w:-]+)="([^"]*)"', open_tag_match.group(1)):
        attributes[key] = decode_xml_entities(raw_value)
    return attributes


def find_xml_tag_text(xml_text: Any, tag_path: str | list[str] | tuple[str, ...]) -> str:
    current = str(xml_text or "")
    tags = tag_path if isinstance(tag_path, (list, tuple)) else [tag_path]
    for tag in tags:
        pattern = re.compile(rf"<{re.escape(str(tag))}(?:\s[^>]*)?>([\s\S]*?)</{re.escape(str(tag))}>", re.I)
        match = pattern.search(current)
        if not match:
            return ""
        current = match.group(1)
    return normalize_text(decode_xml_entities(current))


def format_date_time(date_value: Any) -> str:
    if isinstance(date_value, datetime):
        date = date_value
    else:
        try:
            date = datetime.fromtimestamp(float(date_value))
        except (TypeError, ValueError, OSError):
            return ""
    return date.strftime("%Y-%m-%d %H:%M:%S")


def format_unix_time(value: Any) -> str:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return ""
    if numeric_value <= 0:
        return ""
    timestamp = numeric_value / 1000 if numeric_value > 1e12 else numeric_value
    try:
        return format_date_time(datetime.fromtimestamp(timestamp))
    except (OSError, OverflowError, ValueError):
        return ""


def parse_biz_articles(xml_text: Any) -> list[dict[str, Any]]:
    source = str(xml_text or "")
    category_match = re.search(r'<category\b[^>]*count="(\d+)"[^>]*>', source, re.I)
    if not category_match:
        return []
    expected_count = int(category_match.group(1))
    if expected_count <= 0:
        return []

    nickname = find_xml_tag_text(source, ["publisher", "nickname"])
    username = find_xml_tag_text(source, ["publisher", "username"])
    if not nickname or not username:
        return []

    items: list[dict[str, Any]] = []
    for match in re.finditer(r"<item>([\s\S]*?)</item>", source, re.I):
        item_xml = match.group(1)
        title = find_xml_tag_text(item_xml, "title")
        pub_time = format_unix_time(find_xml_tag_text(item_xml, "pub_time"))
        url = find_xml_tag_text(item_xml, "url")
        if "mp.weixin.qq.com" in url:
            items.append(
                {
                    "title": title,
                    "pub_time": pub_time,
                    "url": url,
                    "nickname": nickname,
                    "username": username,
                    "monitor_time": format_date_time(datetime.now()),
                }
            )

    return items if len(items) == expected_count else []


def build_event_payload(event: Any) -> dict[str, Any]:
    payload = dict(getattr(event, "raw_payload", {}) or {})
    payload.update(
        {
            "normalized_msgid": getattr(event, "normalized_msgid", ""),
            "normalized_wxpid": getattr(event, "normalized_wxpid", None),
            "normalized_local_type": getattr(event, "normalized_local_type", None),
            "normalized_msg_type": getattr(event, "normalized_msg_type", None),
            "normalized_content": getattr(event, "normalized_content", ""),
            "conversation_wxid": getattr(event, "conversation_wxid", ""),
            "sender_wxid": getattr(event, "sender_wxid", ""),
            "is_group_message": getattr(event, "is_group_message", False),
            "is_image": getattr(event, "is_image", False),
        }
    )
    return payload


async def async_http_get(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    timeout: float = 10.0,
    raise_for_status: bool = True,
    client: Any = None,
) -> tuple[int, str]:
    """统一插件 GET（httpx），返回 (status_code, text)。"""
    return await get_text(
        url,
        headers=headers,
        params=params,
        timeout=timeout,
        raise_for_status=raise_for_status,
        client=client,
    )


async def async_http_post(
    url: str,
    *,
    json_payload: Any = None,
    data: Any = None,
    content: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    files: Any = None,
    timeout: float = 10.0,
    raise_for_status: bool = True,
    client: Any = None,
) -> tuple[int, str]:
    """统一插件 POST（httpx）。

    - 传 json_payload 时按 JSON 发送；
    - 否则可传 data / content / files。
    """
    if json_payload is not None:
        return await post_json(
            url,
            json_payload,
            headers=dict(headers or {}),
            timeout=timeout,
            raise_for_status=raise_for_status,
            client=client,
        )
    response = await http_request(
        "POST",
        url,
        headers=headers,
        content=content,
        data=data,
        params=params,
        files=files,
        timeout=timeout,
        client=client,
    )
    if raise_for_status and response.status_code >= 400:
        raise RuntimeError(response.text or f"HTTP {response.status_code}")
    return int(response.status_code), response.text


async def async_http_get_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    client: Any = None,
) -> tuple[int, bytes, str]:
    """统一插件二进制 GET，返回 (status_code, content, content_type)。"""
    return await get_bytes(url, headers=headers, timeout=timeout, client=client)


async def post_json_request(
    url: str,
    payload: Any,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, str]:
    return await async_http_post(url, json_payload=payload, headers=headers, timeout=timeout)


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = normalize_text(value)
    if not text:
        return None
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(float(text))
    except ValueError:
        return None


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = normalize_text(value)
    if not text:
        return None
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        timestamp = int(text)
        if abs(timestamp) >= 1_000_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp)

    normalized_text = text.replace("T", " ")
    for format_string in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized_text, format_string)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"无法解析时间: {value}") from exc


def normalize_mapping_key(value: Any) -> str:
    return normalize_text(value).lower()


def get_mapping_value(item: Any, *keys: str) -> Any:
    if not isinstance(item, dict):
        return None
    normalized_map = {normalize_mapping_key(key): value for key, value in item.items()}
    for key in keys:
        normalized_key = normalize_mapping_key(key)
        if normalized_key in normalized_map:
            return normalized_map[normalized_key]
    return None


def normalize_row_list(rows: Any, column_names: list[Any] | None = None) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return normalized_rows
    normalized_columns = [normalize_text(column_name) or f"col_{index}" for index, column_name in enumerate(column_names or [])]
    for row in rows:
        if isinstance(row, dict):
            normalized_rows.append(dict(row))
            continue
        if isinstance(row, (list, tuple)) and normalized_columns:
            normalized_rows.append(
                {
                    normalized_columns[index]: row[index] if index < len(row) else None
                    for index in range(len(normalized_columns))
                }
            )
    return normalized_rows


def extract_rows_from_payload(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return normalize_row_list(payload)
    if not isinstance(payload, dict):
        return None

    columns = payload.get("columns") or payload.get("header") or payload.get("headers") or payload.get("fields")
    if isinstance(columns, list):
        for key in ("rows", "items", "data", "list", "result", "results"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return normalize_row_list(candidate, columns)

    for key in ("data", "rows", "items", "list", "result", "results"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return normalize_row_list(candidate)
        if isinstance(candidate, dict):
            extracted = extract_rows_from_payload(candidate)
            if extracted is not None:
                return extracted
    return None


def extract_sql_rows(payload: Any) -> list[dict[str, Any]]:
    extracted = extract_rows_from_payload(payload)
    return extracted if extracted is not None else []


def is_success_ret(value: Any) -> bool:
    # 避免 `1 in (True,)` 因 True==1 误判成功。
    if value is True or value is None:
        return True
    return value in ("", 0, "0")


def extract_api_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return normalize_text(payload)
    if is_success_ret(payload.get("ret")):
        return ""
    for key in ("error", "errmsg", "err_msg", "message", "msg", "detail"):
        text = normalize_text(payload.get(key))
        if text:
            return text
    return f"ret={payload.get('ret')}"


def resolve_response_status_code(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    return parse_int(payload.get("status_code"))


def resolve_local_path(raw_path: Any, *, base_dir: Path | None = None) -> Path | None:
    path_text = normalize_text(raw_path)
    if not path_text:
        return None
    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = (base_dir or PROJECT_ROOT) / candidate
    if candidate.exists():
        return candidate
    return None


def resolve_downloaded_file_path(response: Any, *, base_dir: Path | None = None) -> Path | None:
    if not isinstance(response, dict):
        return None

    candidates: list[Any] = []
    for key in ("path", "save_path", "file_path", "download_path"):
        value = response.get(key)
        if value not in (None, ""):
            candidates.append(value)

    payload = response.get("data")
    if isinstance(payload, dict):
        for key in ("path", "save_path", "file_path", "download_path"):
            value = payload.get(key)
            if value not in (None, ""):
                candidates.append(value)

    for raw_path in candidates:
        candidate = resolve_local_path(raw_path, base_dir=base_dir)
        if candidate is not None:
            return candidate
    return None


# 兼容旧命名
resolve_local_image_path = resolve_local_path
resolve_downloaded_image_path = resolve_downloaded_file_path

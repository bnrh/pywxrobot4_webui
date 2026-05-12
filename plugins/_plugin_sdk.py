import asyncio
import json
import random
import re
from datetime import datetime
from enum import IntEnum
from html import unescape
from typing import Any
from urllib import error, request


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


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_wxpid_selection(value: Any) -> int | str | None:
    normalized = normalize_text(value)
    if value in (None, "", 0, "0") or normalized == WXPID_OPTION_DEFAULT:
        return None
    if normalized == WXPID_OPTION_ALL:
        return WXPID_OPTION_ALL
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def post_json_request(
    url: str,
    payload: Any,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
) -> tuple[int, str]:
    request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = request.Request(url, data=request_body, headers=request_headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(body or f"HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

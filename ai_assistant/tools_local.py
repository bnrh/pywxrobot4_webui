"""Local AI assistant tool helpers and execution."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from core.client import WxRobotApiClient

from utils.normalize import normalize_text

from .constants import MAX_TOOL_RESULT_ITEMS, MAX_TOOL_RESULT_STRING_LENGTH
from .tool_registry import LOCAL_TOOL_REGISTRY


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_text(value: Any) -> str:
    return normalize_text(value)

def _coerce_string_sequence(value: Any) -> list[str] | str:
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return str(value or "").strip()


def _safe_trim_string(value: Any) -> str:
    text = str(value or "")
    if len(text) <= MAX_TOOL_RESULT_STRING_LENGTH:
        return text
    return f"{text[:MAX_TOOL_RESULT_STRING_LENGTH]}...<truncated>"


def _compact_tool_result(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _compact_tool_result(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_compact_tool_result(item) for item in value[:MAX_TOOL_RESULT_ITEMS]]
        if len(value) > MAX_TOOL_RESULT_ITEMS:
            items.append({"_truncated": len(value) - MAX_TOOL_RESULT_ITEMS})
        return items
    if isinstance(value, str):
        return _safe_trim_string(value)
    return value


def _clamp_limit(value: Any, default: int = 20, maximum: int = 100) -> int:
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return default
    if numeric_value <= 0:
        return default
    return min(numeric_value, maximum)


def _search_items(items: list[dict[str, Any]], query: str, fields: list[str], limit: int = 20) -> dict[str, Any]:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        raise RuntimeError("query 不能为空")
    limited = _clamp_limit(limit)
    results = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        searchable_text = "\n".join(str(item.get(field) or "") for field in fields).lower()
        if normalized_query in searchable_text:
            results.append(item)
            if len(results) >= limited:
                break
    return {
        "query": query,
        "limit": limited,
        "count": len(results),
        "items": results,
    }


def _summarize_contacts(contacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "wxid": item.get("wxid", ""),
            "wxh": item.get("wxh", ""),
            "nickname": item.get("nickname", ""),
            "remarks": item.get("remarks", ""),
        }
        for item in contacts if isinstance(item, dict)
    ]


def _summarize_room_members(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "username": item.get("username", ""),
            "alias": item.get("alias", ""),
            "nick_name": item.get("nick_name", ""),
            "room_nick_name": item.get("room_nick_name", ""),
            "remarks": item.get("remarks", ""),
        }
        for item in members if isinstance(item, dict)
    ]


def _normalize_contact_wxid(item: dict[str, Any]) -> str:
    return str(item.get("wxid") or item.get("username") or "").strip()


def _normalize_room_member_wxid(item: dict[str, Any]) -> str:
    return str(item.get("username") or item.get("wxid") or "").strip()


def _build_room_friend_match_items(room_members: list[dict[str, Any]], friends: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    friend_lookup = {
        wxid: item
        for item in friends if isinstance(item, dict)
        for wxid in [_normalize_contact_wxid(item)]
        if wxid
    }

    valid_room_member_count = 0
    matched_items: list[dict[str, Any]] = []
    for member in room_members if isinstance(room_members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = _normalize_room_member_wxid(member)
        if not member_wxid:
            continue
        valid_room_member_count += 1
        friend = friend_lookup.get(member_wxid)
        if friend is None:
            continue

        room_nick_name = str(member.get("room_nick_name") or "").strip()
        nick_name = str(member.get("nick_name") or member.get("nickname") or "").strip()
        alias = str(member.get("alias") or "").strip()
        remarks = str(member.get("remarks") or "").strip()
        friend_nickname = str(friend.get("nickname") or "").strip()
        friend_remarks = str(friend.get("remarks") or "").strip()
        matched_items.append(
            {
                "wxid": member_wxid,
                "display_name": room_nick_name or nick_name or friend_remarks or friend_nickname or member_wxid,
                "room_nick_name": room_nick_name,
                "nick_name": nick_name,
                "alias": alias,
                "remarks": remarks,
                "friend_nickname": friend_nickname,
                "friend_remarks": friend_remarks,
                "wxh": str(friend.get("wxh") or friend.get("alias") or "").strip(),
            }
        )

    return matched_items, valid_room_member_count, len(friend_lookup)


def _build_room_member_lookup(room_members: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], int]:
    room_member_lookup: dict[str, dict[str, Any]] = {}
    valid_room_member_count = 0
    for member in room_members if isinstance(room_members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = _normalize_room_member_wxid(member)
        if not member_wxid:
            continue
        valid_room_member_count += 1
        room_member_lookup.setdefault(member_wxid, member)
    return room_member_lookup, valid_room_member_count


def _build_shared_room_member_items(
    first_room_members: list[dict[str, Any]],
    second_room_members: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    first_lookup, total_first_room_members = _build_room_member_lookup(first_room_members)
    second_lookup, total_second_room_members = _build_room_member_lookup(second_room_members)

    shared_items: list[dict[str, Any]] = []
    for member_wxid, first_member in first_lookup.items():
        second_member = second_lookup.get(member_wxid)
        if second_member is None:
            continue

        first_room_nick_name = str(first_member.get("room_nick_name") or "").strip()
        second_room_nick_name = str(second_member.get("room_nick_name") or "").strip()
        first_nick_name = str(first_member.get("nick_name") or first_member.get("nickname") or "").strip()
        second_nick_name = str(second_member.get("nick_name") or second_member.get("nickname") or "").strip()
        first_alias = str(first_member.get("alias") or "").strip()
        second_alias = str(second_member.get("alias") or "").strip()
        first_remarks = str(first_member.get("remarks") or "").strip()
        second_remarks = str(second_member.get("remarks") or "").strip()

        shared_items.append(
            {
                "wxid": member_wxid,
                "display_name": first_room_nick_name or second_room_nick_name or first_nick_name or second_nick_name or member_wxid,
                "first_room_nick_name": first_room_nick_name,
                "second_room_nick_name": second_room_nick_name,
                "first_nick_name": first_nick_name,
                "second_nick_name": second_nick_name,
                "first_alias": first_alias,
                "second_alias": second_alias,
                "first_remarks": first_remarks,
                "second_remarks": second_remarks,
            }
        )

    return shared_items, total_first_room_members, total_second_room_members


def _filter_room_friend_match_items(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return list(items)
    filtered_items: list[dict[str, Any]] = []
    for item in items:
        searchable_text = "\n".join(
            str(item.get(field) or "")
            for field in [
                "wxid",
                "display_name",
                "room_nick_name",
                "nick_name",
                "alias",
                "remarks",
                "friend_nickname",
                "friend_remarks",
                "wxh",
            ]
        ).lower()
        if normalized_query in searchable_text:
            filtered_items.append(item)
    return filtered_items


def _filter_shared_room_member_items(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return list(items)
    filtered_items: list[dict[str, Any]] = []
    for item in items:
        searchable_text = "\n".join(
            str(item.get(field) or "")
            for field in [
                "wxid",
                "display_name",
                "first_room_nick_name",
                "second_room_nick_name",
                "first_nick_name",
                "second_nick_name",
                "first_alias",
                "second_alias",
                "first_remarks",
                "second_remarks",
            ]
        ).lower()
        if normalized_query in searchable_text:
            filtered_items.append(item)
    return filtered_items


async def _collect_room_friend_matches(
    tool_executor: "_McpHttpToolExecutor",
    roomid: str,
    wxpid: int | None,
) -> tuple[list[dict[str, Any]], int, int]:
    friend_arguments: dict[str, Any] = {}
    room_arguments: dict[str, Any] = {"roomid": roomid}
    if wxpid is not None:
        friend_arguments["wxpid"] = wxpid
        room_arguments["wxpid"] = wxpid

    friends, room_members = await asyncio.gather(
        tool_executor.call_tool("get_user_list", friend_arguments),
        tool_executor.call_tool("get_room_members", room_arguments),
    )
    if not isinstance(friends, list):
        raise RuntimeError("get_user_list 返回格式异常")
    if not isinstance(room_members, list):
        raise RuntimeError("get_room_members 返回格式异常")
    return _build_room_friend_match_items(room_members, friends)


async def _collect_shared_room_members(
    tool_executor: "_McpHttpToolExecutor",
    first_roomid: str,
    second_roomid: str,
    wxpid: int | None,
) -> tuple[list[dict[str, Any]], int, int]:
    first_room_arguments: dict[str, Any] = {"roomid": first_roomid}
    second_room_arguments: dict[str, Any] = {"roomid": second_roomid}
    if wxpid is not None:
        first_room_arguments["wxpid"] = wxpid
        second_room_arguments["wxpid"] = wxpid

    first_room_members, second_room_members = await asyncio.gather(
        tool_executor.call_tool("get_room_members", first_room_arguments),
        tool_executor.call_tool("get_room_members", second_room_arguments),
    )
    if not isinstance(first_room_members, list):
        raise RuntimeError("第一个群的 get_room_members 返回格式异常")
    if not isinstance(second_room_members, list):
        raise RuntimeError("第二个群的 get_room_members 返回格式异常")
    return _build_shared_room_member_items(first_room_members, second_room_members)


async def _execute_local_tool_call(
    tool_executor: "_McpHttpToolExecutor",
    tool_name: str,
    arguments: dict[str, Any],
) -> Any:
    roomid = _coerce_text(arguments.get("roomid"))
    first_roomid = _coerce_text(arguments.get("first_roomid") or arguments.get("roomid_a") or arguments.get("roomid1"))
    second_roomid = _coerce_text(arguments.get("second_roomid") or arguments.get("roomid_b") or arguments.get("roomid2"))
    wxpid = _coerce_optional_int(arguments.get("wxpid"))
    if tool_name == "current_datetime":
        return _get_current_datetime_payload()
    if tool_name in {"count_room_friend_members", "list_room_friend_members"} and not roomid:
        raise RuntimeError("roomid 不能为空")
    if tool_name in {"count_shared_room_members", "list_shared_room_members"} and (not first_roomid or not second_roomid):
        raise RuntimeError("first_roomid 和 second_roomid 不能为空")

    if tool_name == "count_shared_room_members":
        sample_limit = _clamp_int(arguments.get("sample_limit"), 10, 1, 20)
        shared_items, total_first_room_members, total_second_room_members = await _collect_shared_room_members(
            tool_executor,
            first_roomid,
            second_roomid,
            wxpid,
        )
        return {
            "first_roomid": first_roomid,
            "second_roomid": second_roomid,
            "wxpid": wxpid,
            "total_first_room_members": total_first_room_members,
            "total_second_room_members": total_second_room_members,
            "shared_member_count": len(shared_items),
            "first_room_unique_member_count": max(0, total_first_room_members - len(shared_items)),
            "second_room_unique_member_count": max(0, total_second_room_members - len(shared_items)),
            "sample_limit": sample_limit,
            "sample_items": shared_items[:sample_limit],
            "is_complete": True,
        }

    if tool_name == "list_shared_room_members":
        offset = _clamp_int(arguments.get("offset"), 0, 0, 1000000)
        limit = _clamp_int(arguments.get("limit"), 20, 1, 40)
        query = _coerce_text(arguments.get("query"))
        shared_items, total_first_room_members, total_second_room_members = await _collect_shared_room_members(
            tool_executor,
            first_roomid,
            second_roomid,
            wxpid,
        )
        filtered_items = _filter_shared_room_member_items(shared_items, query)
        page_items = filtered_items[offset:offset + limit]
        next_offset = offset + len(page_items)
        return {
            "first_roomid": first_roomid,
            "second_roomid": second_roomid,
            "wxpid": wxpid,
            "query": query,
            "offset": offset,
            "limit": limit,
            "total_first_room_members": total_first_room_members,
            "total_second_room_members": total_second_room_members,
            "total_count": len(filtered_items),
            "has_more": next_offset < len(filtered_items),
            "next_offset": next_offset if next_offset < len(filtered_items) else None,
            "items": page_items,
            "is_complete": True,
        }

    if tool_name == "count_room_friend_members":
        sample_limit = _clamp_int(arguments.get("sample_limit"), 10, 1, 20)
        matched_items, total_room_members, total_friends = await _collect_room_friend_matches(tool_executor, roomid, wxpid)
        return {
            "roomid": roomid,
            "wxpid": wxpid,
            "total_room_members": total_room_members,
            "total_friends": total_friends,
            "matched_friend_count": len(matched_items),
            "unmatched_room_member_count": max(0, total_room_members - len(matched_items)),
            "sample_limit": sample_limit,
            "sample_items": matched_items[:sample_limit],
            "is_complete": True,
        }

    if tool_name == "list_room_friend_members":
        offset = _clamp_int(arguments.get("offset"), 0, 0, 1000000)
        limit = _clamp_int(arguments.get("limit"), 20, 1, 40)
        query = _coerce_text(arguments.get("query"))
        matched_items, total_room_members, total_friends = await _collect_room_friend_matches(tool_executor, roomid, wxpid)
        filtered_items = _filter_room_friend_match_items(matched_items, query)
        page_items = filtered_items[offset:offset + limit]
        next_offset = offset + len(page_items)
        return {
            "roomid": roomid,
            "wxpid": wxpid,
            "query": query,
            "offset": offset,
            "limit": limit,
            "total_room_members": total_room_members,
            "total_friends": total_friends,
            "total_count": len(filtered_items),
            "has_more": next_offset < len(filtered_items),
            "next_offset": next_offset if next_offset < len(filtered_items) else None,
            "items": page_items,
            "is_complete": True,
        }

    raise RuntimeError(f"暂不支持本地工具 {tool_name}")

def _get_current_datetime_payload() -> dict[str, Any]:
    now = datetime.now().astimezone()
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday_name = weekday_names[now.weekday()]
    timezone_name = now.tzname() or "本地时区"
    offset = now.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return {
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "iso_datetime": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday_name,
        "timezone_name": timezone_name,
        "timezone_offset": offset,
        "unix_timestamp": int(now.timestamp()),
        "is_complete": True,
    }


def _build_current_time_prompt() -> str:
    payload = _get_current_datetime_payload()
    return (
        "时间上下文："
        f"当前本地时间为 {payload['current_datetime']}，{payload['weekday']}，"
        f"时区 {payload['timezone_name']} ({payload['timezone_offset']})。"
        f"ISO 8601 时间：{payload['iso_datetime']}。"
        "当用户提到今天、昨天、明天、最近几小时、截至目前等相对时间时，"
        "以上述当前时间为准进行理解、推理和回答。"
    )

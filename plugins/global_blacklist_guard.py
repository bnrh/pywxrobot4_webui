from datetime import datetime
from typing import Any

from ._global_blacklist import (
    BLACKLIST_MEMBERS_NAMESPACE,
    BLACKLIST_PLUGIN_NAME,
    ROOM_MEMBER_CACHE_NAMESPACE,
    build_room_cache_key,
    extract_removed_member_names,
    is_room_removal_notice,
    normalize_monitored_rooms,
)
from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text, unique_strings


name = BLACKLIST_PLUGIN_NAME
description = "监听指定群聊的移人通知，维护全局黑名单，并让所有消息插件忽略黑名单成员"
event_filters = ["notice", "sysmsg"]
config_schema = [
    {
        "key": "monitored_rooms",
        "label": "监听群聊",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["roomid"],
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能配置一次",
        "empty_text": "暂无监听群聊，点击“新增”后选择需要自动拉黑移出成员的群聊。",
        "description": "仅监控这里选中的群聊。成员被移出这些群后，会自动加入全局黑名单，后续所有消息插件都会忽略其私聊或群内消息。",
        "columns": [
            {
                "key": "roomid",
                "label": "群聊",
                "type": "select",
                "searchable": True,
                "options_source": "room_options",
                "empty_option_label": "",
                "placeholder": "输入群名称或 wxid 搜索",
                "required": True,
                "required_message": "群聊不能为空",
                "width": "wide",
                "editor_span": 4,
            }
        ],
    }
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_snapshot_store(context: Any):
    return context.state.namespace(ROOM_MEMBER_CACHE_NAMESPACE)


def get_blacklist_store(context: Any):
    return context.state.namespace(BLACKLIST_MEMBERS_NAMESPACE)


def resolve_room_name(event: Any, roomid: str) -> str:
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        room_name = normalize_text(first_non_empty("conversation_display_name", "title_display"))
        if room_name and room_name != roomid:
            return room_name
    return roomid


def normalize_member(member: Any) -> dict[str, str] | None:
    if not isinstance(member, dict):
        return None

    wxid = normalize_text(member.get("username") or member.get("wxid"))
    if not wxid:
        return None

    room_nick_name = normalize_text(member.get("room_nick_name") or member.get("roomNickName"))
    nick_name = normalize_text(member.get("nick_name") or member.get("nickName") or member.get("nickname"))
    remarks = normalize_text(member.get("remarks") or member.get("remark"))
    display_name = room_nick_name or nick_name or remarks or wxid
    return {
        "wxid": wxid,
        "room_nick_name": room_nick_name,
        "nick_name": nick_name,
        "remarks": remarks,
        "display_name": display_name,
    }


def member_aliases(member: dict[str, str]) -> list[str]:
    return unique_strings(
        [
            member.get("room_nick_name"),
            member.get("nick_name"),
            member.get("remarks"),
            member.get("display_name"),
            member.get("wxid"),
        ]
    )


async def fetch_room_member_map(context: Any, roomid: str, wxpid: int | None) -> dict[str, dict[str, str]]:
    members = await context.api.get_room_members(roomid, wxpid)
    normalized_members: dict[str, dict[str, str]] = {}
    for item in members if isinstance(members, list) else []:
        normalized_member = normalize_member(item)
        if normalized_member is None:
            continue
        normalized_members[normalized_member["wxid"]] = normalized_member
    return normalized_members


async def warmup_monitored_room_snapshots(context: Any) -> None:
    room_ids = normalize_monitored_rooms(context.config)
    if not room_ids:
        return

    snapshot_store = get_snapshot_store(context)
    for roomid in room_ids:
        try:
            snapshot_store.set(build_room_cache_key(roomid), await fetch_room_member_map(context, roomid, None))
        except Exception as exc:
            context.logger.warning("全局黑名单插件预热群成员快照失败", {"roomid": roomid, "error": str(exc)})


def resolve_removed_members(
    previous_members: dict[str, dict[str, str]],
    current_members: dict[str, dict[str, str]],
    removed_names: list[str],
) -> list[dict[str, str]]:
    removed_candidates = [
        member
        for wxid, member in previous_members.items()
        if wxid not in current_members
    ]
    if not removed_candidates:
        return []

    normalized_removed_names = {normalize_text(item) for item in removed_names if normalize_text(item)}
    if not normalized_removed_names:
        return removed_candidates

    matched_members = [
        member
        for member in removed_candidates
        if normalized_removed_names & set(member_aliases(member))
    ]
    return matched_members or removed_candidates


def merge_blacklist_record(existing: Any, member: dict[str, str], roomid: str, room_name: str, content_preview: str, wxpid: int | None) -> dict[str, Any]:
    existing_record = existing if isinstance(existing, dict) else {}
    added_at = normalize_text(existing_record.get("added_at")) or now_iso()
    recorded_rooms = [
        value
        for value in unique_strings(existing_record.get("rooms"))
        if value != roomid
    ]
    if roomid:
        recorded_rooms.append(roomid)

    return {
        "wxid": member["wxid"],
        "display_name": member["display_name"],
        "room_nick_name": member["room_nick_name"],
        "nick_name": member["nick_name"],
        "remarks": member["remarks"],
        "reason": "removed_from_room",
        "added_at": added_at,
        "updated_at": now_iso(),
        "last_roomid": roomid,
        "last_room_name": room_name,
        "last_notice": content_preview,
        "wxpid": wxpid,
        "rooms": recorded_rooms,
    }


async def startup(context):
    await warmup_monitored_room_snapshots(context)


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed"):
        await warmup_monitored_room_snapshots(context)


async def handle_message(event, context):
    type_code = get_message_type(event)
    if type_code not in {MESSAGE_TYPES.NOTICE, MESSAGE_TYPES.SYSMSG}:
        return {"handled": False, "detail": ""}

    roomid = normalize_text(event.conversation_wxid)
    monitored_rooms = set(normalize_monitored_rooms(context.config))
    if not roomid or not roomid.endswith("@chatroom") or roomid not in monitored_rooms:
        return {"handled": False, "detail": ""}

    snapshot_store = get_snapshot_store(context)
    snapshot_key = build_room_cache_key(roomid, event.normalized_wxpid)
    previous_members = snapshot_store.get(snapshot_key, {})
    previous_members = previous_members if isinstance(previous_members, dict) else {}

    try:
        current_members = await fetch_room_member_map(context, roomid, event.normalized_wxpid)
    except Exception as exc:
        context.logger.warning(
            "全局黑名单插件刷新群成员快照失败",
            {"roomid": roomid, "wxpid": event.normalized_wxpid, "error": str(exc)},
        )
        return {"handled": False, "detail": ""}

    snapshot_store.set(snapshot_key, current_members)

    if not is_room_removal_notice(event):
        return {"handled": False, "detail": ""}

    removed_names = extract_removed_member_names(event.normalized_content)
    removed_members = resolve_removed_members(previous_members, current_members, removed_names)
    if not removed_members:
        context.logger.warning(
            "全局黑名单插件未能识别被移出成员",
            {
                "roomid": roomid,
                "wxpid": event.normalized_wxpid,
                "removed_names": removed_names,
                "previous_member_count": len(previous_members),
                "current_member_count": len(current_members),
                "content": normalize_text(event.normalized_content)[:120],
            },
        )
        return {"handled": False, "detail": ""}

    room_name = resolve_room_name(event, roomid)
    content_preview = normalize_text(event.normalized_content)[:120]
    blacklist_store = get_blacklist_store(context)
    stored_members: list[dict[str, Any]] = []
    for member in removed_members:
        record = merge_blacklist_record(
            blacklist_store.get(member["wxid"]),
            member,
            roomid,
            room_name,
            content_preview,
            event.normalized_wxpid,
        )
        blacklist_store.set(member["wxid"], record)
        stored_members.append(record)

    context.logger.info(
        "全局黑名单已新增成员",
        {
            "roomid": roomid,
            "room_name": room_name,
            "wxpid": event.normalized_wxpid,
            "members": [
                {"wxid": item["wxid"], "display_name": item["display_name"]}
                for item in stored_members
            ],
        },
    )
    member_names = [item["display_name"] for item in stored_members]
    return {
        "handled": True,
        "detail": f"已加入全局黑名单: {', '.join(member_names)}",
        "data": {
            "roomid": roomid,
            "room_name": room_name,
            "members": stored_members,
        },
    }
import re
from typing import Any

from core.config import normalize_plugin_module_name

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text, unique_strings


BLACKLIST_PLUGIN_MODULE = normalize_plugin_module_name("plugins.global_blacklist_guard")
BLACKLIST_PLUGIN_NAME = "global_blacklist_guard"
BLACKLIST_MEMBERS_NAMESPACE = "blacklist_members"
ROOM_MEMBER_CACHE_NAMESPACE = "room_member_cache"

REMOVAL_NOTICE_TEXT = "移出了群聊"
REMOVAL_MEMBER_SEGMENT_PATTERN = re.compile(r"将([\s\S]+?)移出了群聊")
QUOTED_NAME_PATTERN = re.compile(r"[\"“](.+?)[\"”]")


def normalize_monitored_rooms(config: Any) -> list[str]:
    raw_rooms = config.get("monitored_rooms") if isinstance(config, dict) else []
    normalized_rooms: list[str] = []
    for item in raw_rooms if isinstance(raw_rooms, list) else []:
        if isinstance(item, dict):
            roomid = normalize_text(item.get("roomid") or item.get("wxid"))
        else:
            roomid = normalize_text(item)
        if roomid and roomid not in normalized_rooms:
            normalized_rooms.append(roomid)
    return normalized_rooms


def build_room_cache_key(roomid: Any, wxpid: Any = None) -> str:
    return normalize_text(roomid)


def is_room_removal_notice(event: Any) -> bool:
    type_code = get_message_type(event)
    if type_code not in {MESSAGE_TYPES.NOTICE, MESSAGE_TYPES.SYSMSG}:
        return False

    content = normalize_text(getattr(event, "normalized_content", "") or getattr(event, "content", ""))
    if not content:
        return False
    return REMOVAL_NOTICE_TEXT in content or "<delchatroommember" in content.lower()


def extract_removed_member_names(content: Any) -> list[str]:
    text = normalize_text(content)
    if not text:
        return []

    source_segment = text
    matched_segment = REMOVAL_MEMBER_SEGMENT_PATTERN.search(text)
    if matched_segment:
        source_segment = matched_segment.group(1)

    quoted_names = [
        normalize_text(match.group(1).strip(" \"'“”‘’"))
        for match in QUOTED_NAME_PATTERN.finditer(source_segment)
        if normalize_text(match.group(1).strip(" \"'“”‘’"))
    ]
    if quoted_names:
        return unique_strings(quoted_names)

    fallback_names = [
        normalize_text(part.strip(" \"'“”‘’"))
        for part in re.split(r"[、,，]", source_segment.replace("和", "、"))
        if normalize_text(part.strip(" \"'“”‘’"))
    ]
    return unique_strings(fallback_names)


def resolve_blacklist_subject_wxid(event: Any) -> str:
    if bool(getattr(event, "is_group_message", False)):
        return normalize_text(getattr(event, "sender_wxid", ""))
    return normalize_text(getattr(event, "sender_wxid", "") or getattr(event, "conversation_wxid", ""))
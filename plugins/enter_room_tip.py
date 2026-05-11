import re
from pathlib import Path

from config import PROJECT_ROOT

from ._plugin_sdk import MESSAGE_TYPES, find_xml_tag_text, get_message_type, normalize_text, parse_xml_attributes, sleep


name = "enter_room_tip"
description = "检测新成员入群后自动发送欢迎语或图片"
event_filters = ["notice", "sysmsg"]
NOTICE_DELAY_SECONDS = 3.0
SYSMSG_DELAY_SECONDS = 1.0
IMAGE_UPLOAD_DIR = "uploads/enter_room_tip"
ENTER_ROOM_PATTERN = re.compile(r"加入(?:了)?群聊")
CONTENT_PREVIEW_LIMIT = 160
config_schema = [
    {
        "key": "room_welcomes",
        "aliases": ["welcome_file"],
        "label": "群欢迎规则",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["roomid", "content", "path"],
        "require_one_of": ["content", "path"],
        "require_one_of_message": "请至少填写文本内容或图片路径",
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能保留一条欢迎规则",
        "empty_text": "暂无欢迎规则，点击“新增”后为目标群配置欢迎文本或图片。",
        "description": "每个群聊仅保留一条欢迎规则。配置文本就发送文本，配置图片就发送图片；两者都填时会依次发送。",
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
            },
            {
                "key": "content",
                "label": "文本内容",
                "type": "textarea",
                "rows": 3,
                "width": "wide",
                "placeholder": "填写欢迎文本，可使用 {nick_name} 或 @{nick_name}",
            },
            {
                "key": "path",
                "label": "图片路径",
                "type": "text",
                "file_picker": "project-image",
                "pick_label": "选择图片",
                "accept": "image/*,.png,.jpg,.jpeg,.gif,.webp,.bmp",
                "upload_dir": IMAGE_UPLOAD_DIR,
                "width": "wide",
                "placeholder": "支持绝对路径，或相对于项目根目录的相对路径",
            },
        ],
    },
    {
        "key": "message_interval_seconds",
        "label": "发送消息间隔(秒)",
        "type": "number",
        "default": 1.5,
        "min": 0,
        "max": 60,
        "step": 0.1,
        "full_width": False,
        "description": "识别到新增成员后，首次发送欢迎内容前会等待这个间隔；当同一条规则同时配置了文本和图片时，两次发送之间也会等待这个间隔。",
    },
]


def get_welcome_map(config):
    welcome_map: dict[str, dict[str, str]] = {}
    raw_room_welcomes = config.get("room_welcomes")

    if isinstance(raw_room_welcomes, list):
        for item in raw_room_welcomes:
            if not isinstance(item, dict):
                continue
            roomid = normalize_text(item.get("roomid") or item.get("wxid"))
            entry = normalize_welcome_entry(item)
            if roomid and (entry["content"] or entry["path"]):
                welcome_map[roomid] = entry
        if welcome_map:
            return welcome_map

    legacy_room_welcomes = raw_room_welcomes if isinstance(raw_room_welcomes, dict) else config.get("welcome_file")
    if not isinstance(legacy_room_welcomes, dict):
        return welcome_map

    for roomid, items in legacy_room_welcomes.items():
        normalized_roomid = normalize_text(roomid)
        entry = normalize_legacy_welcome_entry(items)
        if normalized_roomid and (entry["content"] or entry["path"]):
            welcome_map[normalized_roomid] = entry
    return welcome_map


def normalize_image_path(value):
    return str(value or "").strip().replace("\\", "/")


def normalize_welcome_entry(item):
    if isinstance(item, str):
        return {"content": str(item).strip(), "path": ""}
    if not isinstance(item, dict):
        return {"content": "", "path": ""}
    return {
        "content": str(item.get("content") or item.get("text") or "").strip(),
        "path": normalize_image_path(item.get("path") or item.get("image_path") or item.get("image") or ""),
    }


def normalize_legacy_welcome_entry(items):
    if isinstance(items, dict):
        return normalize_welcome_entry(items)
    if not isinstance(items, list):
        return normalize_welcome_entry(items)

    text_segments: list[str] = []
    image_path = ""
    for item in items:
        normalized_item = normalize_welcome_entry(item)
        if normalized_item["content"]:
            text_segments.append(normalized_item["content"])
        if normalized_item["path"] and not image_path:
            image_path = normalized_item["path"]
    return {
        "content": "\n".join(segment for segment in text_segments if segment).strip(),
        "path": image_path,
    }


def resolve_image_path(raw_path):
    normalized_path = normalize_image_path(raw_path)
    if not normalized_path:
        return None
    candidate = Path(normalized_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate


async def fetch_room_member_map(context, roomid, wxpid):
    members = await context.api.get_room_members(roomid, wxpid)
    return {str(member.get("username") or "").strip(): normalize_text(member.get("room_nick_name") or member.get("nick_name") or member.get("username") or "成员") for member in members if str(member.get("username") or "").strip()}


def extract_sysmsg_xml(content):
    text = str(content or "")
    start_index = text.find("<sysmsg")
    return text[start_index:] if start_index >= 0 else text


def extract_xml_tag_values(xml_text, tag_name):
    pattern = re.compile(
        rf"<{re.escape(str(tag_name))}(?:\s[^>]*)?>\s*(?:<!\[CDATA\[(.*?)\]\]>|([^<]*))\s*</{re.escape(str(tag_name))}>",
        re.I | re.S,
    )
    values: list[str] = []
    for match in pattern.finditer(str(xml_text or "")):
        value = normalize_text(match.group(1) or match.group(2) or "")
        if value:
            values.append(value)
    return values


def extract_xml_tag_block(xml_text, tag_name):
    match = re.search(rf"<{re.escape(str(tag_name))}(?:\s[^>]*)?>([\s\S]*?)</{re.escape(str(tag_name))}>", str(xml_text or ""), re.I)
    return match.group(1) if match else ""


def find_first_xml_tag_value(xml_text, tag_name):
    values = extract_xml_tag_values(xml_text, tag_name)
    return values[0] if values else ""


def inspect_enter_room_notice(content):
    normalized_content = normalize_text(content)
    xml_text = extract_sysmsg_xml(content)
    sysmsg_type = normalize_text(parse_xml_attributes(xml_text).get("type")).lower()
    delchatroommember_xml = extract_xml_tag_block(xml_text, "delchatroommember")
    link_xml = extract_xml_tag_block(delchatroommember_xml, "link")
    memberlist_xml = extract_xml_tag_block(link_xml, "memberlist")
    notice_text = (
        find_first_xml_tag_value(delchatroommember_xml, "plain")
        or find_first_xml_tag_value(delchatroommember_xml, "text")
        or normalized_content
    )
    return {
        "matched": bool(ENTER_ROOM_PATTERN.search(notice_text)),
        "notice_text": notice_text,
        "sysmsg_type": sysmsg_type,
        "scene": find_first_xml_tag_value(link_xml, "scene") or find_xml_tag_text(xml_text, ["delchatroommember", "link", "scene"]),
        "member_usernames": extract_xml_tag_values(memberlist_xml, "username") or extract_xml_tag_values(xml_text, "username"),
        "content_preview": normalized_content[:CONTENT_PREVIEW_LIMIT],
    }


def build_notice_log_payload(event, roomid, type_code, notice_meta):
    return {
        "roomid": roomid,
        "msgid": getattr(event, "normalized_msgid", "") or getattr(event, "msgid", ""),
        "wxpid": getattr(event, "normalized_wxpid", None),
        "type_code": type_code,
        "type_name": "sysmsg" if type_code == MESSAGE_TYPES.SYSMSG else "notice",
        "sysmsg_type": notice_meta.get("sysmsg_type", ""),
        "scene": notice_meta.get("scene", ""),
        "member_usernames": notice_meta.get("member_usernames", []),
        "content_preview": notice_meta.get("content_preview", ""),
    }


def build_members_from_usernames(usernames, latest_members_map, fallback_members_map=None):
    fallback_map = fallback_members_map if isinstance(fallback_members_map, dict) else {}
    latest_map = latest_members_map if isinstance(latest_members_map, dict) else {}
    unique_usernames: list[str] = []
    seen: set[str] = set()
    for username in usernames or []:
        normalized_username = normalize_text(username)
        if not normalized_username or normalized_username in seen:
            continue
        seen.add(normalized_username)
        unique_usernames.append(normalized_username)

    return [
        {
            "username": username,
            "nick_name": normalize_text(latest_map.get(username) or fallback_map.get(username) or username or "成员"),
        }
        for username in unique_usernames
    ]


async def warmup_room_members(context, wxpid):
    welcome_map = get_welcome_map(context.config)
    room_cache = context.state.namespace("room_members_cache")
    for roomid in welcome_map.keys():
        try:
            room_cache.set(roomid, await fetch_room_member_map(context, roomid, wxpid))
        except Exception as exc:
            context.logger.warn("预热群成员缓存失败", {"roomid": roomid, "error": str(exc)})


async def startup(context):
    await warmup_room_members(context, None)


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed"):
        await warmup_room_members(context, None)


async def handle_message(event, context):
    type_code = get_message_type(event)
    if type_code not in {MESSAGE_TYPES.NOTICE, MESSAGE_TYPES.SYSMSG}:
        return {"handled": False, "detail": "不是入群通知相关消息"}

    roomid = normalize_text(event.conversation_wxid)
    welcome_entry = get_welcome_map(context.config).get(roomid) or {}
    if not roomid or not roomid.endswith("@chatroom") or not (welcome_entry.get("content") or welcome_entry.get("path")):
        return {"handled": False, "detail": "当前群聊没有配置欢迎语"}

    content = str(event.normalized_content or getattr(event, "content", ""))
    notice_meta = inspect_enter_room_notice(content)
    log_payload = build_notice_log_payload(event, roomid, type_code, notice_meta)
    if not notice_meta["matched"]:
        context.logger.info("入群欢迎插件忽略了非入群通知消息", log_payload)
        return {"handled": False, "detail": "不是成员入群通知"}

    context.logger.info("入群欢迎插件命中成员入群通知", {**log_payload, "notice_text": notice_meta["notice_text"]})

    room_cache = context.state.namespace("room_members_cache")
    old_members = room_cache.get(roomid)
    if not isinstance(old_members, dict):
        old_members = {}

    if not old_members and not notice_meta["member_usernames"]:
        initialized_members = await fetch_room_member_map(context, roomid, event.normalized_wxpid)
        room_cache.set(roomid, initialized_members)
        context.logger.info("入群欢迎插件已初始化群成员缓存", {**log_payload, "cached_member_count": len(initialized_members)})
        return {"handled": False, "detail": "已初始化群成员缓存，等待下一次通知"}

    await sleep((NOTICE_DELAY_SECONDS if type_code == MESSAGE_TYPES.NOTICE else SYSMSG_DELAY_SECONDS) * 1000)
    new_members_map = await fetch_room_member_map(context, roomid, event.normalized_wxpid)
    room_cache.set(roomid, new_members_map)
    if notice_meta["member_usernames"]:
        new_members = build_members_from_usernames(notice_meta["member_usernames"], new_members_map, old_members)
        context.logger.info(
            "入群欢迎插件直接使用通知中的成员 wxid",
            {
                **log_payload,
                "cached_member_count": len(old_members),
                "latest_member_count": len(new_members_map),
                "new_member_source": "notice_memberlist",
                "resolved_new_members": new_members,
            },
        )
    else:
        new_members = [{"username": username, "nick_name": nickname} for username, nickname in new_members_map.items() if username not in old_members]
    if not new_members:
        context.logger.info("入群欢迎插件未识别到新增成员", {**log_payload, "cached_member_count": len(old_members), "latest_member_count": len(new_members_map)})
        return {"handled": False, "detail": "没有识别到新增成员"}

    context.logger.info(
        "入群欢迎插件识别到新增成员",
        {
            **log_payload,
            "cached_member_count": len(old_members),
            "latest_member_count": len(new_members_map),
            "new_member_source": "notice_memberlist" if notice_meta["member_usernames"] else "member_cache_diff",
            "new_members": new_members,
        },
    )

    interval_ms = float(context.config.get("message_interval_seconds", 1.5) or 0) * 1000
    sent_count = 0
    message_text = str(welcome_entry.get("content") or "").strip()
    context.logger.info(
        "入群欢迎插件准备发送欢迎内容",
        {
            **log_payload,
            "member_count": len(new_members),
            "has_text": bool(message_text),
            "has_image": bool(welcome_entry.get("path")),
            "interval_ms": interval_ms,
        },
    )
    if interval_ms > 0:
        context.logger.info("入群欢迎插件等待发送欢迎内容", {**log_payload, "member_count": len(new_members), "interval_ms": interval_ms})
        await sleep(interval_ms)
    if message_text:
        atlist = ""
        if "@{nick_name}" in message_text:
            message_text = message_text.replace("@{nick_name}", " ".join(f"@{member['nick_name']}\u2005" for member in new_members))
            atlist = ",".join(member["username"] for member in new_members)
        message_text = message_text.replace("{nick_name}", " ".join(member["nick_name"] for member in new_members))
        await context.api.send_text(wxid=roomid, content=message_text, atlist=atlist, wxpid=event.normalized_wxpid)
        sent_count += 1

    image_path = resolve_image_path(welcome_entry.get("path"))
    if image_path is not None:
        if image_path.exists():
            if sent_count and interval_ms > 0:
                await sleep(interval_ms)
            await context.api.send_image(wxid=roomid, path=str(image_path), wxpid=event.normalized_wxpid)
            sent_count += 1
        else:
            context.logger.warning("欢迎图片不存在，已跳过发送", {"roomid": roomid, "path": str(image_path)})

    if sent_count <= 0:
        return {"handled": False, "detail": "欢迎规则存在，但文本和图片均不可用"}

    context.logger.info("已发送入群欢迎语", {**log_payload, "new_members": new_members, "sent_count": sent_count})
    return {"handled": True, "detail": f"已向 {len(new_members)} 位新成员发送欢迎语", "data": {"roomid": roomid, "new_members": new_members}}

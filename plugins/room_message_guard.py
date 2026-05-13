from time import time

from ._plugin_sdk import MESSAGE_TYPES, find_xml_tag_text, get_message_type, normalize_text, random_between, sleep, unique_strings


name = "room_message_guard"
description = "按群聊规则限制消息类型，违规时提醒并可移出群聊"
event_filters = ["group"]

RULE_MODE_ALLOW = "allow_selected"
RULE_MODE_BLOCK = "block_selected"
PENDING_KICK_TTL_MS = 30_000
DEFAULT_WARNING_TEMPLATE = "当前群不允许发送这类消息，请遵守群规。"

MESSAGE_KIND_DEFINITIONS = [
    {"key": "text", "label": "文本", "codes": [MESSAGE_TYPES.TEXT]},
    {"key": "image", "label": "图片", "codes": [MESSAGE_TYPES.IMAGE]},
    {"key": "voice", "label": "语音", "codes": [34]},
    {"key": "video", "label": "视频", "codes": [MESSAGE_TYPES.VIDEO, 0x3E]},
    {"key": "emoji", "label": "表情", "codes": [47]},
    {"key": "attachment", "label": "名片/位置/链接/文件/公众号名片", "codes": [42, 48, 0x1100000031, 0x2A0000031, 0x500000031, MESSAGE_TYPES.FILE]},
    {"key": "channels", "label": "视频号/视频号卡片", "codes": [0x330000031, 0x3F0000031]},
    {"key": "mini_program", "label": "小程序", "codes": [0x210000031]},
    {"key": "merged", "label": "合并消息/聊天记录消息", "codes": [0x280000031, 0x1300000031]},
    {"key": "other", "label": "其他类型", "codes": []},
]

MESSAGE_KIND_LABELS = {item["key"]: item["label"] for item in MESSAGE_KIND_DEFINITIONS}
MESSAGE_KIND_OPTIONS = [{"label": item["label"], "value": item["key"]} for item in MESSAGE_KIND_DEFINITIONS]
EXACT_TYPE_CODE_TO_MESSAGE_KIND = {
    int(code): item["key"]
    for item in MESSAGE_KIND_DEFINITIONS
    for code in item["codes"]
}
APPMSG_SUBTYPE_TO_MESSAGE_KIND = {
    5: "attachment",
    6: "attachment",
    17: "attachment",
    19: "merged",
    33: "mini_program",
    40: "merged",
    42: "attachment",
    51: "channels",
    63: "channels",
}
IGNORED_TYPE_CODES = {
    MESSAGE_TYPES.ADDFRIEND,
    MESSAGE_TYPES.NOTICE,
    MESSAGE_TYPES.SYSMSG,
    0x33,
    0x34,
    0x35,
    0x3900000031,
    0x4A00000031,
    0x570000031,
    0x7D000000031,
}
IGNORED_APPMSG_SUBTYPES = {
    57,
    74,
    87,
    2000,
}
LEGACY_MESSAGE_KIND_ALIASES = {
    "card": ["attachment"],
    "location": ["attachment"],
    "file": ["attachment"],
    "xml": ["attachment", "channels", "mini_program", "merged", "other"],
    "unknown": ["other"],
}

config_schema = [
    {
        "key": "kick_after_warning",
        "label": "是否踢出群聊",
        "type": "checkbox",
        "default": True,
        "full_width": False,
        "description": "开启后会先发送群内提醒并 @ 违规成员，再等待 3 到 5 秒将其移出群聊。",
    },
    {
        "key": "warning_template",
        "label": "提示信息模版",
        "type": "text",
        "default": DEFAULT_WARNING_TEMPLATE,
        "placeholder": "支持 @{user_name} 占位符，例如：@{user_name} 本群仅允许发送指定类型消息",
        "description": "支持 @{user_name} 占位符；若未填写该占位符，插件会自动在消息前追加 @ 提示。",
    },
    {
        "key": "room_rules",
        "label": "群聊禁言规则",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["roomid", "mode", "message_types"],
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能保留一条禁言规则",
        "empty_text": "暂无群聊禁言规则，点击“新增”后为目标群聊设置消息类型限制。",
        "description": "每个群聊可单独设置规则模式。若选择“仅允许以下类型”，未勾选的类型都会被视为违规。群主和所有管理员默认不受该群规则限制。",
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
            },
            {
                "key": "mode",
                "label": "规则模式",
                "type": "select",
                "default": RULE_MODE_ALLOW,
                "required": True,
                "required_message": "规则模式不能为空",
                "options": [
                    {"label": "仅允许以下类型", "value": RULE_MODE_ALLOW},
                    {"label": "禁止以下类型", "value": RULE_MODE_BLOCK},
                ],
                "width": "compact",
                "editor_span": 3,
            },
            {
                "key": "message_types",
                "label": "消息类型",
                "type": "multi-checkbox",
                "default": [],
                "required": True,
                "required_message": "请至少选择一种消息类型",
                "options": MESSAGE_KIND_OPTIONS,
                "width": "wide",
                "editor_span": 12,
            },
        ],
    },
]


def is_truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return normalize_text(value).lower() in {"1", "true", "yes", "on", "y", "是"}


def normalize_rule_mode(value):
    normalized = normalize_text(value).lower()
    return normalized if normalized in {RULE_MODE_ALLOW, RULE_MODE_BLOCK} else RULE_MODE_ALLOW


def normalize_message_kinds(value):
    normalized_items: list[str] = []
    for item in unique_strings(value):
        normalized = normalize_text(item).lower()
        resolved_items = LEGACY_MESSAGE_KIND_ALIASES.get(normalized, [normalized])
        for resolved_item in resolved_items:
            if resolved_item in MESSAGE_KIND_LABELS and resolved_item not in normalized_items:
                normalized_items.append(resolved_item)
    return normalized_items


def normalize_room_rules(config):
    rules: dict[str, dict[str, object]] = {}
    raw_rules = config.get("room_rules") if isinstance(config, dict) else []
    for item in raw_rules if isinstance(raw_rules, list) else []:
        if not isinstance(item, dict):
            continue
        roomid = normalize_text(item.get("roomid") or item.get("wxid"))
        if not roomid:
            continue
        message_types = normalize_message_kinds(item.get("message_types") if item.get("message_types") is not None else item.get("types"))
        if not message_types:
            continue
        rules[roomid] = {
            "roomid": roomid,
            "mode": normalize_rule_mode(item.get("mode") or item.get("rule_mode")),
            "message_types": message_types,
        }
    return rules


def get_message_kind(type_code):
    if type_code is None:
        return "other"
    return EXACT_TYPE_CODE_TO_MESSAGE_KIND.get(int(type_code), "other")


def extract_appmsg_subtype(content):
    subtype_text = find_xml_tag_text(content, ["appmsg", "type"])
    if not subtype_text:
        return None
    try:
        return int(subtype_text)
    except (TypeError, ValueError):
        return None


def get_appmsg_subtype(type_code, content):
    if type_code is not None:
        try:
            normalized_type_code = int(type_code)
        except (TypeError, ValueError):
            normalized_type_code = None
        if normalized_type_code is not None and normalized_type_code > 0xFFFFFFFF and normalized_type_code & 0xFFFFFFFF == MESSAGE_TYPES.XML:
            return normalized_type_code >> 32
    return extract_appmsg_subtype(content)


def inspect_message_kind(event):
    type_code = get_message_type(event)
    if type_code is None:
        return {"type_code": None, "appmsg_subtype": None, "message_kind": "other", "ignored": True}

    content = getattr(event, "content", "") or getattr(event, "normalized_content", "")
    appmsg_subtype = get_appmsg_subtype(type_code, content)

    if int(type_code) in IGNORED_TYPE_CODES or appmsg_subtype in IGNORED_APPMSG_SUBTYPES:
        return {
            "type_code": int(type_code),
            "appmsg_subtype": appmsg_subtype,
            "message_kind": "",
            "ignored": True,
        }

    message_kind = EXACT_TYPE_CODE_TO_MESSAGE_KIND.get(int(type_code))
    if message_kind is None and appmsg_subtype is not None:
        message_kind = APPMSG_SUBTYPE_TO_MESSAGE_KIND.get(appmsg_subtype)
    return {
        "type_code": int(type_code),
        "appmsg_subtype": appmsg_subtype,
        "message_kind": message_kind or "other",
        "ignored": False,
    }


def describe_message_kind(type_key, type_code):
    if type_key in MESSAGE_KIND_LABELS:
        return MESSAGE_KIND_LABELS[type_key]
    return f"其他类型({hex(int(type_code))})" if type_code is not None else "其他类型"


def is_message_blocked(rule, message_kind):
    configured_types = set(rule.get("message_types") or [])
    if rule.get("mode") == RULE_MODE_BLOCK:
        return message_kind in configured_types
    return message_kind not in configured_types


def find_room_member(members, sender_wxid):
    normalized_sender_wxid = normalize_text(sender_wxid)
    if not normalized_sender_wxid:
        return None
    for member in members if isinstance(members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = normalize_text(member.get("username") or member.get("wxid"))
        if member_wxid == normalized_sender_wxid:
            return member
    return None


def is_default_whitelist_member(member):
    if not isinstance(member, dict):
        return False
    return is_truthy(member.get("is_owner")) or is_truthy(member.get("is_admin"))


async def can_current_account_remove_members(context, roomid, wxpid, self_wxid, log_payload=None):
    payload = dict(log_payload or {})
    normalized_self_wxid = normalize_text(self_wxid)
    if not normalized_self_wxid:
        context.logger.warning(
            "群聊禁言插件无法确认当前账号微信号，已跳过移除群成员",
            {**payload, "roomid": roomid, "wxpid": wxpid},
        )
        return False

    try:
        room_members = await context.api.get_room_members(roomid, wxpid)
    except Exception as exc:
        context.logger.warning(
            "群聊禁言插件移人前读取群成员失败，已跳过移除群成员",
            {**payload, "roomid": roomid, "self_wxid": normalized_self_wxid, "wxpid": wxpid, "error": str(exc)},
        )
        return False

    if not isinstance(room_members, list):
        context.logger.warning(
            "群聊禁言插件移人前读取群成员返回了非列表结果，已跳过移除群成员",
            {**payload, "roomid": roomid, "self_wxid": normalized_self_wxid, "wxpid": wxpid, "result_type": type(room_members).__name__},
        )
        return False

    self_member = find_room_member(room_members, normalized_self_wxid)
    if is_default_whitelist_member(self_member):
        return True

    context.logger.warning(
        "群聊禁言插件当前账号不是群主或管理员，已跳过移除群成员",
        {
            **payload,
            "roomid": roomid,
            "self_wxid": normalized_self_wxid,
            "wxpid": wxpid,
            "self_is_owner": is_truthy(self_member.get("is_owner")) if isinstance(self_member, dict) else False,
            "self_is_admin": is_truthy(self_member.get("is_admin")) if isinstance(self_member, dict) else False,
        },
    )
    return False


def get_active_pending_kick(pending_state, pending_key):
    pending = pending_state.get(pending_key)
    if not isinstance(pending, dict):
        return None
    try:
        created_at_ms = int(pending.get("created_at_ms") or 0)
    except (TypeError, ValueError):
        created_at_ms = 0
    now_ms = int(time() * 1000)
    if created_at_ms <= 0 or now_ms - created_at_ms > PENDING_KICK_TTL_MS:
        pending_state.delete(pending_key)
        return None
    return pending


async def resolve_self_wxid(context, wxpid):
    users = await context.api.get_logged_in_users()
    for item in users if isinstance(users, list) else []:
        try:
            if wxpid is None or int(item.get("wxpid") or item.get("pid") or -1) == int(wxpid):
                return normalize_text(item.get("wxid"))
        except (TypeError, ValueError):
            continue
    return ""


async def resolve_sender_name(event, context, roomid, sender_wxid, room_members=None):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        display_name = normalize_text(first_non_empty("room_sender_display_name", "sender_display_name"))
        if display_name and display_name != sender_wxid:
            return display_name

    members = room_members if isinstance(room_members, list) else await context.api.get_room_members(roomid, event.normalized_wxpid)
    for member in members if isinstance(members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = normalize_text(member.get("username") or member.get("wxid"))
        if member_wxid != sender_wxid:
            continue
        return normalize_text(member.get("room_nick_name") or member.get("nick_name") or member.get("remarks") or member_wxid) or sender_wxid

    return sender_wxid or "该成员"


def resolve_room_name(event, roomid):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        room_name = normalize_text(first_non_empty("conversation_display_name", "title_display"))
        if room_name and room_name != roomid:
            return room_name
    return roomid or "当前群聊"


def render_warning_text(template, sender_name, message_type_name, room_name):
    content = str(template or "").strip() or DEFAULT_WARNING_TEMPLATE
    mention_text = f"@{sender_name}\u2005"
    inserted_mention = False
    if "@{user_name}" in content:
        content = content.replace("@{user_name}", mention_text)
        inserted_mention = True
    content = content.replace("{user_name}", sender_name)
    content = content.replace("{message_type}", message_type_name)
    content = content.replace("{room_name}", room_name)
    content = content.strip()
    if not inserted_mention:
        content = f"{mention_text}{content}".strip()
    return content


def build_log_payload(event, roomid, sender_wxid, sender_name, rule, message_kind, type_code):
    appmsg_subtype = get_appmsg_subtype(type_code, getattr(event, "content", "") or event.normalized_content)
    return {
        "roomid": roomid,
        "sender_wxid": sender_wxid,
        "sender_name": sender_name,
        "wxpid": event.normalized_wxpid,
        "msgid": event.normalized_msgid,
        "message_kind": message_kind,
        "message_type": describe_message_kind(message_kind, type_code),
        "type_code": type_code,
        "appmsg_subtype": appmsg_subtype,
        "rule_mode": rule.get("mode"),
        "configured_types": [MESSAGE_KIND_LABELS.get(item, item) for item in rule.get("message_types") or []],
    }


async def handle_message(event, context):
    roomid = normalize_text(event.conversation_wxid)
    if not roomid or not roomid.endswith("@chatroom"):
        return {"handled": False, "detail": ""}

    room_rule = normalize_room_rules(context.config).get(roomid)
    if not room_rule:
        return {"handled": False, "detail": ""}

    message_meta = inspect_message_kind(event)
    type_code = message_meta.get("type_code")
    if message_meta.get("ignored"):
        return {"handled": False, "detail": ""}

    sender_wxid = normalize_text(event.sender_wxid)
    if not sender_wxid:
        return {"handled": False, "detail": ""}

    self_wxid = await resolve_self_wxid(context, event.normalized_wxpid)
    if self_wxid and sender_wxid == self_wxid:
        return {"handled": False, "detail": ""}

    try:
        room_members = await context.api.get_room_members(roomid, event.normalized_wxpid)
    except Exception as exc:
        context.logger.warning("群聊禁言插件读取群成员失败，已跳过本次校验", {"roomid": roomid, "sender_wxid": sender_wxid, "wxpid": event.normalized_wxpid, "error": str(exc)})
        return {"handled": False, "detail": ""}

    if not isinstance(room_members, list):
        context.logger.warning("群聊禁言插件读取群成员返回了非列表结果，已跳过本次校验", {"roomid": roomid, "sender_wxid": sender_wxid, "wxpid": event.normalized_wxpid, "result_type": type(room_members).__name__})
        return {"handled": False, "detail": ""}

    sender_member = find_room_member(room_members, sender_wxid)
    if is_default_whitelist_member(sender_member):
        return {"handled": False, "detail": ""}

    message_kind = str(message_meta.get("message_kind") or "other")
    if not is_message_blocked(room_rule, message_kind):
        return {"handled": False, "detail": ""}

    sender_name = await resolve_sender_name(event, context, roomid, sender_wxid, room_members)

    room_name = resolve_room_name(event, roomid)
    message_type_name = describe_message_kind(message_kind, type_code)
    warning_text = render_warning_text(context.config.get("warning_template"), sender_name, message_type_name, room_name)
    kick_after_warning = bool(context.config.get("kick_after_warning", True))
    log_payload = build_log_payload(event, roomid, sender_wxid, sender_name, room_rule, message_kind, type_code)

    pending_state = context.state.namespace("pending_kicks")
    pending_key = f"{roomid}::{sender_wxid}"
    if kick_after_warning and get_active_pending_kick(pending_state, pending_key):
        context.logger.info("群聊禁言插件检测到重复违规，成员仍在待移出队列中", log_payload)
        return {"handled": True, "detail": "该成员已在待移出队列中", "data": log_payload}

    if kick_after_warning:
        pending_state.set(
            pending_key,
            {
                "created_at_ms": int(time() * 1000),
                "msgid": event.normalized_msgid,
                "sender_wxid": sender_wxid,
                "roomid": roomid,
            },
        )

    try:
        await context.api.send_text(wxid=roomid, content=warning_text, atlist=sender_wxid, wxpid=event.normalized_wxpid)
    except Exception as exc:
        if kick_after_warning:
            pending_state.delete(pending_key)
        context.logger.error("群聊禁言插件发送提示信息失败", {**log_payload, "error": str(exc)})
        return {"handled": False, "detail": "发送违规提示失败", "data": {**log_payload, "error": str(exc)}}

    warning_count = context.state.increment("warning_count", 1)
    if not kick_after_warning:
        context.logger.info("群聊禁言插件已发送违规提示", {**log_payload, "warning_count": warning_count})
        return {
            "handled": True,
            "detail": f"已提醒 {sender_name} 不要发送 {message_type_name}",
            "data": {**log_payload, "action": "warned", "warning_count": warning_count},
        }

    delay_seconds = random_between(3, 5)
    await sleep(delay_seconds * 1000)

    removal_log_payload = {**log_payload, "warning_count": warning_count, "delay_seconds": delay_seconds}
    if not await can_current_account_remove_members(
        context,
        roomid,
        event.normalized_wxpid,
        self_wxid,
        removal_log_payload,
    ):
        pending_state.delete(pending_key)
        return {
            "handled": True,
            "detail": "已发送提示，但当前账号没有群管理权限，未移出群成员",
            "data": {**removal_log_payload, "action": "warned_only_no_permission"},
        }

    try:
        await context.api.delete_room_members(roomid=roomid, wxids=sender_wxid, wxpid=event.normalized_wxpid)
    except Exception as exc:
        pending_state.delete(pending_key)
        context.logger.error(
            "群聊禁言插件移出违规成员失败",
            {**removal_log_payload, "error": str(exc)},
        )
        return {
            "handled": True,
            "detail": "已发送提示，但移出群成员失败",
            "data": {**removal_log_payload, "action": "warned_only", "error": str(exc)},
        }
    finally:
        pending_state.delete(pending_key)

    kick_count = context.state.increment("kick_count", 1)
    context.logger.info(
        "群聊禁言插件已提醒并移出违规成员",
        {**log_payload, "warning_count": warning_count, "kick_count": kick_count, "delay_seconds": delay_seconds},
    )
    return {
        "handled": True,
        "detail": f"已提醒并移出发送 {message_type_name} 的成员 {sender_name}",
        "data": {
            **log_payload,
            "action": "warned_and_removed",
            "warning_count": warning_count,
            "kick_count": kick_count,
            "delay_seconds": delay_seconds,
        },
    }
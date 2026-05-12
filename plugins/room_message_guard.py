from time import time

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text, random_between, sleep, unique_strings


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
    {"key": "emoji", "label": "表情/标签消息", "codes": [47]},
    {"key": "voice", "label": "语音", "codes": [34]},
    {"key": "video", "label": "视频", "codes": [MESSAGE_TYPES.VIDEO]},
    {"key": "file", "label": "文件", "codes": [MESSAGE_TYPES.FILE]},
    {"key": "card", "label": "名片", "codes": [42]},
    {"key": "location", "label": "位置", "codes": [48]},
    {"key": "xml", "label": "链接/小程序/引用/分享", "codes": [MESSAGE_TYPES.XML]},
    {"key": "unknown", "label": "其他未知类型", "codes": []},
]

MESSAGE_KIND_LABELS = {item["key"]: item["label"] for item in MESSAGE_KIND_DEFINITIONS}
MESSAGE_KIND_OPTIONS = [{"label": item["label"], "value": item["key"]} for item in MESSAGE_KIND_DEFINITIONS]
TYPE_CODE_TO_MESSAGE_KIND = {
    int(code): item["key"]
    for item in MESSAGE_KIND_DEFINITIONS
    for code in item["codes"]
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
        "meaningful_keys": ["roomid", "mode", "message_types", "whitelist_members"],
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能保留一条禁言规则",
        "empty_text": "暂无群聊禁言规则，点击“新增”后为目标群聊设置消息类型限制。",
        "description": "每个群聊可单独设置规则模式。若选择“仅允许以下类型”，未勾选的类型都会被视为违规。白名单成员不受该群规则限制。",
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
            },
            {
                "key": "whitelist_members",
                "label": "白名单成员",
                "type": "string-list",
                "rows": 3,
                "placeholder": "每行一个成员 wxid、群昵称或展示名",
                "width": "wide",
            },
        ],
    },
]


def normalize_rule_mode(value):
    normalized = normalize_text(value).lower()
    return normalized if normalized in {RULE_MODE_ALLOW, RULE_MODE_BLOCK} else RULE_MODE_ALLOW


def normalize_message_kinds(value):
    normalized_items: list[str] = []
    for item in unique_strings(value):
        normalized = normalize_text(item).lower()
        if normalized in MESSAGE_KIND_LABELS and normalized not in normalized_items:
            normalized_items.append(normalized)
    return normalized_items


def normalize_whitelist_members(value):
    normalized_items: list[str] = []
    for item in unique_strings(value):
        normalized = normalize_text(item)
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
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
            "whitelist_members": normalize_whitelist_members(
                item.get("whitelist_members") if item.get("whitelist_members") is not None else item.get("whitelist")
            ),
        }
    return rules


def get_message_kind(type_code):
    if type_code is None:
        return "unknown"
    return TYPE_CODE_TO_MESSAGE_KIND.get(int(type_code), "unknown")


def describe_message_kind(type_key, type_code):
    if type_key in MESSAGE_KIND_LABELS:
        return MESSAGE_KIND_LABELS[type_key]
    return f"未知类型({type_code})" if type_code is not None else "未知类型"


def is_message_blocked(rule, message_kind):
    configured_types = set(rule.get("message_types") or [])
    if rule.get("mode") == RULE_MODE_BLOCK:
        return message_kind in configured_types
    return message_kind not in configured_types


def get_event_display_candidate(event, field_name):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        return normalize_text(first_non_empty(field_name))
    return normalize_text(getattr(event, field_name, ""))


def build_sender_whitelist_candidates(event, sender_wxid, sender_name=""):
    return unique_strings(
        [
            normalize_text(sender_wxid),
            normalize_text(sender_name),
            get_event_display_candidate(event, "room_sender_display_name"),
            get_event_display_candidate(event, "sender_display_name"),
            get_event_display_candidate(event, "room_sender"),
            get_event_display_candidate(event, "sender"),
        ]
    )


def is_sender_whitelisted(rule, sender_identifiers):
    whitelist_members = {normalize_text(item) for item in rule.get("whitelist_members") or [] if normalize_text(item)}
    if not whitelist_members:
        return False
    return bool(whitelist_members & {normalize_text(item) for item in sender_identifiers if normalize_text(item)})


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


async def resolve_sender_name(event, context, roomid, sender_wxid):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        display_name = normalize_text(first_non_empty("room_sender_display_name", "sender_display_name"))
        if display_name and display_name != sender_wxid:
            return display_name

    members = await context.api.get_room_members(roomid, event.normalized_wxpid)
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
    return {
        "roomid": roomid,
        "sender_wxid": sender_wxid,
        "sender_name": sender_name,
        "wxpid": event.normalized_wxpid,
        "msgid": event.normalized_msgid,
        "message_kind": message_kind,
        "message_type": describe_message_kind(message_kind, type_code),
        "type_code": type_code,
        "rule_mode": rule.get("mode"),
        "configured_types": [MESSAGE_KIND_LABELS.get(item, item) for item in rule.get("message_types") or []],
        "whitelist_members": rule.get("whitelist_members") or [],
    }


async def handle_message(event, context):
    roomid = normalize_text(event.conversation_wxid)
    if not roomid or not roomid.endswith("@chatroom"):
        return {"handled": False, "detail": "不是群聊消息"}

    room_rule = normalize_room_rules(context.config).get(roomid)
    if not room_rule:
        return {"handled": False, "detail": "当前群聊没有配置禁言规则"}

    type_code = get_message_type(event)
    if type_code in {MESSAGE_TYPES.NOTICE, MESSAGE_TYPES.SYSMSG, MESSAGE_TYPES.ADDFRIEND}:
        return {"handled": False, "detail": "忽略通知或系统消息"}
    if type_code is None:
        return {"handled": False, "detail": "无法识别当前消息类型"}

    sender_wxid = normalize_text(event.sender_wxid)
    if not sender_wxid:
        return {"handled": False, "detail": "当前消息缺少发送者 wxid"}

    self_wxid = await resolve_self_wxid(context, event.normalized_wxpid)
    if self_wxid and sender_wxid == self_wxid:
        return {"handled": False, "detail": "忽略当前账号自己发送的群消息"}

    whitelist_candidates = build_sender_whitelist_candidates(event, sender_wxid)
    if is_sender_whitelisted(room_rule, whitelist_candidates):
        context.logger.info(
            "群聊禁言插件白名单成员已放行",
            {
                "roomid": roomid,
                "sender_wxid": sender_wxid,
                "sender_identifiers": whitelist_candidates,
                "whitelist_members": room_rule.get("whitelist_members") or [],
            },
        )
        return {"handled": False, "detail": "当前发送者在白名单中"}

    message_kind = get_message_kind(type_code)
    if not is_message_blocked(room_rule, message_kind):
        return {"handled": False, "detail": "当前消息类型允许发送"}

    sender_name = await resolve_sender_name(event, context, roomid, sender_wxid)
    if is_sender_whitelisted(room_rule, build_sender_whitelist_candidates(event, sender_wxid, sender_name)):
        context.logger.info(
            "群聊禁言插件白名单成员已放行",
            {
                "roomid": roomid,
                "sender_wxid": sender_wxid,
                "sender_name": sender_name,
                "whitelist_members": room_rule.get("whitelist_members") or [],
            },
        )
        return {"handled": False, "detail": "当前发送者在白名单中"}

    room_name = resolve_room_name(event, roomid)
    message_type_name = describe_message_kind(message_kind, type_code)
    warning_text = render_warning_text(context.config.get("warning_template"), sender_name, message_type_name, room_name)
    kick_after_warning = bool(context.config.get("kick_after_warning", True))
    log_payload = build_log_payload(event, roomid, sender_wxid, sender_name, room_rule, message_kind, type_code)

    pending_state = context.state.namespace("pending_kicks")
    pending_key = f"{roomid}::{sender_wxid}"
    if kick_after_warning and get_active_pending_kick(pending_state, pending_key):
        context.logger.info("群聊禁言插件忽略重复违规消息，成员已在待移出队列中", log_payload)
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

    try:
        await context.api.delete_room_members(roomid=roomid, wxids=sender_wxid, wxpid=event.normalized_wxpid)
    except Exception as exc:
        pending_state.delete(pending_key)
        context.logger.error(
            "群聊禁言插件移出违规成员失败",
            {**log_payload, "warning_count": warning_count, "delay_seconds": delay_seconds, "error": str(exc)},
        )
        return {
            "handled": True,
            "detail": "已发送提示，但移出群成员失败",
            "data": {**log_payload, "action": "warned_only", "warning_count": warning_count, "delay_seconds": delay_seconds, "error": str(exc)},
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
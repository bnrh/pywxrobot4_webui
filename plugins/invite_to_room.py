from time import time

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text, parse_xml_attributes, random_between, sleep, is_truthy


INVITE_DELAY_MIN_SECONDS = 3
INVITE_DELAY_MAX_SECONDS = 10


name = "invite_to_room"
description = "根据好友请求验证词或文本关键词自动邀请好友进群"
event_filters = ["friend_request", "notice", "text"]
config_schema = [
    {
        "key": "keyword_rooms",
        "label": "关键词进群规则",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["roomid", "keyword"],
        "empty_text": "暂无已保存规则，点击“新增”填写后，再点当前行的“保存”。",
        "description": "每行配置一个群聊关键词规则；同一群聊可配置多行关键词。好友申请内容或好友私聊文本命中规则后，会邀请好友进群。",
        "columns": [
            {"key": "roomid", "label": "群聊", "type": "select", "searchable": True, "options_source": "room_options", "empty_option_label": "", "placeholder": "输入群名称或 wxid 搜索", "required": True, "required_message": "群聊不能为空", "width": "wide"},
            {"key": "keyword", "label": "关键词", "type": "text", "placeholder": "例如 视频号", "required": True, "required_message": "关键词不能为空", "width": "compact"},
            {"key": "full_match", "label": "是否全匹配", "type": "checkbox", "default": False, "width": "compact"},
        ],
    },
    {"key": "cooldown_seconds", "label": "重复邀请冷却秒数", "type": "number", "default": 600, "min": 0, "max": 86400, "step": 1, "full_width": False, "description": "设置为 0 表示禁用重复邀请冷却。"},
]




def append_keyword_room_rule(rules, seen_rules, roomid, keyword, full_match=False):
    normalized_roomid = normalize_text(roomid)
    normalized_keyword = normalize_text(keyword)
    normalized_full_match = is_truthy(full_match)
    rule_key = (normalized_roomid, normalized_keyword, normalized_full_match)
    if not normalized_roomid or not normalized_keyword or rule_key in seen_rules:
        return
    seen_rules.add(rule_key)
    rules.append({"roomid": normalized_roomid, "keyword": normalized_keyword, "full_match": normalized_full_match})


def resolve_keyword_room_pairs(config):
    pairs = []
    seen_rules = set()
    keyword_rooms = config.get("keyword_rooms")
    if isinstance(keyword_rooms, list):
        for item in keyword_rooms:
            if not isinstance(item, dict):
                continue
            append_keyword_room_rule(pairs, seen_rules, item.get("roomid"), item.get("keyword"), item.get("full_match"))
    elif isinstance(keyword_rooms, dict):
        for keyword, roomid in keyword_rooms.items():
            append_keyword_room_rule(pairs, seen_rules, roomid, keyword, False)
    keywords = config.get("keywords")
    if isinstance(keywords, dict):
        for roomid, keyword_values in keywords.items():
            for keyword in [normalize_text(item) for item in str(keyword_values or "").replace("，", ",").replace("\n", ",").split(",") if normalize_text(item)]:
                append_keyword_room_rule(pairs, seen_rules, roomid, keyword, False)
    return pairs


def find_keyword_room(pairs, content):
    normalized_content = normalize_text(content)
    if not normalized_content:
        return None
    for item in pairs:
        if normalized_content == item["keyword"] if item.get("full_match") else item["keyword"] in normalized_content:
            return item
    return None


async def invite_to_room(friend_wxid, roomid, keyword, context, event):
    invite_records = context.state.namespace("invite_records")
    record_key = f"{roomid}:{friend_wxid}"
    cooldown_seconds = max(0, int(float(context.config.get("cooldown_seconds", 600) or 0)))
    last_invite_at = int(invite_records.get(record_key, 0) or 0)
    now = int(time())
    if cooldown_seconds > 0 and last_invite_at and now - last_invite_at < cooldown_seconds:
        await context.api.send_text(wxid=friend_wxid, content=f"你已被邀请进群({keyword})，请勿重复发送", wxpid=event.normalized_wxpid)
        return {"handled": True, "detail": f"好友 {friend_wxid} 仍处于拉群冷却期"}

    members = await context.api.get_room_members(roomid, event.normalized_wxpid)
    if any(normalize_text(member.get("username")) == friend_wxid for member in members if isinstance(member, dict)):
        await context.api.send_text(wxid=friend_wxid, content=f"你已是 {keyword} 中的成员，无需重复邀请", wxpid=event.normalized_wxpid)
        return {"handled": True, "detail": f"好友 {friend_wxid} 已经在群 {roomid} 中"}

    await sleep(random_between(INVITE_DELAY_MIN_SECONDS, INVITE_DELAY_MAX_SECONDS) * 1000)
    await context.api.invite_room_members(roomid=roomid, wxids=[friend_wxid], wxpid=event.normalized_wxpid)
    invite_records.set(record_key, now)
    context.logger.info("已邀请好友进群", {"friend_wxid": friend_wxid, "roomid": roomid, "keyword": keyword})
    return {"handled": True, "detail": f"已邀请 {friend_wxid} 加入 {roomid}", "data": {"friend_wxid": friend_wxid, "roomid": roomid, "keyword": keyword}}


async def handle_message(event, context):
    type_code = get_message_type(event)
    keyword_room_pairs = resolve_keyword_room_pairs(context.config)
    if not keyword_room_pairs:
        return {"handled": False, "detail": ""}

    pending_invites = context.state.namespace("pending_invites")
    if type_code == MESSAGE_TYPES.ADDFRIEND:
        payload = parse_xml_attributes(event.normalized_content or getattr(event, "content", ""))
        verification = normalize_text(payload.get("content"))
        friend_wxid = normalize_text(payload.get("fromusername"))
        nickname = normalize_text(payload.get("fromnickname"))
        if not friend_wxid or not verification or verification == f"我是{nickname}":
            return {"handled": False, "detail": ""}
        matched = find_keyword_room(keyword_room_pairs, verification)
        if not matched:
            return {"handled": False, "detail": ""}
        if pending_invites.has(friend_wxid):
            return {"handled": False, "detail": f"好友请求仍在处理中: {friend_wxid}"}
        pending_invites.set(friend_wxid, {"verification": verification, "roomid": matched["roomid"], "keyword": matched["keyword"], "full_match": bool(matched.get("full_match"))})
        return {"handled": False, "detail": f"已记录好友请求进群规则: {matched['keyword']} -> {matched['roomid']}"}

    if type_code == MESSAGE_TYPES.NOTICE:
        notice_text = normalize_text(event.normalized_content or getattr(event, "content", ""))
        if "现在可以开始聊天了" not in notice_text:
            return {"handled": False, "detail": ""}
        friend_wxid = normalize_text(getattr(event, "sender", "") or event.sender_wxid or "")
        pending = pending_invites.get(friend_wxid)
        if not pending:
            return {"handled": False, "detail": ""}
        pending_invites.delete(friend_wxid)
        matched = pending if pending.get("roomid") and pending.get("keyword") else find_keyword_room(keyword_room_pairs, pending.get("verification"))
        if not matched:
            return {"handled": False, "detail": ""}
        return await invite_to_room(friend_wxid, matched["roomid"], matched["keyword"], context, event)

    if type_code == MESSAGE_TYPES.TEXT and not event.is_group_message:
        content = normalize_text(event.normalized_content or getattr(event, "content", ""))
        matched = find_keyword_room(keyword_room_pairs, content)
        if not matched:
            return {"handled": False, "detail": ""}
        friend_wxid = normalize_text(event.sender_wxid or getattr(event, "sender", "") or event.conversation_wxid)
        if not friend_wxid:
            return {"handled": False, "detail": "无法确定当前好友 wxid"}
        return await invite_to_room(friend_wxid, matched["roomid"], matched["keyword"], context, event)

    return {"handled": False, "detail": ""}

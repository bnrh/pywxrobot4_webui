from datetime import datetime

from ._plugin_sdk import MESSAGE_TYPES, build_event_payload, get_message_type, normalize_text, post_json_request, to_string_set


name = "openclaw_channel"
description = "监听指定群聊文本消息并转发到外部 Webhook"
event_filters = ["text"]
scope_targets = ["rooms"]
config_schema = [
    {
        "key": "chatroom_wxid",
        "label": "目标群ID",
        "type": "text",
        "default": "",
        "description": "仅转发这个群聊里的文本消息。",
    },
    {
        "key": "webhook_url",
        "label": "Webhook 地址",
        "type": "url",
        "default": "",
        "description": "收到符合条件的消息后，POST 到该地址。",
    },
    {
        "key": "member_whitelist",
        "label": "成员白名单",
        "type": "string-list",
        "default": [],
        "description": "每行一个群成员 wxid；留空表示群内所有成员都转发。",
    },
]


def strip_room_sender_prefix(content, room_sender):
    normalized_content = str(content or "")
    if not room_sender:
        return normalized_content
    prefixes = [f"{room_sender}:", f"{room_sender}：", f"{room_sender}\n", f"{room_sender}:\n", f"{room_sender}：\n"]
    for prefix in prefixes:
        if normalized_content.startswith(prefix):
            return normalized_content[len(prefix):].strip()
    return normalized_content


async def handle_message(event, context):
    if get_message_type(event) != MESSAGE_TYPES.TEXT:
        return {"handled": False, "detail": ""}

    target_roomid = normalize_text(context.config.get("chatroom_wxid") or "")
    webhook_url = normalize_text(context.config.get("webhook_url") or "")
    if not target_roomid or not webhook_url:
        return {"handled": False, "detail": ""}
    if normalize_text(event.conversation_wxid) != target_roomid:
        return {"handled": False, "detail": ""}

    room_sender = normalize_text(getattr(event, "room_sender", "") or event.sender_wxid or "")
    whitelist = to_string_set(context.config.get("member_whitelist"))
    if whitelist and room_sender not in whitelist:
        return {"handled": False, "detail": ""}

    payload = build_event_payload(event)
    payload.update(
        {
            "forwarded_at": datetime.now().astimezone().isoformat(),
            "content": strip_room_sender_prefix(getattr(event, "content", "") or event.normalized_content, room_sender),
            "normalized_content": strip_room_sender_prefix(event.normalized_content or getattr(event, "content", ""), room_sender),
        }
    )
    response_status, response_text = await post_json_request(webhook_url, payload)

    context.logger.info(
        "已将群消息转发到 Webhook",
        {
            "roomid": target_roomid,
            "room_sender": room_sender,
            "webhook_url": webhook_url,
            "response_status": response_status,
        },
    )
    return {
        "handled": True,
        "detail": f"已将群消息转发到 {webhook_url}",
        "data": {
            "roomid": target_roomid,
            "room_sender": room_sender,
            "webhook_url": webhook_url,
            "response_status": response_status,
            "response_text": response_text[:200],
        },
    }

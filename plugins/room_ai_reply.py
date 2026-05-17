from ai_assistant import run_openai_compatible_chat_completion

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text


name = "room_ai_reply"
description = "监听指定群聊文本消息并调用 OpenAI-compatible 大模型自动回复"
event_filters = ["text"]

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_SYSTEM_PROMPT = (
    "你是微信群聊助手。"
    "请直接回复用户刚发出的那条消息，保持自然、简洁、有帮助。"
    "除非用户明确要求，否则不要使用 Markdown，不要自称 AI，也不要添加多余前缀。"
)

config_schema = [
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
        "description": "仅回复这个群聊中的文本消息。",
    },
    {
        "key": "base_url",
        "label": "大模型 Base URL",
        "type": "url",
        "default": DEFAULT_BASE_URL,
        "placeholder": "https://api.openai.com/v1",
        "description": "需要兼容 OpenAI Chat Completions 与 /models 接口。",
    },
    {
        "key": "api_key",
        "label": "大模型 API Key",
        "type": "password",
        "default": "",
        "placeholder": "输入可用的 API Key",
        "description": "填写后插件才会实际调用大模型。",
    },
    {
        "key": "model",
        "label": "模型",
        "type": "text",
        "options_source": "model_options",
        "options_loader": "openai_compatible",
        "manual_fetch_options": True,
        "fetch_options_button": True,
        "fetch_options_button_label": "获取模型列表",
        "fetch_options_select_placeholder": "从已获取的模型列表中选择",
        "base_url_key": "base_url",
        "api_key_key": "api_key",
        "placeholder": "可手动输入模型名，或点击右侧按钮获取列表后选择",
        "required": True,
        "required_message": "模型不能为空",
        "description": "支持手动输入模型名；也可点击右侧按钮，根据当前 Base URL 和 API Key 获取模型列表。",
    },
]


def strip_room_sender_prefix(content, room_sender):
    normalized_content = str(content or "")
    normalized_sender = normalize_text(room_sender)
    if not normalized_sender:
        return normalized_content.strip()

    prefixes = [
        f"{normalized_sender}:",
        f"{normalized_sender}：",
        f"{normalized_sender}\n",
        f"{normalized_sender}:\n",
        f"{normalized_sender}：\n",
    ]
    for prefix in prefixes:
        if normalized_content.startswith(prefix):
            return normalized_content[len(prefix):].strip()
    return normalized_content.strip()


def resolve_sender_name(event):
    for candidate in [
        getattr(event, "room_sender_display_name", ""),
        getattr(event, "sender_display_name", ""),
        getattr(event, "room_sender", ""),
        getattr(event, "sender_wxid", ""),
    ]:
        text = str(candidate or "").strip()
        if text:
            return text
    return "群成员"


def resolve_room_name(event, roomid):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        room_name = str(first_non_empty("conversation_display_name", "title_display") or "").strip()
        if room_name and room_name != roomid:
            return room_name
    return roomid or "当前群聊"


def build_model_prompt(event, roomid, message_text):
    sender_name = resolve_sender_name(event)
    room_name = resolve_room_name(event, roomid)
    return (
        f"群聊：{room_name}\n"
        f"发送者：{sender_name}\n"
        f"消息内容：{message_text}\n\n"
        "请直接给出适合发回群聊的回复。"
    )


async def handle_message(event, context):
    if get_message_type(event) != MESSAGE_TYPES.TEXT:
        return {"handled": False, "detail": ""}

    target_roomid = normalize_text(context.config.get("roomid") or "")
    roomid = normalize_text(event.conversation_wxid or "")
    if not target_roomid or roomid != target_roomid:
        return {"handled": False, "detail": ""}

    base_url = str(context.config.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    api_key = str(context.config.get("api_key") or "").strip()
    model = str(context.config.get("model") or "").strip()
    if not api_key or not model:
        return {"handled": False, "detail": ""}

    raw_content = getattr(event, "content", "") or getattr(event, "normalized_content", "") or ""
    room_sender = getattr(event, "room_sender", "") or getattr(event, "sender_wxid", "") or ""
    message_text = strip_room_sender_prefix(raw_content, room_sender)
    if not message_text:
        return {"handled": False, "detail": ""}

    try:
        ai_result = await run_openai_compatible_chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": build_model_prompt(event, roomid, message_text)}],
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            temperature=0.4,
        )
    except Exception as exc:
        context.logger.error(
            "群聊 AI 回复调用失败",
            {
                "roomid": roomid,
                "model": model,
                "sender": resolve_sender_name(event),
                "error": str(exc),
            },
        )
        return {
            "handled": False,
            "detail": f"群聊 AI 回复调用失败: {exc}",
            "data": {"roomid": roomid, "model": model, "error": str(exc)},
        }

    reply_text = str(ai_result.get("content") or "").strip()
    if not reply_text:
        return {"handled": False, "detail": "模型未返回可发送的回复"}

    try:
        await context.api.send_text(wxid=roomid, content=reply_text, wxpid=event.normalized_wxpid)
    except Exception as exc:
        context.logger.error(
            "群聊 AI 回复发送失败",
            {
                "roomid": roomid,
                "model": model,
                "sender": resolve_sender_name(event),
                "error": str(exc),
            },
        )
        return {
            "handled": False,
            "detail": f"群聊 AI 回复发送失败: {exc}",
            "data": {"roomid": roomid, "model": model, "error": str(exc)},
        }

    context.logger.info(
        "已发送群聊 AI 回复",
        {
            "roomid": roomid,
            "model": model,
            "sender": resolve_sender_name(event),
            "message_length": len(message_text),
            "reply_length": len(reply_text),
        },
    )
    return {
        "handled": True,
        "detail": f"已对群聊 {roomid} 的文本消息发送 AI 回复",
        "data": {
            "roomid": roomid,
            "model": model,
            "sender": resolve_sender_name(event),
            "message": message_text,
            "reply": reply_text,
        },
    }
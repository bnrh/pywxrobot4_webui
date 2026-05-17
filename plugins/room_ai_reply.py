from ai_assistant import run_openai_compatible_chat_completion

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text


name = "room_ai_reply"
description = "按群聊配置 OpenAI-compatible AI 助手，自动回复群文本消息"
event_filters = ["text"]

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_SYSTEM_PROMPT = (
    "你是微信群聊助手。"
    "请直接回复用户刚发出的那条消息，保持自然、简洁、有帮助。"
    "除非用户明确要求，否则不要使用 Markdown，不要自称 AI，也不要添加多余前缀。"
)

config_schema = [
    {
        "key": "room_configs",
        "aliases": ["roomid", "wxid", "base_url", "api_key", "model", "system_prompt", "prompt"],
        "label": "群聊 AI 助手",
        "type": "object-list",
        "default": [],
        "meaningful_keys": ["roomid", "base_url", "api_key", "model", "system_prompt"],
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能保留一个 AI 助手配置",
        "empty_text": "暂无群聊 AI 助手配置，点击“新增”后为目标群聊单独设置模型、Key 和提示词。",
        "description": "每个群聊可单独配置一个 AI 助手，包括 Base URL、API Key、模型和系统提示词。模型支持手动填写，也可点击按钮获取模型列表。",
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
                "key": "base_url",
                "label": "大模型 Base URL",
                "type": "url",
                "default": DEFAULT_BASE_URL,
                "placeholder": "https://api.openai.com/v1",
                "width": "wide",
            },
            {
                "key": "api_key",
                "label": "大模型 API Key",
                "type": "password",
                "default": "",
                "placeholder": "输入可用的 API Key",
                "required": True,
                "required_message": "API Key 不能为空",
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
                "description": "支持手动输入模型名，也可根据当前 Base URL 和 API Key 获取模型列表。",
                "width": "wide",
            },
            {
                "key": "system_prompt",
                "label": "系统提示词",
                "type": "textarea",
                "rows": 5,
                "default": DEFAULT_SYSTEM_PROMPT,
                "placeholder": "例如：你是这个群的售后助手，回答要礼貌、简洁，并优先给出可执行步骤",
                "description": "每个群聊都可以自定义 AI 助手提示词；留空时会使用默认提示词。",
                "width": "wide",
            },
        ],
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


def normalize_room_ai_entry(item):
    if not isinstance(item, dict):
        return None

    roomid = normalize_text(item.get("roomid") or item.get("wxid"))
    if not roomid:
        return None

    return {
        "roomid": roomid,
        "base_url": str(item.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        "api_key": str(item.get("api_key") or "").strip(),
        "model": str(item.get("model") or "").strip(),
        "system_prompt": str(item.get("system_prompt") or item.get("prompt") or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT,
    }


def build_legacy_room_ai_entry(config):
    if not isinstance(config, dict):
        return None
    return normalize_room_ai_entry(
        {
            "roomid": config.get("roomid") or config.get("wxid"),
            "base_url": config.get("base_url"),
            "api_key": config.get("api_key"),
            "model": config.get("model"),
            "system_prompt": config.get("system_prompt") or config.get("prompt"),
        }
    )


def get_room_config_map(config):
    room_config_map = {}
    raw_room_configs = config.get("room_configs") if isinstance(config, dict) else []

    if isinstance(raw_room_configs, list):
        for item in raw_room_configs:
            entry = normalize_room_ai_entry(item)
            if entry is not None:
                room_config_map[entry["roomid"]] = entry
        if room_config_map:
            return room_config_map

    legacy_entry = build_legacy_room_ai_entry(config)
    if legacy_entry is not None:
        room_config_map[legacy_entry["roomid"]] = legacy_entry
    return room_config_map


async def handle_message(event, context):
    if get_message_type(event) != MESSAGE_TYPES.TEXT:
        return {"handled": False, "detail": ""}

    roomid = normalize_text(event.conversation_wxid or "")
    room_config = get_room_config_map(context.config).get(roomid)
    if room_config is None:
        return {"handled": False, "detail": ""}

    base_url = room_config["base_url"]
    api_key = room_config["api_key"]
    model = room_config["model"]
    system_prompt = room_config["system_prompt"] or DEFAULT_SYSTEM_PROMPT
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
            system_prompt=system_prompt,
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
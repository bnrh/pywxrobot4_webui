from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text


name = "example_plugin"
description = "收到触发词后执行示例动作"
event_filters = ["text"]
config_schema = [
    {
        "key": "trigger",
        "label": "触发词",
        "type": "text",
        "default": "ping",
        "required": True,
        "required_message": "触发词不能为空",
    },
    {
        "key": "reply_text",
        "label": "回复内容",
        "type": "textarea",
        "rows": 3,
        "default": "pong",
    },
]


async def startup(context):
    context.logger.info("插件启动", {"plugin": context.plugin_name})


async def handle_message(event, context):
    type_code = get_message_type(event)
    if type_code != MESSAGE_TYPES.TEXT:
        return {"handled": False, "detail": "不是文本消息"}

    trigger = normalize_text(context.config.get("trigger") or "ping")
    content = normalize_text(event.normalized_content)
    if not trigger or content != trigger:
        return {"handled": False, "detail": "未命中触发词"}

    reply_text = str(context.config.get("reply_text") or "pong").strip()
    if not reply_text:
        return {"handled": False, "detail": "回复内容为空"}

    total = context.state.increment("handled_count", 1)
    await context.api.send_text(
        wxid=event.conversation_wxid,
        content=reply_text,
        wxpid=event.normalized_wxpid,
    )
    context.logger.info("插件执行完成", {"conversation": event.conversation_wxid, "total": total})
    return {"handled": True, "detail": f"已处理 {total} 次"}


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed"):
        context.logger.warning("插件已热重载", hot_reload)
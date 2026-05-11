from ._plugin_sdk import normalize_text


name = "auto_download_image"
description = "收到图片消息时自动调用 /cdn/image 下载原图"
event_filters = ["image"]
scope_targets = ["rooms", "friend_labels"]
config_schema = [
    {
        "key": "flag",
        "label": "图片下载类型",
        "type": "select",
        "default": 3,
        "full_width": False,
        "description": "选择下载缩略图、压缩图还是原图。",
        "options": [
            {"label": "缩略图", "value": 1},
            {"label": "压缩图", "value": 2},
            {"label": "原图", "value": 3},
        ],
    },
    {
        "key": "wait",
        "label": "等待下载完成",
        "type": "checkbox",
        "default": True,
        "full_width": False,
        "description": "开启后会等待主 API 返回实际下载路径。",
    },
    {
        "key": "timeout",
        "label": "下载超时秒数",
        "type": "number",
        "default": 15,
        "min": 1,
        "max": 120,
        "step": 1,
        "full_width": False,
        "description": "等待 CDN 下载完成的最长时间。",
    },
]


async def handle_message(event, context):
    if not event.is_image:
        return {"handled": False, "detail": ""}

    msgid = normalize_text(event.normalized_msgid)
    wxid = normalize_text(event.conversation_wxid)
    if not msgid or not wxid:
        return {"handled": False, "detail": "消息缺少 msgid 或会话 wxid"}

    response = await context.api.download_cdn_image(
        msgid=msgid,
        wxid=wxid,
        wxpid=event.normalized_wxpid,
        flag=int(context.config.get("flag", context.settings.image_download_flag or 3)),
        wait=bool(context.config.get("wait", context.settings.image_download_wait if context.settings.image_download_wait is not None else True)),
        timeout=int(context.config.get("timeout", context.settings.image_download_timeout or 15)),
    )
    detail = response.get("path") or f"ret={response.get('ret')}"
    context.logger.info(f"插件 {context.plugin_name} 已处理({wxid})图片消息 {msgid} -> {detail}")
    return {
        "handled": True,
        "detail": f"图片已下载: {detail}",
        "data": dict(response or {}),
    }

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text, to_string_list


RESOURCE_TYPE_OPTIONS = [
    {"label": "视频", "value": "视频"},
    {"label": "文件", "value": "文件"},
]


name = "auto_download_resources"
description = "按作用范围自动下载视频和文件资源"
event_filters = ["video", "file"]
scope_targets = ["rooms", "friend_labels"]
config_schema = [
    {
        "key": "user_types",
        "aliases": ["user_save_resource_type"],
        "label": "自动下载类型",
        "type": "multi-checkbox",
        "default": [],
        "description": "收到命中作用范围的视频或文件消息时，自动下载这些资源类型。",
        "options": RESOURCE_TYPE_OPTIONS,
    },
    {
        "key": "wait",
        "label": "等待下载完成",
        "type": "checkbox",
        "default": True,
        "full_width": False,
        "description": "开启后会等待资源下载完成再返回结果。",
    },
    {
        "key": "timeout",
        "label": "下载超时秒数",
        "type": "number",
        "default": 15,
        "min": 1,
        "max": 300,
        "step": 1,
        "full_width": False,
    },
]


def resolve_rules(config, event):
    direct_rules = config.get("user_types") if config.get("user_types") is not None else config.get("user_save_resource_type", [])
    return direct_rules


def resolve_operations(type_code, rules):
    normalized_rules = to_string_list(rules)
    if type_code == MESSAGE_TYPES.VIDEO and "视频" in normalized_rules:
        return [{"kind": "video", "label": "视频"}]
    if type_code == MESSAGE_TYPES.FILE and "文件" in normalized_rules:
        return [{"kind": "file", "label": "文件"}]
    return []


async def handle_message(event, context):
    type_code = get_message_type(event)
    if type_code not in {MESSAGE_TYPES.VIDEO, MESSAGE_TYPES.FILE}:
        return {"handled": False, "detail": "不是可下载资源消息"}

    msgid = normalize_text(event.normalized_msgid)
    wxid = normalize_text(event.conversation_wxid)
    if not msgid or not wxid:
        return {"handled": False, "detail": "消息缺少 msgid 或会话 wxid"}

    operations = resolve_operations(type_code, resolve_rules(context.config, event))
    if not operations:
        return {"handled": False, "detail": "当前会话没有匹配到资源下载规则"}

    wait = bool(context.config.get("wait", True))
    timeout = int(context.config.get("timeout", context.settings.image_download_timeout or 15))
    results: list[dict[str, object]] = []
    for operation in operations:
        if operation["kind"] == "video":
            response = await context.api.download_cdn_video(msgid=msgid, wxid=wxid, wxpid=event.normalized_wxpid, wait=wait, timeout=timeout)
            results.append({"type": operation["label"], "path": response.get("path", ""), "ret": response.get("ret")})
            continue
        response = await context.api.download_cdn_file(msgid=msgid, wxid=wxid, wxpid=event.normalized_wxpid, wait=wait, timeout=timeout)
        results.append({"type": operation["label"], "path": response.get("path", ""), "ret": response.get("ret")})

    handled_count = context.state.increment("download_count", len(results))
    context.logger.info(
        "资源下载任务已完成",
        {
            "conversation_wxid": wxid,
            "msgid": msgid,
            "results": results,
            "handled_count": handled_count,
        },
    )
    return {
        "handled": True,
        "detail": f"{'/'.join(item['type'] for item in results)} 已下载",
        "data": {
            "msgid": msgid,
            "conversation_wxid": wxid,
            "results": results,
            "handled_count": handled_count,
        },
    }

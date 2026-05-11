from csv import writer
from io import StringIO
from pathlib import Path

from ._plugin_sdk import filter_room_entries, normalize_text


CSV_FIELDS = [
    "username",
    "nick_name",
    "big_head_url",
    "small_head_url",
    "gender",
    "signature",
    "country",
    "province",
    "city",
    "is_owner",
    "room_nick_name",
]


name = "export_room_members"
description = "在启动或热重载时导出指定群聊的成员列表到 CSV"
category = "functional"
message_dependent = False
scope_targets = ["rooms"]
config_schema = [
    {
        "key": "export_dir",
        "aliases": ["save_path"],
        "label": "导出目录",
        "type": "text",
        "default": "",
        "description": "CSV 文件会保存到这个目录。",
    },
    {
        "key": "wxpid",
        "label": "默认微信进程ID",
        "type": "number",
        "full_width": False,
        "description": "留空时使用主 API 的默认微信进程。",
    },
    {
        "key": "rooms",
        "label": "导出群列表",
        "type": "object-list",
        "default": [],
        "meaningful_keys": ["roomid"],
        "description": "为每个群填写群ID、显示名和可选微信进程。",
        "columns": [
            {"key": "roomid", "label": "群ID", "type": "text", "placeholder": "123456@chatroom"},
            {"key": "nickname", "label": "群名称", "type": "text", "placeholder": "导出的文件名显示"},
            {"key": "wxpid", "label": "微信进程ID", "type": "number", "placeholder": "留空使用默认进程"},
        ],
    },
    {
        "key": "export_on_startup",
        "label": "启动时自动导出",
        "type": "checkbox",
        "default": True,
        "full_width": False,
    },
    {
        "key": "export_on_reload",
        "label": "热重载时自动导出",
        "type": "checkbox",
        "default": True,
        "full_width": False,
    },
]


def normalize_room_entries(config):
    rooms = config.get("rooms")
    if isinstance(rooms, list):
        entries = [item for item in rooms if isinstance(item, dict) and item.get("roomid")]
        return filter_room_entries(entries, config, allow_missing_entries=True)
    if isinstance(rooms, dict):
        entries = [{"roomid": roomid, "nickname": nickname} for roomid, nickname in rooms.items()]
        return filter_room_entries(entries, config, allow_missing_entries=True)
    return filter_room_entries([], config, allow_missing_entries=True)


def sanitize_file_name(value):
    return normalize_text(value).translate(str.maketrans({'\\': '_', '/': '_', ':': '_', '*': '_', '?': '_', '"': '_', '<': '_', '>': '_', '|': '_'}))


def render_csv(members):
    buffer = StringIO()
    csv_writer = writer(buffer)
    csv_writer.writerow(CSV_FIELDS)
    for member in members:
        csv_writer.writerow([member.get(field, "") for field in CSV_FIELDS])
    return "\ufeff" + buffer.getvalue()


async def export_members(context, reason):
    export_dir = normalize_text(context.config.get("export_dir") or context.config.get("save_path") or "")
    rooms = normalize_room_entries(context.config)
    default_wxpid = context.config.get("wxpid")
    if not export_dir or not rooms:
        return 0

    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    exported_count = 0
    for room in rooms:
        roomid = normalize_text(room.get("roomid"))
        if not roomid:
            continue
        members = await context.api.get_room_members(roomid, room.get("wxpid") if room.get("wxpid") is not None else default_wxpid)
        nickname = normalize_text(room.get("nickname") or room.get("name") or roomid)
        file_path = export_path / f"{sanitize_file_name(nickname)}({roomid}).csv"
        file_path.write_text(render_csv(members), encoding="utf-8")
        exported_count += 1
        context.logger.info("已导出群成员列表", {"roomid": roomid, "nickname": nickname, "filePath": str(file_path), "reason": reason, "member_count": len(members)})
    return exported_count


async def startup(context):
    if context.config.get("export_on_startup") is False:
        return
    await export_members(context, "startup")


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed") and context.config.get("export_on_reload") is not False:
        await export_members(context, "hot-reload")


async def execute(context):
    exported_count = await export_members(context, "manual-execute")
    if exported_count > 0:
        context.logger.info("群成员导出已完成", {"reason": "manual-execute", "exported_count": exported_count})
        return {"handled": True, "detail": f"已导出 {exported_count} 个群聊的成员列表", "data": {"exported_count": exported_count}}
    return {"handled": False, "detail": "没有可导出的群聊或导出目录未配置", "data": {"exported_count": 0}}

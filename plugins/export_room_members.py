import os
from csv import writer
from io import StringIO
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from ._plugin_sdk import normalize_text, resolve_wxpid_targets, to_string_list


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
    "is_admin",
    "room_nick_name",
]


name = "export_room_members"
description = "在启动或热重载时导出指定群聊的成员列表到 CSV"
category = "functional"
message_dependent = False


WINDOWS_DOWNLOADS_FOLDER_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"
WINDOWS_DOWNLOADS_REGISTRY_KEYS = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
)


def get_default_export_dir():
    if winreg is not None:
        for registry_key in WINDOWS_DOWNLOADS_REGISTRY_KEYS:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_key) as key:
                    value, _ = winreg.QueryValueEx(key, WINDOWS_DOWNLOADS_FOLDER_GUID)
            except OSError:
                continue

            resolved_value = normalize_text(os.path.expandvars(str(value)))
            if resolved_value:
                return Path(resolved_value).expanduser()

    return Path.home() / "Downloads"


DEFAULT_EXPORT_DIR = get_default_export_dir()


config_schema = [
    {
        "key": "wxpid",
        "label": "微信进程",
        "type": "select",
        "options_source": "wxpid_options",
        "required": True,
        "required_message": "微信进程不能为空",
        "full_width": False,
    },
    {
        "key": "export_dir",
        "aliases": ["save_path"],
        "label": "导出目录",
        "type": "text",
        "default": str(DEFAULT_EXPORT_DIR),
        "description": "CSV 文件会保存到这个目录，默认使用当前系统下载目录。",
    },
    {
        "key": "rooms",
        "label": "需要导出的群",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["roomid"],
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能保留一条导出配置",
        "empty_text": "暂无已配置群聊，点击“新增”选择需要导出的群聊，再点当前行的“保存”。",
        "description": "每行选择一个需要导出的群聊。",
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
        ],
    },
]

def resolve_export_dir(config):
    configured_dir = normalize_text(config.get("export_dir") or config.get("save_path") or "")
    return configured_dir or str(get_default_export_dir())


def normalize_room_entries(config):
    entries = []
    seen_roomids = set()

    def append_room(roomid):
        normalized_roomid = normalize_text(roomid)
        if not normalized_roomid or normalized_roomid in seen_roomids:
            return
        seen_roomids.add(normalized_roomid)
        entries.append({"roomid": normalized_roomid})

    rooms = config.get("rooms")
    if isinstance(rooms, list):
        for item in rooms:
            if not isinstance(item, dict):
                continue
            append_room(item.get("roomid") or item.get("wxid"))
        return entries

    if isinstance(rooms, dict):
        for roomid in rooms:
            append_room(roomid)
        return entries

    for roomid in to_string_list(config.get("roomids") or config.get("room_ids")):
        append_room(roomid)
    return entries


async def build_room_lookup(context, wxpid):
    rooms = await context.api.get_room_list(wxpid)
    by_id = {}
    for room in rooms if isinstance(rooms, list) else []:
        roomid = normalize_text(room.get("wxid"))
        nickname = normalize_text(room.get("nickname") or room.get("remarks") or room.get("wxid"))
        if not roomid:
            continue
        by_id[roomid] = {"roomid": roomid, "nickname": nickname, "wxpid": wxpid}
    return by_id


def sanitize_file_name(value):
    return normalize_text(value).translate(str.maketrans({'\\': '_', '/': '_', ':': '_', '*': '_', '?': '_', '"': '_', '<': '_', '>': '_', '|': '_'}))


def render_csv(members):
    buffer = StringIO()
    csv_writer = writer(buffer)
    csv_writer.writerow(CSV_FIELDS)
    for member in members:
        csv_writer.writerow([member.get(field, "") for field in CSV_FIELDS])
    return "\ufeff" + buffer.getvalue()


def build_export_file_path(export_path, room_name, roomid, wxpid=None, include_wxpid=False):
    file_stem = sanitize_file_name(room_name or roomid)
    if normalize_text(room_name) and normalize_text(room_name) != roomid:
        file_stem = f"{file_stem}({roomid})"
    if include_wxpid and wxpid not in (None, ""):
        file_stem = f"{file_stem}_wxpid{wxpid}"
    return export_path / f"{file_stem}.csv"


async def export_members(context, reason):
    export_dir = resolve_export_dir(context.config)
    rooms = normalize_room_entries(context.config)
    wxpid_selection = context.config.get("wxpid")
    target_wxpids = await resolve_wxpid_targets(context.api, wxpid_selection)
    report = {
        "reason": reason,
        "wxpid_selection": wxpid_selection,
        "target_wxpids": target_wxpids,
        "export_dir": export_dir,
        "requested_count": len(rooms),
        "exported_count": 0,
        "failed_count": 0,
        "rooms": [],
    }
    if not rooms:
        context.logger.info("群成员导出跳过，未配置需要导出的群聊", report)
        return report
    if not target_wxpids:
        report["error"] = "missing-live-wxpids"
        context.logger.warning("群成员导出跳过，当前没有可用的微信进程", report)
        context.state.namespace("export_room_members").set("last_report", report)
        return report

    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    context.logger.info("开始导出群成员列表", report)

    include_wxpid_in_file_name = len(target_wxpids) > 1
    room_lookup_cache = {}

    for wxpid in target_wxpids:
        room_lookup = {}
        try:
            room_lookup = await build_room_lookup(context, wxpid)
            room_lookup_cache[wxpid] = room_lookup
            context.logger.info("已加载群聊索引", {"reason": reason, "wxpid": wxpid, "room_count": len(room_lookup)})
        except Exception as exc:
            context.logger.warning("加载群聊索引失败，将按群ID直接导出", {"reason": reason, "wxpid": wxpid, "error": str(exc)})

        for room in rooms:
            roomid = normalize_text(room.get("roomid"))
            if not roomid:
                continue
            room_info = room_lookup.get(roomid)
            if room_lookup and not room_info:
                continue

            try:
                members = await context.api.get_room_members(roomid, wxpid)
            except Exception as exc:
                failure = {"reason": reason, "roomid": roomid, "room_name": normalize_text(room_info.get("nickname") if room_info else roomid), "wxpid": wxpid, "status": "failed", "error": str(exc)}
                report["rooms"].append(failure)
                report["failed_count"] += 1
                context.logger.warning("导出群成员失败", failure)
                continue

            if not isinstance(members, list):
                context.logger.warning("群成员接口返回了非列表结果，已按空列表导出", {"reason": reason, "roomid": roomid, "wxpid": wxpid, "result_type": type(members).__name__})
                members = []

            room_name = normalize_text(room_info.get("nickname") if room_info else roomid) or roomid
            file_path = build_export_file_path(export_path, room_name, roomid, wxpid, include_wxpid_in_file_name)
            file_path.write_text(render_csv(members), encoding="utf-8")
            room_report = {"reason": reason, "roomid": roomid, "room_name": room_name, "wxpid": wxpid, "file_path": str(file_path), "member_count": len(members)}
            report["rooms"].append(room_report)
            report["exported_count"] += 1
            context.logger.info("已导出群成员列表", room_report)

    context.logger.info("群成员导出流程结束", report)
    context.state.namespace("export_room_members").set("last_report", report)
    return report


async def startup(context):
    await export_members(context, "startup")


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed"):
        await export_members(context, "hot-reload")


async def execute(context):
    report = await export_members(context, "manual-execute")
    if report.get("error") == "missing-live-wxpids":
        return {"handled": False, "detail": "当前没有已登录的微信进程", "data": report}
    if report.get("exported_count"):
        detail = f"已导出 {report['exported_count']} 个群聊的成员列表"
        if report.get("failed_count"):
            detail = f"{detail}，另有 {report['failed_count']} 个群聊导出失败"
        return {"handled": True, "detail": detail, "data": report}
    if report.get("requested_count"):
        return {"handled": False, "detail": "已配置群聊，但本次没有成功导出任何群成员列表", "data": report}
    return {"handled": False, "detail": "请先配置需要导出的群聊", "data": report}

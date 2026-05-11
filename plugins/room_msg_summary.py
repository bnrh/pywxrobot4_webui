import json
from datetime import datetime, timedelta
from pathlib import Path

from ._plugin_sdk import filter_room_entries, format_date_time, normalize_text, to_string_list


name = "room_msg_summary"
description = "按配置导出指定群聊在给定时间窗口内的消息记录"
category = "functional"
message_dependent = False
scope_targets = ["rooms"]
config_schema = [
    {"key": "export_dir", "aliases": ["save_path"], "label": "导出目录", "type": "text", "default": "", "description": "群消息文件会输出到这个目录。"},
    {"key": "wxpid", "label": "微信进程", "type": "number", "full_width": False},
    {"key": "max_count", "label": "最多导出消息数", "type": "number", "default": 500, "min": 1, "max": 20000, "step": 1, "full_width": False},
    {"key": "file_type", "aliases": ["output_format"], "label": "输出格式", "type": "select", "default": "txt", "full_width": False, "options": [{"label": "TXT(JSONL 每行一条)", "value": "txt"}, {"label": "JSONL", "value": "jsonl"}, {"label": "JSON", "value": "json"}]},
    {"key": "time_range", "label": "默认时间范围", "type": "select", "default": "2h", "full_width": False, "description": "如果未手动填写开始和结束时间，就按这里的范围导出。", "options": [{"label": "最近 2 小时", "value": "2h"}, {"label": "最近 6 小时", "value": "6h"}, {"label": "最近 12 小时", "value": "12h"}, {"label": "最近 1 天", "value": "1d"}, {"label": "最近 3 天", "value": "3d"}, {"label": "最近 1 年", "value": "1y"}]},
    {"key": "start_time", "label": "开始时间", "type": "text", "default": "", "full_width": False, "placeholder": "yyyy-MM-dd HH:mm:ss"},
    {"key": "end_time", "label": "结束时间", "type": "text", "default": "", "full_width": False, "placeholder": "yyyy-MM-dd HH:mm:ss"},
    {"key": "run_on_startup", "label": "启动时导出", "type": "checkbox", "default": True, "full_width": False},
    {"key": "run_on_reload", "label": "热重载时导出", "type": "checkbox", "default": True, "full_width": False},
    {"key": "rooms", "label": "导出群列表", "type": "object-list", "default": [], "meaningful_keys": ["roomid", "room_name"], "description": "可按群ID或群名称匹配。", "columns": [{"key": "roomid", "label": "群ID", "type": "text", "placeholder": "123456@chatroom"}, {"key": "room_name", "label": "群名称", "type": "text", "placeholder": "可选，用于按名称匹配"}, {"key": "wxpid", "label": "微信进程ID", "type": "number", "placeholder": "可选"}]},
]


def sanitize_file_name(value):
    return normalize_text(value).translate(str.maketrans({'\\': '_', '/': '_', ':': '_', '*': '_', '?': '_', '"': '_', '<': '_', '>': '_', '|': '_'}))


def normalize_room_entries(config):
    rooms = config.get("rooms")
    if isinstance(rooms, list):
        entries = [{"roomid": normalize_text(item.get("roomid") or item.get("wxid")), "room_name": normalize_text(item.get("room_name") or item.get("nickname") or item.get("name")), "wxpid": item.get("wxpid")} for item in rooms if isinstance(item, dict) and (normalize_text(item.get("roomid") or item.get("wxid")) or normalize_text(item.get("room_name") or item.get("nickname") or item.get("name")))]
        return filter_room_entries(entries, config, allow_missing_entries=True)
    if isinstance(rooms, dict):
        entries = [{"roomid": normalize_text(roomid), "room_name": normalize_text(nickname)} for roomid, nickname in rooms.items() if normalize_text(roomid)]
        return filter_room_entries(entries, config, allow_missing_entries=True)
    entries = [{"roomid": roomid} for roomid in to_string_list(config.get("roomids") or config.get("room_ids"))]
    return filter_room_entries(entries, config, allow_missing_entries=True)


async def build_room_lookup(context, wxpid):
    rooms = await context.api.get_room_list(wxpid)
    by_id = {}
    by_name = {}
    for room in rooms if isinstance(rooms, list) else []:
        roomid = normalize_text(room.get("wxid"))
        nickname = normalize_text(room.get("nickname") or room.get("remarks") or room.get("wxid"))
        if not roomid:
            continue
        entry = {"roomid": roomid, "nickname": nickname, "wxpid": wxpid}
        by_id[roomid] = entry
        if nickname and nickname not in by_name:
            by_name[nickname] = entry
    return {"by_id": by_id, "by_name": by_name}


def resolve_lookback_seconds(config):
    range_key = normalize_text(config.get("time_range") or config.get("lookback") or "").lower()
    range_map = {"2h": 2 * 60 * 60, "6h": 6 * 60 * 60, "12h": 12 * 60 * 60, "1d": 24 * 60 * 60, "3d": 3 * 24 * 60 * 60, "1y": 365 * 24 * 60 * 60}
    if range_key in range_map:
        return range_map[range_key]
    try:
        lookback_seconds = int(config.get("lookback_seconds") or 0)
        if lookback_seconds > 0:
            return lookback_seconds
    except (TypeError, ValueError):
        pass
    try:
        lookback_hours = float(config.get("lookback_hours") or 0)
        if lookback_hours > 0:
            return int(lookback_hours * 60 * 60)
    except (TypeError, ValueError):
        pass
    return 2 * 60 * 60


def resolve_time_window(config):
    explicit_start = normalize_text(config.get("start_time"))
    explicit_end = normalize_text(config.get("end_time"))
    if explicit_start and explicit_end:
        return explicit_start, explicit_end
    now = datetime.now()
    end_time = explicit_end or format_date_time(now)
    start_time = explicit_start or format_date_time(now - timedelta(seconds=resolve_lookback_seconds(config)))
    return start_time, end_time


def write_messages(file_path, messages, extension):
    target_path = Path(file_path)
    if extension == "json":
        target_path.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    target_path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in messages) + "\n", encoding="utf-8")


async def export_room_messages(context, reason):
    export_dir = normalize_text(context.config.get("export_dir") or context.config.get("save_path") or "")
    entries = normalize_room_entries(context.config)
    if not export_dir or not entries:
        return {"exported_count": 0, "rooms": []}

    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    default_wxpid = context.config.get("wxpid")
    room_lookup_cache = {}
    start_time, end_time = resolve_time_window(context.config)
    max_count = max(1, int(context.config.get("max_count", 500) or 500))
    extension = normalize_text(context.config.get("file_type") or context.config.get("output_format") or "txt").lower() or "txt"
    reports = []
    for entry in entries:
        wxpid = entry.get("wxpid") if entry.get("wxpid") is not None else default_wxpid
        if wxpid not in room_lookup_cache:
            room_lookup_cache[wxpid] = await build_room_lookup(context, wxpid)
        lookup = room_lookup_cache[wxpid]
        resolved_room = (entry.get("roomid") and lookup["by_id"].get(entry["roomid"])) or (entry.get("room_name") and lookup["by_name"].get(entry["room_name"]))
        if not resolved_room:
            context.logger.warning("群消息汇总插件未找到目标群聊", {"reason": reason, "roomid": entry.get("roomid"), "room_name": entry.get("room_name"), "wxpid": wxpid})
            continue
        messages = await context.api.get_chat_messages(wxid=resolved_room["roomid"], start_time=start_time, end_time=end_time, max_count=max_count, wxpid=wxpid)
        room_dir = export_path / sanitize_file_name(resolved_room["nickname"] or resolved_room["roomid"])
        room_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{sanitize_file_name(resolved_room['nickname'])}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{extension}"
        file_path = room_dir / file_name
        write_messages(file_path, messages if isinstance(messages, list) else [], extension)
        report = {"roomid": resolved_room["roomid"], "room_name": resolved_room["nickname"], "wxpid": wxpid, "file_path": str(file_path), "message_count": len(messages) if isinstance(messages, list) else 0, "start_time": start_time, "end_time": end_time}
        reports.append(report)
        context.logger.info("群消息已导出", report)

    payload = {"reason": reason, "exported_count": len(reports), "rooms": reports, "start_time": start_time, "end_time": end_time}
    context.state.namespace("room_msg_summary").set("last_report", payload)
    return payload


async def startup(context):
    if context.config.get("run_on_startup") is False:
        return
    report = await export_room_messages(context, "startup")
    if report.get("exported_count"):
        context.logger.info("群消息汇总导出已完成", report)


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed") and context.config.get("run_on_reload") is not False:
        report = await export_room_messages(context, "hot-reload")
        if report.get("exported_count"):
            context.logger.info("群消息汇总导出已完成", report)


async def execute(context):
    report = await export_room_messages(context, "manual-execute")
    if report.get("exported_count"):
        context.logger.info("群消息汇总导出已完成", report)
        return {"handled": True, "detail": f"已导出 {report['exported_count']} 个群聊的消息记录", "data": report}
    return {"handled": False, "detail": "没有可导出的群聊消息或导出目录未配置", "data": report}
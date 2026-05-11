import json
from datetime import datetime
from pathlib import Path
from time import time

from ._plugin_sdk import format_date_time, get_room_scope, normalize_text, sleep, to_string_list


name = "room_members_deduplication"
description = "按配置检查多个群聊的重复成员，并可选择性自动移除重复项"
category = "functional"
message_dependent = False
scope_targets = ["rooms"]
config_schema = [
    {"key": "wxpid", "label": "微信进程", "type": "number", "full_width": False},
    {"key": "delay_ms", "label": "删除间隔毫秒", "type": "number", "default": 100, "min": 0, "max": 10000, "step": 10, "full_width": False},
    {"key": "dry_run", "label": "仅生成报告不删除", "type": "checkbox", "default": True, "full_width": False},
    {"key": "remove_duplicates", "label": "允许实际删除重复成员", "type": "checkbox", "default": True, "full_width": False},
    {"key": "report_dir", "aliases": ["save_path"], "label": "报告输出目录", "type": "text", "default": "", "description": "填写后会把去重报告输出成 JSON 文件。"},
    {"key": "run_on_startup", "label": "启动时执行", "type": "checkbox", "default": True, "full_width": False},
    {"key": "run_on_reload", "label": "热重载时执行", "type": "checkbox", "default": True, "full_width": False},
    {"key": "room_groups", "label": "群组去重规则", "type": "object-list", "default": [], "meaningful_keys": ["roomids"], "description": "每一行代表一组要去重的群聊。群ID 每行一个。", "columns": [{"key": "name", "label": "规则名称", "type": "text", "placeholder": "例如 视频号互通群"}, {"key": "roomids", "label": "群ID 列表", "type": "string-list", "rows": 3, "width": "wide", "placeholder": "每行一个群ID"}, {"key": "keep_roomid", "label": "保留所在群ID", "type": "text", "placeholder": "留空默认保留第一个群"}, {"key": "wxpid", "label": "微信进程ID", "type": "number", "placeholder": "可选"}, {"key": "remove_duplicates", "label": "允许删除", "type": "checkbox"}]},
]


def normalize_group_entries(config):
    room_groups = config.get("room_groups")
    if isinstance(room_groups, list):
        entries = []
        for index, item in enumerate(room_groups, start=1):
            if not isinstance(item, dict):
                continue
            roomids = to_string_list(item.get("roomids") or item.get("rooms") or item.get("room_ids"))
            if len(roomids) >= 2:
                entries.append({"name": normalize_text(item.get("name") or f"group_{index}"), "roomids": roomids, "wxpid": item.get("wxpid"), "remove_duplicates": item.get("remove_duplicates"), "keep_roomid": normalize_text(item.get("keep_roomid"))})
        return apply_room_scope(entries, config)
    single_rooms = to_string_list(config.get("roomids") or config.get("rooms") or config.get("room_ids"))
    if len(single_rooms) >= 2:
        entries = [{"name": normalize_text(config.get("group_name") or "default"), "roomids": single_rooms, "wxpid": config.get("wxpid"), "remove_duplicates": config.get("remove_duplicates"), "keep_roomid": normalize_text(config.get("keep_roomid"))}]
        return apply_room_scope(entries, config)
    return apply_room_scope([], config)


def apply_room_scope(entries, config):
    mode, selected_room_ids = get_room_scope(config)
    if mode == "none":
        return []
    if mode == "selected" and not selected_room_ids:
        return []
    if mode != "selected":
        return entries

    selected_set = set(selected_room_ids)
    scoped_entries = []
    for item in entries:
        roomids = [roomid for roomid in item.get("roomids", []) if roomid in selected_set]
        if len(roomids) < 2:
            continue
        next_item = {**item, "roomids": roomids}
        keep_roomid = normalize_text(item.get("keep_roomid"))
        if keep_roomid and keep_roomid not in roomids:
            next_item["keep_roomid"] = roomids[0]
        scoped_entries.append(next_item)
    return scoped_entries


def build_duplicate_report(group, members_by_room):
    member_map = {}
    for roomid, members in members_by_room.items():
        for member in members:
            if member.get("is_owner"):
                continue
            wxid = normalize_text(member.get("username") or member.get("wxid"))
            if not wxid:
                continue
            if wxid not in member_map:
                member_map[wxid] = {"wxid": wxid, "nickname": normalize_text(member.get("room_nick_name") or member.get("nick_name") or member.get("nickname")), "rooms": []}
            member_map[wxid]["rooms"].append(roomid)
    reports = []
    for item in member_map.values():
        if len(item["rooms"]) <= 1:
            continue
        keep_roomid = normalize_text(group.get("keep_roomid")) or item["rooms"][0]
        reports.append({**item, "keep_roomid": keep_roomid, "remove_roomids": [roomid for roomid in item["rooms"] if roomid != keep_roomid]})
    return reports


async def write_report_file(report_dir, payload):
    if not report_dir:
        return ""
    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)
    file_path = report_path / f"room_members_deduplication_{int(time() * 1000)}.json"
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(file_path)


async def run_deduplication(context, reason):
    groups = normalize_group_entries(context.config)
    if not groups:
        return {"groups": [], "duplicate_count": 0, "removed_count": 0, "dry_run": True}

    dry_run = context.config.get("dry_run") is not False
    delay_ms = max(0, int(float(context.config.get("delay_ms", 100) or 0)))
    reports = []
    duplicate_count = 0
    removed_count = 0
    for group in groups:
        wxpid = group.get("wxpid") if group.get("wxpid") is not None else context.config.get("wxpid")
        members_by_room = {}
        for roomid in group["roomids"]:
            members = await context.api.get_room_members(roomid, wxpid)
            members_by_room[roomid] = members if isinstance(members, list) else []
        duplicates = build_duplicate_report(group, members_by_room)
        duplicate_count += len(duplicates)
        group_removed = 0
        if not dry_run and (group.get("remove_duplicates") if group.get("remove_duplicates") is not None else context.config.get("remove_duplicates")) is not False:
            for duplicate in duplicates:
                for roomid in duplicate["remove_roomids"]:
                    await context.api.delete_room_members(roomid=roomid, wxids=[duplicate["wxid"]], wxpid=wxpid)
                    group_removed += 1
                    removed_count += 1
                    if delay_ms > 0:
                        await sleep(delay_ms)
        reports.append({"name": group["name"], "wxpid": wxpid, "roomids": group["roomids"], "duplicate_count": len(duplicates), "removed_count": group_removed, "duplicates": duplicates})

    payload = {"reason": reason, "dry_run": dry_run, "duplicate_count": duplicate_count, "removed_count": removed_count, "groups": reports, "generated_at": format_date_time(datetime.now())}
    report_file = await write_report_file(normalize_text(context.config.get("report_dir") or context.config.get("save_path")), payload)
    if report_file:
        payload["report_file"] = report_file
    context.state.namespace("room_members_deduplication").set("last_report", payload)
    return payload


async def startup(context):
    if context.config.get("run_on_startup") is False:
        return
    report = await run_deduplication(context, "startup")
    if report.get("duplicate_count") or report.get("groups"):
        context.logger.info("群成员去重检查已完成", report)


async def on_hot_reload(hot_reload, context):
    if hot_reload.get("changed") and context.config.get("run_on_reload") is not False:
        report = await run_deduplication(context, "hot-reload")
        if report.get("duplicate_count") or report.get("groups"):
            context.logger.info("群成员去重检查已完成", report)


async def execute(context):
    report = await run_deduplication(context, "manual-execute")
    if report.get("duplicate_count") or report.get("groups"):
        context.logger.info("群成员去重检查已完成", report)
        return {"handled": True, "detail": f"已完成 {len(report.get('groups', []))} 组群聊去重检查", "data": report}
    return {"handled": False, "detail": "没有可执行的群聊去重规则", "data": report}

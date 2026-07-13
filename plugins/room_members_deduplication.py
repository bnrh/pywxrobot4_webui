import os
from csv import writer
from datetime import datetime
from io import StringIO
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from ._plugin_sdk import format_date_time, normalize_text, resolve_wxpid_targets, to_string_list, is_truthy


name = "room_members_deduplication"
description = "按配置检查多个群聊组中的重复成员，并导出 CSV 报表"
category = "functional"
message_dependent = False
direct_execute = True


WINDOWS_DOWNLOADS_FOLDER_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"
WINDOWS_DOWNLOADS_REGISTRY_KEYS = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
)

CSV_FIELDS = [
    "group_name",
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
    "occurrence_count",
    "room_names",
    "room_ids",
    "room_nick_names",
]




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
        "aliases": ["report_dir", "save_path"],
        "label": "重复群成员输出目录",
        "type": "text",
        "default": str(DEFAULT_EXPORT_DIR),
        "description": "每个群聊组的重复成员 CSV 会输出到这个目录，默认使用当前系统下载目录。",
    },
    {
        "key": "room_groups",
        "label": "需要检查的群聊组",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["group_name", "roomid"],
        "unique_by": ["group_name", "roomid"],
        "unique_message": "同一分组内不能重复选择同一个群聊",
        "empty_text": "暂无已配置群聊组，点击“新增”后填写分组名称并选择群聊，再点当前行的“保存”。",
        "description": "同一个分组名称下可添加多个群聊。执行插件时会分别统计每个分组中在 2 个及以上群聊重复出现的成员。",
        "columns": [
            {
                "key": "group_name",
                "label": "分组名称",
                "type": "text",
                "placeholder": "例如 机器人群",
                "required": True,
                "required_message": "分组名称不能为空",
                "width": "compact",
            },
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


def normalize_group_entries(config):
    grouped_roomids = {}
    ignored_groups = []

    def append_room(group_name, roomid):
        normalized_group_name = normalize_text(group_name)
        normalized_roomid = normalize_text(roomid)
        if not normalized_group_name or not normalized_roomid:
            return
        bucket = grouped_roomids.setdefault(normalized_group_name, [])
        if normalized_roomid not in bucket:
            bucket.append(normalized_roomid)

    room_groups = config.get("room_groups")
    if isinstance(room_groups, list):
        for index, item in enumerate(room_groups, start=1):
            if not isinstance(item, dict):
                continue
            group_name = normalize_text(item.get("group_name") or item.get("name") or f"第{index}组")
            roomids = to_string_list(item.get("roomids") or item.get("rooms") or item.get("room_ids"))
            if roomids:
                for roomid in roomids:
                    append_room(group_name, roomid)
                continue
            append_room(group_name, item.get("roomid") or item.get("wxid"))
    elif isinstance(room_groups, dict):
        for group_name, value in room_groups.items():
            normalized_group_name = normalize_text(group_name)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        roomids = to_string_list(item.get("roomids") or item.get("rooms") or item.get("room_ids"))
                        if roomids:
                            for roomid in roomids:
                                append_room(normalized_group_name, roomid)
                            continue
                        append_room(normalized_group_name, item.get("roomid") or item.get("wxid"))
                        continue
                    append_room(normalized_group_name, item)
                continue
            if isinstance(value, dict):
                roomids = to_string_list(value.get("roomids") or value.get("rooms") or value.get("room_ids"))
                if roomids:
                    for roomid in roomids:
                        append_room(normalized_group_name, roomid)
                    continue
                append_room(normalized_group_name, value.get("roomid") or value.get("wxid"))
                continue
            for roomid in to_string_list(value):
                append_room(normalized_group_name, roomid)
    else:
        legacy_roomids = to_string_list(config.get("roomids") or config.get("room_ids"))
        legacy_group_name = normalize_text(config.get("group_name") or "默认分组")
        for roomid in legacy_roomids:
            append_room(legacy_group_name, roomid)

    groups = []
    for group_name, roomids in grouped_roomids.items():
        if len(roomids) < 2:
            ignored_groups.append({"group_name": group_name, "roomids": roomids})
            continue
        groups.append({"group_name": group_name, "roomids": roomids})
    return {"groups": groups, "ignored_groups": ignored_groups}

def resolve_export_dir(config):
    configured_dir = normalize_text(config.get("export_dir") or config.get("report_dir") or config.get("save_path") or "")
    return configured_dir or str(DEFAULT_EXPORT_DIR)


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
    text = normalize_text(value)
    return text.translate(str.maketrans({'\\': '_', '/': '_', ':': '_', '*': '_', '?': '_', '"': '_', '<': '_', '>': '_', '|': '_'}))


def build_export_file_path(export_path, group_name, room_names, wxpid=None, include_wxpid=False):
    joined_room_names = "｜".join([normalize_text(item) for item in room_names if normalize_text(item)])
    file_stem = sanitize_file_name(joined_room_names or group_name or "重复群成员") or "重复群成员"
    if len(file_stem) > 120:
        fallback_name = sanitize_file_name(f"{normalize_text(group_name) or '重复群成员'}_共{len(room_names)}群")
        file_stem = (fallback_name or "重复群成员")[:120].rstrip("._ ") or "重复群成员"
    if include_wxpid and wxpid not in (None, ""):
        file_stem = f"{file_stem}_wxpid{wxpid}"
    return export_path / f"{file_stem}.csv"


def render_csv(rows):
    buffer = StringIO()
    csv_writer = writer(buffer)
    csv_writer.writerow(CSV_FIELDS)
    for row in rows:
        csv_writer.writerow([row.get(field, "") for field in CSV_FIELDS])
    return "\ufeff" + buffer.getvalue()


def merge_member_profile(entry, member):
    profile_fields = ["nick_name", "big_head_url", "small_head_url", "gender", "signature", "country", "province", "city"]
    for field in profile_fields:
        current_value = entry.get(field)
        if current_value not in (None, ""):
            continue
        if field == "nick_name":
            next_value = member.get("nick_name") or member.get("nickname")
        else:
            next_value = member.get(field)
        if next_value in (None, ""):
            continue
        entry[field] = next_value
    if is_truthy(member.get("is_owner")):
        entry["is_owner"] = True


def should_ignore_member(member):
    return is_truthy(member.get("is_owner")) or is_truthy(member.get("is_admin"))


def build_duplicate_rows(group_name, members_by_room, room_lookup):
    member_map = {}
    for roomid, members in members_by_room.items():
        room_name = normalize_text(room_lookup.get(roomid, {}).get("nickname") or roomid) or roomid
        for member in members if isinstance(members, list) else []:
            if should_ignore_member(member):
                continue
            wxid = normalize_text(member.get("username") or member.get("wxid"))
            if not wxid:
                continue
            if wxid not in member_map:
                member_map[wxid] = {
                    "group_name": group_name,
                    "username": wxid,
                    "nick_name": "",
                    "big_head_url": "",
                    "small_head_url": "",
                    "gender": "",
                    "signature": "",
                    "country": "",
                    "province": "",
                    "city": "",
                    "is_owner": False,
                    "_room_ids": [],
                    "_room_names": [],
                    "_room_nick_names": [],
                }
            entry = member_map[wxid]
            merge_member_profile(entry, member)
            if roomid not in entry["_room_ids"]:
                entry["_room_ids"].append(roomid)
            if room_name not in entry["_room_names"]:
                entry["_room_names"].append(room_name)
            room_nick_name = normalize_text(member.get("room_nick_name"))
            if room_nick_name and room_nick_name not in entry["_room_nick_names"]:
                entry["_room_nick_names"].append(room_nick_name)
    reports = []
    for item in member_map.values():
        occurrence_count = len(item["_room_ids"])
        if occurrence_count <= 1:
            continue
        reports.append(
            {
                "group_name": item["group_name"],
                "username": item["username"],
                "nick_name": item["nick_name"],
                "big_head_url": item["big_head_url"],
                "small_head_url": item["small_head_url"],
                "gender": item["gender"],
                "signature": item["signature"],
                "country": item["country"],
                "province": item["province"],
                "city": item["city"],
                "is_owner": item["is_owner"],
                "occurrence_count": occurrence_count,
                "room_names": "|".join(item["_room_names"]),
                "room_ids": "|".join(item["_room_ids"]),
                "room_nick_names": "|".join(item["_room_nick_names"]),
            }
        )
    reports.sort(key=lambda item: (-int(item.get("occurrence_count") or 0), normalize_text(item.get("nick_name") or item.get("username"))))
    return reports


async def run_deduplication(context, reason):
    normalized_groups = normalize_group_entries(context.config)
    groups = normalized_groups["groups"]
    ignored_groups = normalized_groups["ignored_groups"]
    export_dir = resolve_export_dir(context.config)
    wxpid_selection = context.config.get("wxpid")
    target_wxpids = await resolve_wxpid_targets(context.api, wxpid_selection)
    payload = {
        "reason": reason,
        "wxpid_selection": wxpid_selection,
        "target_wxpids": target_wxpids,
        "export_dir": export_dir,
        "configured_group_count": len(groups) + len(ignored_groups),
        "valid_group_count": len(groups),
        "ignored_group_count": len(ignored_groups),
        "exported_file_count": 0,
        "failed_group_count": 0,
        "duplicate_member_count": 0,
        "ignored_groups": ignored_groups,
        "groups": [],
        "generated_at": format_date_time(datetime.now()),
    }

    if ignored_groups:
        context.logger.warning("部分群聊组因群聊数量不足 2 个而被跳过", {"reason": reason, "ignored_groups": ignored_groups, "wxpid_selection": wxpid_selection})
    if not groups:
        context.logger.info("重复群成员导出跳过，没有可执行的群聊组", payload)
        context.state.namespace("room_members_deduplication").set("last_report", payload)
        return payload
    if not target_wxpids:
        payload["error"] = "missing-live-wxpids"
        context.logger.warning("重复群成员导出跳过，当前没有可用的微信进程", payload)
        context.state.namespace("room_members_deduplication").set("last_report", payload)
        return payload

    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    context.logger.info("开始导出重复群成员 CSV", {"reason": reason, "wxpid_selection": wxpid_selection, "target_wxpids": target_wxpids, "export_dir": export_dir, "group_count": len(groups)})

    include_wxpid_in_file_name = len(target_wxpids) > 1
    for wxpid in target_wxpids:
        room_lookup = {}
        try:
            room_lookup = await build_room_lookup(context, wxpid)
            context.logger.info("已加载群聊索引", {"reason": reason, "wxpid": wxpid, "room_count": len(room_lookup)})
        except Exception as exc:
            context.logger.warning("加载群聊索引失败，将按群ID继续导出重复成员", {"reason": reason, "wxpid": wxpid, "error": str(exc)})

        for group in groups:
            room_names = [normalize_text(room_lookup.get(roomid, {}).get("nickname") or roomid) or roomid for roomid in group["roomids"]]
            context.logger.info("开始检查群聊组重复成员", {"reason": reason, "group_name": group["group_name"], "roomids": group["roomids"], "room_names": room_names, "wxpid": wxpid})

            members_by_room = {}
            room_member_counts = {}
            group_failed = False
            group_error = ""
            for roomid in group["roomids"]:
                try:
                    members = await context.api.get_room_members(roomid, wxpid)
                except Exception as exc:
                    group_failed = True
                    group_error = str(exc)
                    break

                if not isinstance(members, list):
                    context.logger.warning("群成员接口返回了非列表结果，已按空列表处理", {"reason": reason, "group_name": group["group_name"], "roomid": roomid, "wxpid": wxpid, "result_type": type(members).__name__})
                    members = []
                members_by_room[roomid] = members
                room_member_counts[roomid] = len(members)
                context.logger.info("已加载群成员", {"reason": reason, "group_name": group["group_name"], "roomid": roomid, "room_name": normalize_text(room_lookup.get(roomid, {}).get("nickname") or roomid) or roomid, "wxpid": wxpid, "member_count": len(members)})

            if group_failed:
                failure = {
                    "group_name": group["group_name"],
                    "roomids": group["roomids"],
                    "room_names": room_names,
                    "wxpid": wxpid,
                    "status": "failed",
                    "error": group_error,
                }
                payload["groups"].append(failure)
                payload["failed_group_count"] += 1
                context.logger.warning("导出重复群成员失败", {"reason": reason, **failure})
                continue

            duplicates = build_duplicate_rows(group["group_name"], members_by_room, room_lookup)
            file_path = build_export_file_path(export_path, group["group_name"], room_names, wxpid, include_wxpid_in_file_name)
            file_path.write_text(render_csv(duplicates), encoding="utf-8")

            group_report = {
                "group_name": group["group_name"],
                "roomids": group["roomids"],
                "room_names": room_names,
                "wxpid": wxpid,
                "status": "exported",
                "duplicate_count": len(duplicates),
                "room_member_counts": room_member_counts,
                "file_path": str(file_path),
            }
            payload["groups"].append(group_report)
            payload["exported_file_count"] += 1
            payload["duplicate_member_count"] += len(duplicates)
            context.logger.info("已导出重复群成员 CSV", {"reason": reason, **group_report})

    payload["generated_at"] = format_date_time(datetime.now())
    context.logger.info("重复群成员导出流程结束", payload)
    context.state.namespace("room_members_deduplication").set("last_report", payload)
    return payload


async def execute(context):
    report = await run_deduplication(context, "manual-execute")
    if report.get("error") == "missing-live-wxpids":
        return {"handled": False, "detail": "当前没有已登录的微信进程", "data": report}
    if report.get("exported_file_count"):
        detail = f"已导出 {report['exported_file_count']} 组群聊的重复成员 CSV，共 {report['duplicate_member_count']} 名重复成员"
        if report.get("failed_group_count"):
            detail = f"{detail}，另有 {report['failed_group_count']} 组导出失败"
        if report.get("ignored_group_count"):
            detail = f"{detail}，{report['ignored_group_count']} 组因群聊数量不足 2 个已跳过"
        return {"handled": True, "detail": detail, "data": report}
    if report.get("valid_group_count"):
        return {"handled": False, "detail": "已配置群聊组，但本次没有成功导出任何重复成员 CSV", "data": report}
    if report.get("ignored_group_count"):
        return {"handled": False, "detail": "请确保每个分组至少选择 2 个群聊", "data": report}
    return {"handled": False, "detail": "请先配置需要检查的群聊组", "data": report}

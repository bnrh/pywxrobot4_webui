import os
import json
from datetime import datetime, timedelta
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from ._plugin_sdk import format_date_time, normalize_text, resolve_wxpid_targets, to_string_list


name = "user_msg_summary"
description = "按配置导出指定微信好友在给定时间窗口内的聊天记录"
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
    {"key": "wxpid", "label": "微信进程", "type": "number", "full_width": False},
    {"key": "max_count", "label": "最多导出消息数", "type": "number", "default": 500, "min": 1, "max": 10000, "step": 1, "full_width": False},
    {"key": "file_type", "aliases": ["output_format"], "label": "输出格式", "type": "select", "default": "jsonl", "full_width": False, "options": [{"label": "JSONL", "value": "jsonl"}, {"label": "JSON", "value": "json"}]},
    {"key": "time_range", "label": "默认时间范围", "type": "select", "default": "2h", "full_width": False, "description": "选择后会同步更新下方开始时间和结束时间。", "options": [{"label": "最近 2 小时", "value": "2h"}, {"label": "最近 6 小时", "value": "6h"}, {"label": "最近 12 小时", "value": "12h"}, {"label": "最近 1 天", "value": "1d"}, {"label": "最近 3 天", "value": "3d"}, {"label": "最近 1 年", "value": "1y"}]},
    {"key": "start_time", "label": "开始时间", "type": "text", "default": "", "full_width": False, "placeholder": "yyyy-MM-dd HH:mm:ss"},
    {"key": "end_time", "label": "结束时间", "type": "text", "default": "", "full_width": False, "placeholder": "yyyy-MM-dd HH:mm:ss"},
    {
        "key": "users",
        "aliases": ["friends"],
        "label": "导出好友列表",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["wxh"],
        "unique_by": ["wxh"],
        "unique_message": "同一个微信号只能保留一条导出配置",
        "empty_text": "暂无已配置好友，点击“新增”输入需要导出的好友微信号，再点当前行的“保存”。",
        "description": "每行输入一个好友微信号。导出时会先通过微信号查询好友 wxid，再导出聊天记录。",
        "columns": [
            {
                "key": "wxh",
                "label": "好友微信号",
                "type": "text",
                "placeholder": "输入好友微信号，例如 zhangsan123",
                "required": True,
                "required_message": "好友微信号不能为空",
                "width": "wide",
            },
        ],
    },
    {"key": "export_dir", "aliases": ["save_path"], "label": "导出目录", "type": "text", "default": str(DEFAULT_EXPORT_DIR), "description": "好友消息文件会输出到这个目录，默认使用当前系统下载目录。"},
]


def sanitize_file_name(value):
    return normalize_text(value).translate(str.maketrans({'\\': '_', '/': '_', ':': '_', '*': '_', '?': '_', '"': '_', '<': '_', '>': '_', '|': '_'}))


def resolve_export_dir(config):
    configured_dir = normalize_text(config.get("export_dir") or config.get("save_path") or "")
    return configured_dir or str(DEFAULT_EXPORT_DIR)


def normalize_user_entries(config):
    entries = []
    seen_wechat_ids = set()

    def append_user(wechat_id="", wxpid=None):
        normalized_wechat_id = normalize_text(wechat_id)
        if not normalized_wechat_id or normalized_wechat_id in seen_wechat_ids:
            return
        seen_wechat_ids.add(normalized_wechat_id)
        entries.append({"wxh": normalized_wechat_id, "wxpid": wxpid})

    users = config.get("users")
    if users is None:
        users = config.get("friends")

    if isinstance(users, list):
        for item in users:
            if not isinstance(item, dict):
                append_user(item)
                continue
            append_user(item.get("wxh") or item.get("alias") or item.get("wechat_id") or item.get("account"), item.get("wxpid"))
        return entries

    if isinstance(users, dict):
        for wxh in users:
            append_user(wxh)
        return entries

    for wxh in to_string_list(config.get("wechat_ids") or config.get("wxhs") or config.get("user_ids") or config.get("friends")):
        append_user(wxh)
    return entries


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


def build_message_file_name(user_name, extension, wxpid=None, include_wxpid=False):
    file_name = f"{sanitize_file_name(user_name)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    if include_wxpid and wxpid not in (None, ""):
        file_name = f"{file_name}_wxpid{wxpid}"
    return f"{file_name}.{extension}"


def build_user_directory_name(display_name, wechat_id, wxid):
    base_name = sanitize_file_name(display_name or wechat_id or wxid) or "好友消息"
    suffix = normalize_text(wechat_id or wxid)
    if suffix and suffix != normalize_text(display_name):
        return f"{base_name}({sanitize_file_name(suffix)})"
    return base_name


def iter_friend_wechat_ids(friend):
    candidates = [
        friend.get("wxh"),
        friend.get("alias"),
        friend.get("wechat_id"),
        friend.get("wechatid"),
        friend.get("account"),
        friend.get("user_name"),
    ]
    seen = set()
    for candidate in candidates:
        normalized = normalize_text(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        yield normalized


async def build_user_lookup(context, wxpid):
    users = await context.api.get_user_list(wxpid)
    by_wechat_id = {}
    by_wxid = {}
    for user in users if isinstance(users, list) else []:
        if not isinstance(user, dict):
            continue
        wxid = normalize_text(user.get("wxid"))
        wechat_id = normalize_text(user.get("wxh") or user.get("alias") or "")
        nickname = normalize_text(user.get("remarks") or user.get("nickname") or wechat_id or wxid)
        if not wxid:
            continue
        entry = {"wxid": wxid, "wxh": wechat_id, "nickname": nickname, "wxpid": wxpid}
        by_wxid[wxid] = entry
        for candidate in iter_friend_wechat_ids(user):
            if candidate not in by_wechat_id:
                by_wechat_id[candidate] = entry
    return {"by_wechat_id": by_wechat_id, "by_wxid": by_wxid}


async def export_user_messages(context, reason):
    export_dir = resolve_export_dir(context.config)
    entries = normalize_user_entries(context.config)
    if not export_dir or not entries:
        return {"exported_count": 0, "users": []}

    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)
    default_wxpid_selection = context.config.get("wxpid")
    default_target_wxpids = await resolve_wxpid_targets(context.api, default_wxpid_selection)
    user_lookup_cache = {}
    start_time, end_time = resolve_time_window(context.config)
    max_count = max(1, int(context.config.get("max_count", 500) or 500))
    extension = normalize_text(context.config.get("file_type") or context.config.get("output_format") or "jsonl").lower() or "jsonl"
    if extension == "txt":
        extension = "jsonl"
    if extension not in {"jsonl", "json"}:
        extension = "jsonl"

    reports = []
    if not default_target_wxpids and default_wxpid_selection not in (None, ""):
        context.logger.warning("好友消息汇总插件当前没有可用的微信进程", {"reason": reason, "wxpid_selection": default_wxpid_selection})

    for entry in entries:
        entry_wxpid_selection = entry.get("wxpid") if entry.get("wxpid") not in (None, "") else default_wxpid_selection
        target_wxpids = default_target_wxpids if entry.get("wxpid") in (None, "") else await resolve_wxpid_targets(context.api, entry.get("wxpid"))
        if not target_wxpids:
            context.logger.warning("好友消息汇总插件当前没有可用的微信进程", {"reason": reason, "wechat_id": entry.get("wxh"), "wxpid_selection": entry_wxpid_selection})
            continue

        include_wxpid_in_file_name = len(target_wxpids) > 1
        for wxpid in target_wxpids:
            if wxpid not in user_lookup_cache:
                user_lookup_cache[wxpid] = await build_user_lookup(context, wxpid)

            lookup = user_lookup_cache[wxpid]
            input_wechat_id = normalize_text(entry.get("wxh"))
            resolved_user = lookup["by_wechat_id"].get(input_wechat_id) or lookup["by_wxid"].get(input_wechat_id)
            if not resolved_user:
                context.logger.warning("好友消息汇总插件未找到目标好友", {"reason": reason, "wechat_id": input_wechat_id, "wxpid": wxpid})
                continue

            messages = await context.api.get_chat_messages(wxid=resolved_user["wxid"], start_time=start_time, end_time=end_time, max_count=max_count, wxpid=wxpid)
            user_dir = export_path / build_user_directory_name(resolved_user["nickname"], resolved_user["wxh"], resolved_user["wxid"])
            user_dir.mkdir(parents=True, exist_ok=True)
            file_path = user_dir / build_message_file_name(resolved_user["nickname"] or resolved_user["wxh"] or resolved_user["wxid"], extension, wxpid, include_wxpid_in_file_name)
            write_messages(file_path, messages if isinstance(messages, list) else [], extension)
            report = {
                "wechat_id": input_wechat_id,
                "wxid": resolved_user["wxid"],
                "user_name": resolved_user["nickname"],
                "wxpid": wxpid,
                "file_path": str(file_path),
                "message_count": len(messages) if isinstance(messages, list) else 0,
                "start_time": start_time,
                "end_time": end_time,
            }
            reports.append(report)
            context.logger.info("好友消息已导出", report)

    payload = {
        "reason": reason,
        "wxpid_selection": default_wxpid_selection,
        "target_wxpids": default_target_wxpids,
        "exported_count": len(reports),
        "users": reports,
        "start_time": start_time,
        "end_time": end_time,
    }
    context.state.namespace("user_msg_summary").set("last_report", payload)
    return payload


async def execute(context):
    report = await export_user_messages(context, "manual-execute")
    if report.get("exported_count"):
        context.logger.info("好友消息汇总导出已完成", report)
        return {"handled": True, "detail": f"已导出 {report['exported_count']} 个好友的聊天记录", "data": report}
    return {"handled": False, "detail": "没有可导出的好友聊天记录", "data": report}
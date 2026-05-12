import os
import json
from csv import writer
from datetime import datetime
from io import StringIO
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from ._plugin_sdk import normalize_text, resolve_wxpid_targets


name = "export_contacts"
description = "导出当前微信好友列表信息到 CSV 表格"
category = "functional"
message_dependent = False


WINDOWS_DOWNLOADS_FOLDER_GUID = "{374DE290-123F-4565-9164-39C4925E467B}"
WINDOWS_DOWNLOADS_REGISTRY_KEYS = (
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
)

PREFERRED_CSV_FIELDS = [
    "wxid",
    "wxh",
    "alias",
    "nickname",
    "remarks",
    "gender",
    "signature",
    "country",
    "province",
    "city",
    "big_head_url",
    "small_head_url",
]


def get_default_save_path():
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


DEFAULT_SAVE_PATH = get_default_save_path()


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
        "key": "save_path",
        "aliases": ["export_dir"],
        "label": "保存路径",
        "type": "text",
        "default": str(DEFAULT_SAVE_PATH),
        "description": "好友列表 CSV 会保存到这个目录，默认使用当前系统下载目录。",
    },
]


def resolve_save_path(config):
    configured_dir = normalize_text(config.get("save_path") or config.get("export_dir") or "")
    return configured_dir or str(DEFAULT_SAVE_PATH)


def sanitize_file_name(value):
    text = normalize_text(value)
    return text.translate(str.maketrans({'\\': '_', '/': '_', ':': '_', '*': '_', '?': '_', '"': '_', '<': '_', '>': '_', '|': '_'}))


def build_csv_fields(contacts):
    seen_fields = set()
    extra_fields = []
    for contact in contacts if isinstance(contacts, list) else []:
        if not isinstance(contact, dict):
            continue
        for key in contact:
            normalized_key = normalize_text(key)
            if not normalized_key or normalized_key in seen_fields:
                continue
            seen_fields.add(normalized_key)
            if normalized_key not in PREFERRED_CSV_FIELDS:
                extra_fields.append(normalized_key)

    ordered_fields = [field for field in PREFERRED_CSV_FIELDS if field in seen_fields]
    ordered_fields.extend(sorted(extra_fields))
    return ordered_fields or list(PREFERRED_CSV_FIELDS)


def serialize_csv_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_csv(contacts):
    fields = build_csv_fields(contacts)
    buffer = StringIO()
    csv_writer = writer(buffer)
    csv_writer.writerow(fields)
    for contact in contacts if isinstance(contacts, list) else []:
        row = contact if isinstance(contact, dict) else {}
        csv_writer.writerow([serialize_csv_value(row.get(field)) for field in fields])
    return "\ufeff" + buffer.getvalue(), fields


def build_export_file_path(export_path, wxpid=None, include_wxpid=False):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem = f"好友列表_{timestamp}"
    if include_wxpid and wxpid not in (None, ""):
        file_stem = f"{file_stem}_wxpid{wxpid}"
    return export_path / f"{sanitize_file_name(file_stem)}.csv"


async def export_contacts(context, reason):
    save_path = resolve_save_path(context.config)
    wxpid_selection = context.config.get("wxpid")
    target_wxpids = await resolve_wxpid_targets(context.api, wxpid_selection)
    report = {
        "reason": reason,
        "wxpid_selection": wxpid_selection,
        "target_wxpids": target_wxpids,
        "save_path": save_path,
        "exported_file_count": 0,
        "failed_count": 0,
        "exports": [],
    }

    if not target_wxpids:
        report["error"] = "missing-live-wxpids"
        context.logger.warning("好友列表导出跳过，当前没有可用的微信进程", report)
        context.state.namespace("export_contacts").set("last_report", report)
        return report

    export_path = Path(save_path)
    export_path.mkdir(parents=True, exist_ok=True)
    include_wxpid_in_file_name = len(target_wxpids) > 1
    context.logger.info("开始导出好友列表", report)

    for wxpid in target_wxpids:
        try:
            contacts = await context.api.get_user_list(wxpid)
        except Exception as exc:
            failure = {
                "reason": reason,
                "wxpid": wxpid,
                "status": "failed",
                "error": str(exc),
            }
            report["exports"].append(failure)
            report["failed_count"] += 1
            context.logger.warning("导出好友列表失败", failure)
            continue

        if not isinstance(contacts, list):
            context.logger.warning("好友列表接口返回了非列表结果，已按空列表导出", {"reason": reason, "wxpid": wxpid, "result_type": type(contacts).__name__})
            contacts = []

        csv_text, fields = render_csv(contacts)
        file_path = build_export_file_path(export_path, wxpid, include_wxpid_in_file_name)
        file_path.write_text(csv_text, encoding="utf-8")
        export_report = {
            "reason": reason,
            "wxpid": wxpid,
            "status": "exported",
            "file_path": str(file_path),
            "contact_count": len(contacts),
            "field_count": len(fields),
            "fields": fields,
        }
        report["exports"].append(export_report)
        report["exported_file_count"] += 1
        context.logger.info("已导出好友列表", export_report)

    context.logger.info("好友列表导出流程结束", report)
    context.state.namespace("export_contacts").set("last_report", report)
    return report


async def execute(context):
    report = await export_contacts(context, "manual-execute")
    if report.get("error") == "missing-live-wxpids":
        return {"handled": False, "detail": "当前没有已登录的微信进程", "data": report}
    if report.get("exported_file_count"):
        detail = f"已导出 {report['exported_file_count']} 份好友列表 CSV"
        if report.get("failed_count"):
            detail = f"{detail}，另有 {report['failed_count']} 个微信进程导出失败"
        return {"handled": True, "detail": detail, "data": report}
    return {"handled": False, "detail": "本次没有成功导出任何好友列表", "data": report}
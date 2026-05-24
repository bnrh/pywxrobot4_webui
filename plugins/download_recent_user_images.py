from datetime import datetime, timedelta
from typing import Any

from ._plugin_sdk import MESSAGE_TYPES, format_date_time, normalize_text, resolve_wxpid_targets, sleep


name = "download_recent_user_images"
description = "周期扫描 ChatName2Id 中最近活跃用户，并下载时间窗口内的图片消息"
category = "functional"
message_dependent = False
schedule = {
    "interval_field": "interval_seconds",
    "default_interval_seconds": 3,
}


DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_INTERVAL_SECONDS = 3.0
DEFAULT_MAX_COUNT_PER_USER = 2000
DEFAULT_MESSAGE_RESOURCE_DB_NAME = "message_resource.db"
DOWNLOAD_HISTORY_LIMIT = 5000
DOWNLOAD_HISTORY_RETENTION_BUFFER_SECONDS = 3600
MAX_REPORT_ITEMS = 100


def build_default_start_time_text(reference_time: datetime | None = None) -> str:
    base_time = reference_time if isinstance(reference_time, datetime) else datetime.now()
    return format_date_time(base_time - timedelta(hours=DEFAULT_LOOKBACK_HOURS))


config_schema = [
    {
        "key": "wxpid",
        "label": "微信进程",
        "type": "select",
        "options_source": "wxpid_options",
        "required": True,
        "required_message": "微信进程不能为空",
        "full_width": False,
        "description": "使用这个微信进程读取 ChatName2Id 与聊天记录。",
    },
    {
        "key": "start_time",
        "label": "起始时间",
        "type": "text",
        "default": build_default_start_time_text(),
        "full_width": False,
        "placeholder": "yyyy-MM-dd HH:mm:ss",
        "description": "默认填充当前时间往前 24 小时，可手动修改。",
    },
    {
        "key": "interval_seconds",
        "label": "执行间隔秒数",
        "type": "number",
        "default": DEFAULT_INTERVAL_SECONDS,
        "min": 0,
        "max": 3600,
        "step": 0.1,
        "full_width": False,
        "description": "插件启用后每隔多少秒巡检一次；同一轮发现多张新图片时，也会按这个间隔串行下载。",
    },
    {
        "key": "max_count_per_user",
        "label": "单个用户最多扫描消息数",
        "type": "number",
        "default": DEFAULT_MAX_COUNT_PER_USER,
        "min": 1,
        "max": 10000,
        "step": 1,
        "full_width": False,
        "description": "每个命中用户在时间窗口内最多读取多少条聊天消息。",
    },
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
]


def parse_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = normalize_text(value)
    if not text:
        return None
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(float(text))
    except ValueError:
        return None


def parse_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = normalize_text(value)
    if not text:
        return None
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        timestamp = int(text)
        if abs(timestamp) >= 1_000_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp)

    normalized_text = text.replace("T", " ")
    for format_string in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized_text, format_string)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"无法解析起始时间: {value}") from exc


def resolve_time_window(config: dict[str, Any]) -> tuple[datetime, datetime]:
    now = datetime.now()
    explicit_start = parse_datetime_value(config.get("start_time"))
    start_time = explicit_start or (now - timedelta(hours=DEFAULT_LOOKBACK_HOURS))
    if start_time > now:
        raise ValueError("起始时间不能晚于当前时间")
    return start_time, now


def resolve_interval_seconds(config: dict[str, Any]) -> float:
    return max(0.0, parse_float(config.get("interval_seconds"), DEFAULT_INTERVAL_SECONDS))


def resolve_max_count_per_user(config: dict[str, Any]) -> int:
    configured = parse_int(config.get("max_count_per_user"))
    if configured is None:
        return DEFAULT_MAX_COUNT_PER_USER
    return max(1, min(10000, configured))


def resolve_download_flag(config: dict[str, Any], context: Any) -> int:
    configured = parse_int(config.get("flag"))
    if configured is not None:
        return max(1, min(3, configured))
    return int(getattr(context.settings, "image_download_flag", 3) or 3)


def normalize_mapping_key(value: Any) -> str:
    return normalize_text(value).lower()


def get_mapping_value(item: Any, *keys: str) -> Any:
    if not isinstance(item, dict):
        return None
    normalized_map = {
        normalize_mapping_key(key): value
        for key, value in item.items()
    }
    for key in keys:
        normalized_key = normalize_mapping_key(key)
        if normalized_key in normalized_map:
            return normalized_map[normalized_key]
    return None


def normalize_row_list(rows: Any, column_names: list[Any] | None = None) -> list[dict[str, Any]]:
    normalized_rows: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return normalized_rows
    normalized_columns = [normalize_text(column_name) or f"col_{index}" for index, column_name in enumerate(column_names or [])]
    for row in rows:
        if isinstance(row, dict):
            normalized_rows.append(dict(row))
            continue
        if isinstance(row, (list, tuple)) and normalized_columns:
            normalized_rows.append(
                {
                    normalized_columns[index]: row[index] if index < len(row) else None
                    for index in range(len(normalized_columns))
                }
            )
    return normalized_rows


def extract_rows_from_payload(payload: Any) -> list[dict[str, Any]] | None:
    if isinstance(payload, list):
        return normalize_row_list(payload)
    if not isinstance(payload, dict):
        return None

    columns = payload.get("columns") or payload.get("header") or payload.get("headers") or payload.get("fields")
    if isinstance(columns, list):
        for key in ("rows", "items", "data", "list", "result", "results"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return normalize_row_list(candidate, columns)

    for key in ("data", "rows", "items", "list", "result", "results"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return normalize_row_list(candidate)
        if isinstance(candidate, dict):
            extracted = extract_rows_from_payload(candidate)
            if extracted is not None:
                return extracted
    return None


def extract_sql_rows(payload: Any) -> list[dict[str, Any]]:
    extracted = extract_rows_from_payload(payload)
    return extracted if extracted is not None else []


def is_success_ret(value: Any) -> bool:
    return value in (None, "", 0, "0", True)


def extract_api_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if is_success_ret(payload.get("ret")):
        return ""
    for key in ("error", "errmsg", "err_msg", "message", "msg", "detail"):
        text = normalize_text(payload.get(key))
        if text:
            return text
    return f"ret={payload.get('ret')}"


def describe_update_time_scale(scale: int) -> str:
    if scale == 1_000_000:
        return "microseconds"
    if scale == 1000:
        return "milliseconds"
    return "seconds"


def detect_update_time_scale(max_update_time: Any) -> int:
    numeric_value = abs(parse_int(max_update_time) or 0)
    if numeric_value >= 100_000_000_000_000:
        return 1_000_000
    if numeric_value >= 100_000_000_000:
        return 1000
    return 1


def is_chatroom_wxid(wxid: str) -> bool:
    return normalize_text(wxid).endswith("@chatroom")


def resolve_message_type(message: dict[str, Any]) -> int | None:
    for key in ("local_type", "msg_type", "type", "localtype", "msgtype"):
        numeric_value = parse_int(get_mapping_value(message, key))
        if numeric_value is not None:
            return numeric_value
    return None


def is_image_message(message: dict[str, Any]) -> bool:
    return resolve_message_type(message) == int(MESSAGE_TYPES.IMAGE)


def resolve_message_id(message: dict[str, Any]) -> str:
    for key in ("msgid", "server_id", "msgsvrid", "id"):
        value = get_mapping_value(message, key)
        normalized = normalize_text(value)
        if normalized:
            return normalized
    return ""


def resolve_message_timestamp(message: dict[str, Any]) -> int:
    for key in ("timestamp", "create_time", "createtime", "time", "msg_time"):
        raw_value = get_mapping_value(message, key)
        parsed = parse_datetime_value(raw_value)
        if parsed is not None:
            return int(parsed.timestamp())
        numeric_value = parse_int(raw_value)
        if numeric_value is not None:
            if abs(numeric_value) >= 1_000_000_000_000:
                numeric_value //= 1000
            return numeric_value
    return 0


def build_download_history_key(wxpid: int | None, wxid: str, msgid: str) -> str:
    return f"{wxpid or 0}:{normalize_text(wxid)}:{normalize_text(msgid)}"


def load_download_history(state: Any) -> list[dict[str, Any]]:
    records = state.get("history", [])
    normalized_records: list[dict[str, Any]] = []
    for item in records if isinstance(records, list) else []:
        if not isinstance(item, dict):
            continue
        key = normalize_text(item.get("key"))
        downloaded_at = parse_int(item.get("downloaded_at")) or 0
        if not key:
            continue
        normalized_records.append({"key": key, "downloaded_at": max(0, downloaded_at)})
    return normalized_records[-DOWNLOAD_HISTORY_LIMIT:]


def prune_download_history(records: list[dict[str, Any]], min_timestamp: int) -> list[dict[str, Any]]:
    keep_after = max(0, int(min_timestamp or 0) - DOWNLOAD_HISTORY_RETENTION_BUFFER_SECONDS)
    filtered = [
        item
        for item in records
        if normalize_text(item.get("key")) and ((parse_int(item.get("downloaded_at")) or 0) >= keep_after)
    ]
    return filtered[-DOWNLOAD_HISTORY_LIMIT:]


def append_limited(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if len(items) < MAX_REPORT_ITEMS:
        items.append(item)


async def resolve_wxpid(context: Any) -> int | None:
    targets = await resolve_wxpid_targets(context.api, context.config.get("wxpid"))
    return targets[0] if targets else None


async def query_update_time_scale(context: Any, wxpid: int, db_name: str) -> int:
    payload = await context.api.exec_sql(
        sql="SELECT MAX(update_time) AS max_update_time FROM ChatName2Id",
        db_name=db_name,
        wxpid=wxpid,
    )
    rows = extract_sql_rows(payload)
    if not rows:
        error_text = extract_api_error(payload)
        if error_text:
            raise RuntimeError(error_text)
        return 1
    return detect_update_time_scale(get_mapping_value(rows[0], "max_update_time"))


async def query_recent_users(context: Any, wxpid: int, db_name: str, start_update_time: int) -> list[dict[str, Any]]:
    sql = (
        "SELECT user_name, update_time "
        "FROM ChatName2Id "
        f"WHERE update_time > {int(start_update_time)} "
        "AND user_name IS NOT NULL "
        "AND TRIM(user_name) != '' "
        "ORDER BY update_time ASC, user_name ASC"
    )
    payload = await context.api.exec_sql(sql=sql, db_name=db_name, wxpid=wxpid)
    rows = extract_sql_rows(payload)
    if not rows:
        error_text = extract_api_error(payload)
        if error_text:
            raise RuntimeError(error_text)
        return []

    users: list[dict[str, Any]] = []
    seen_wxids: set[str] = set()
    for row in rows:
        wxid = normalize_text(get_mapping_value(row, "user_name"))
        if not wxid or is_chatroom_wxid(wxid) or wxid in seen_wxids:
            continue
        seen_wxids.add(wxid)
        users.append(
            {
                "wxid": wxid,
                "update_time": parse_int(get_mapping_value(row, "update_time")) or 0,
            }
        )
    return users


def build_report_detail(report: dict[str, Any]) -> str:
    downloaded_count = int(report.get("downloaded_count") or 0)
    failed_count = int(report.get("failed_count") or 0)
    matched_image_count = int(report.get("matched_image_count") or 0)
    scanned_user_count = int(report.get("scanned_user_count") or 0)
    if downloaded_count > 0 and failed_count > 0:
        return f"已下载 {downloaded_count} 张图片，另有 {failed_count} 张下载失败"
    if downloaded_count > 0:
        return f"已下载 {downloaded_count} 张图片"
    if failed_count > 0:
        return f"扫描完成，但有 {failed_count} 张图片下载失败"
    if matched_image_count > 0:
        return "没有新的图片需要下载"
    if scanned_user_count > 0:
        return "命中了最近活跃用户，但时间窗口内没有图片消息"
    return "起始时间之后没有命中用户"


async def run_download_cycle(context: Any, reason: str) -> dict[str, Any]:
    runtime_state = context.state.namespace("runtime")
    history_state = context.state.namespace("downloads")

    try:
        start_time, end_time = resolve_time_window(context.config)
    except ValueError as exc:
        report = {
            "reason": reason,
            "error": str(exc),
            "downloaded_count": 0,
            "failed_count": 0,
        }
        runtime_state.set("last_report", report)
        return report

    wxpid = await resolve_wxpid(context)
    if wxpid is None:
        report = {
            "reason": reason,
            "error": "当前没有可用的微信进程",
            "downloaded_count": 0,
            "failed_count": 0,
        }
        runtime_state.set("last_report", report)
        return report

    start_time_text = format_date_time(start_time)
    end_time_text = format_date_time(end_time)
    interval_seconds = resolve_interval_seconds(context.config)
    max_count_per_user = resolve_max_count_per_user(context.config)
    db_name = DEFAULT_MESSAGE_RESOURCE_DB_NAME
    history = prune_download_history(load_download_history(history_state), int(start_time.timestamp()))
    history_keys = {item["key"] for item in history}
    update_time_scale = await query_update_time_scale(context, wxpid, db_name)
    start_update_time = int(start_time.timestamp()) * update_time_scale
    users = await query_recent_users(context, wxpid, db_name, start_update_time)
    flag = resolve_download_flag(context.config, context)

    report = {
        "reason": reason,
        "error": "",
        "wxpid": wxpid,
        "db_name": db_name,
        "start_time": start_time_text,
        "end_time": end_time_text,
        "start_update_time": start_update_time,
        "update_time_unit": describe_update_time_scale(update_time_scale),
        "interval_seconds": interval_seconds,
        "max_count_per_user": max_count_per_user,
        "scanned_user_count": len(users),
        "matched_user_count": 0,
        "failed_user_count": 0,
        "scanned_message_count": 0,
        "matched_image_count": 0,
        "downloaded_count": 0,
        "skipped_downloaded_count": 0,
        "skipped_missing_msgid_count": 0,
        "failed_count": 0,
        "users": [],
        "downloads": [],
        "failures": [],
    }

    download_attempt_count = 0
    for user in users:
        wxid = user["wxid"]
        try:
            messages = await context.api.get_chat_messages(
                wxid=wxid,
                start_time=start_time_text,
                end_time=end_time_text,
                max_count=max_count_per_user,
                wxpid=wxpid,
            )
        except Exception as exc:
            report["failed_user_count"] += 1
            failure = {
                "wxid": wxid,
                "update_time": user["update_time"],
                "error": str(exc),
            }
            append_limited(report["failures"], failure)
            context.logger.warning("读取用户聊天记录失败", failure)
            continue

        if not isinstance(messages, list):
            report["failed_user_count"] += 1
            failure = {
                "wxid": wxid,
                "update_time": user["update_time"],
                "error": "聊天记录接口未返回列表",
            }
            append_limited(report["failures"], failure)
            context.logger.warning("读取用户聊天记录失败", failure)
            continue

        report["scanned_message_count"] += len(messages)
        image_messages = [message for message in messages if isinstance(message, dict) and is_image_message(message)]
        if not image_messages:
            continue

        report["matched_user_count"] += 1
        user_report = {
            "wxid": wxid,
            "update_time": user["update_time"],
            "image_count": len(image_messages),
            "downloaded_count": 0,
            "skipped_downloaded_count": 0,
            "skipped_missing_msgid_count": 0,
            "failed_count": 0,
        }

        sorted_image_messages = sorted(
            image_messages,
            key=lambda item: (resolve_message_timestamp(item), resolve_message_id(item)),
        )

        for message in sorted_image_messages:
            report["matched_image_count"] += 1
            msgid = resolve_message_id(message)
            if not msgid:
                report["skipped_missing_msgid_count"] += 1
                user_report["skipped_missing_msgid_count"] += 1
                continue

            history_key = build_download_history_key(wxpid, wxid, msgid)
            if history_key in history_keys:
                report["skipped_downloaded_count"] += 1
                user_report["skipped_downloaded_count"] += 1
                continue

            if download_attempt_count > 0 and interval_seconds > 0:
                await sleep(interval_seconds * 1000)
            download_attempt_count += 1

            response = await context.api.download_cdn_image(
                msgid=msgid,
                wxid=wxid,
                wxpid=wxpid,
                flag=flag,
                wait=False,
            )
            response_payload = dict(response or {}) if isinstance(response, dict) else {}
            download_path = normalize_text(response_payload.get("path"))
            if download_path or is_success_ret(response_payload.get("ret")):
                history_keys.add(history_key)
                history.append({"key": history_key, "downloaded_at": int(end_time.timestamp())})
                history = prune_download_history(history, int(start_time.timestamp()))
                report["downloaded_count"] += 1
                user_report["downloaded_count"] += 1
                download_record = {
                    "wxid": wxid,
                    "msgid": msgid,
                    "path": download_path,
                    "ret": response_payload.get("ret"),
                }
                append_limited(report["downloads"], download_record)
                context.logger.info("已下载近期用户图片", download_record)
                continue

            error_text = extract_api_error(response_payload) or "下载接口未返回成功结果"
            report["failed_count"] += 1
            user_report["failed_count"] += 1
            failure = {
                "wxid": wxid,
                "msgid": msgid,
                "error": error_text,
                "response": response_payload,
            }
            append_limited(report["failures"], failure)
            context.logger.warning("下载近期用户图片失败", failure)

        append_limited(report["users"], user_report)

    history = prune_download_history(history, int(start_time.timestamp()))
    history_state.set("history", history)
    report["detail"] = build_report_detail(report)
    runtime_state.set("last_report", report)

    if report["downloaded_count"] > 0 or report["failed_count"] > 0:
        context.logger.info(
            "近期用户图片扫描完成",
            {
                "reason": reason,
                "wxpid": wxpid,
                "downloaded_count": report["downloaded_count"],
                "failed_count": report["failed_count"],
                "matched_user_count": report["matched_user_count"],
                "matched_image_count": report["matched_image_count"],
            },
        )

    return report


async def execute(context):
    report = await run_download_cycle(context, "manual-execute")
    if report.get("error"):
        return {
            "handled": False,
            "detail": report["error"],
            "data": report,
        }
    return {
        "handled": bool(report.get("downloaded_count") or report.get("matched_image_count") or report.get("scanned_user_count")),
        "detail": report.get("detail") or "执行完成",
        "data": report,
    }


async def tick(context):
    report = await run_download_cycle(context, "tick")
    if report.get("error"):
        context.logger.warning("近期用户图片扫描失败", {"reason": "tick", "error": report["error"]})
        return {"handled": False, "detail": report["error"], "data": report}
    if report.get("downloaded_count") or report.get("failed_count"):
        return {
            "handled": True,
            "detail": report.get("detail") or "周期扫描完成",
            "data": report,
        }
    return {"handled": False, "detail": "", "data": report}
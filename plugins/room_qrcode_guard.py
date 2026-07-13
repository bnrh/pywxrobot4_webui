from pathlib import Path
from time import time

from config import PROJECT_ROOT
from ._plugin_sdk import normalize_text, random_between, sleep, unique_strings, is_truthy

try:
    import numpy as np
    from PIL import Image, UnidentifiedImageError
    import zxingcpp
except ImportError as exc:
    np = None
    Image = None
    UnidentifiedImageError = OSError
    zxingcpp = None
    DETECTION_IMPORT_ERROR = exc
else:
    DETECTION_IMPORT_ERROR = None


name = "room_qrcode_guard"
description = "检测群聊图片是否包含二维码，提醒后可移出发送成员"
event_filters = ["image"]

PENDING_KICK_TTL_MS = 30_000
PROCESS_DELAY_MS = 2_000
DEFAULT_WARNING_TEMPLATE = "当前群不允许发送包含二维码的图片，请遵守群规。"

config_schema = [
    {
        "key": "kick_after_warning",
        "label": "是否踢出群聊",
        "type": "checkbox",
        "default": True,
        "full_width": False,
        "description": "开启后会先发送群内提醒并 @ 违规成员，再等待 3 到 5 秒将其移出群聊。",
    },
    {
        "key": "warning_template",
        "label": "警告信息模版",
        "type": "text",
        "default": DEFAULT_WARNING_TEMPLATE,
        "placeholder": "支持 @{user_name}、{user_name}、{room_name} 占位符",
        "description": "支持 @{user_name}、{user_name}、{room_name} 占位符；若未填写 @{user_name}，插件会自动在消息前追加 @ 提示。",
    },
    {
        "key": "room_ids",
        "label": "生效的群聊列表",
        "type": "searchable-multi-checkbox",
        "options_source": "room_options",
        "default": [],
        "search_placeholder": "输入群名称或 wxid 搜索",
        "show_selected_label": "仅显示已勾选群聊",
        "empty_text": "没有匹配到群聊。",
        "empty_no_options_text": "当前还没有可选群聊，请先确保心跳与群聊列表已加载。",
        "description": "仅在选中的群聊中检测图片二维码；未选择任何群聊时，插件不会生效。",
    },
]




def normalize_room_ids(config):
    if not isinstance(config, dict):
        return []
    raw_value = config.get("room_ids")
    if raw_value in (None, ""):
        raw_value = config.get("rooms")
    return [roomid for roomid in unique_strings(raw_value) if roomid.endswith("@chatroom")]


def find_room_member(members, sender_wxid):
    normalized_sender_wxid = normalize_text(sender_wxid)
    if not normalized_sender_wxid:
        return None
    for member in members if isinstance(members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = normalize_text(member.get("username") or member.get("wxid"))
        if member_wxid == normalized_sender_wxid:
            return member
    return None


def is_default_whitelist_member(member):
    if not isinstance(member, dict):
        return False
    return is_truthy(member.get("is_owner")) or is_truthy(member.get("is_admin"))


async def can_current_account_remove_members(context, roomid, wxpid, self_wxid, log_payload=None):
    payload = dict(log_payload or {})
    normalized_self_wxid = normalize_text(self_wxid)
    if not normalized_self_wxid:
        context.logger.warning(
            "群二维码检测插件无法确认当前账号微信号，已跳过移除群成员",
            {**payload, "roomid": roomid, "wxpid": wxpid},
        )
        return False

    try:
        room_members = await context.api.get_room_members(roomid, wxpid)
    except Exception as exc:
        context.logger.warning(
            "群二维码检测插件移人前读取群成员失败，已跳过移除群成员",
            {**payload, "roomid": roomid, "self_wxid": normalized_self_wxid, "wxpid": wxpid, "error": str(exc)},
        )
        return False

    if not isinstance(room_members, list):
        context.logger.warning(
            "群二维码检测插件移人前读取群成员返回了非列表结果，已跳过移除群成员",
            {**payload, "roomid": roomid, "self_wxid": normalized_self_wxid, "wxpid": wxpid, "result_type": type(room_members).__name__},
        )
        return False

    self_member = find_room_member(room_members, normalized_self_wxid)
    if is_default_whitelist_member(self_member):
        return True

    context.logger.warning(
        "群二维码检测插件当前账号不是群主或管理员，已跳过移除群成员",
        {
            **payload,
            "roomid": roomid,
            "self_wxid": normalized_self_wxid,
            "wxpid": wxpid,
            "self_is_owner": is_truthy(self_member.get("is_owner")) if isinstance(self_member, dict) else False,
            "self_is_admin": is_truthy(self_member.get("is_admin")) if isinstance(self_member, dict) else False,
        },
    )
    return False


def get_active_pending_kick(pending_state, pending_key):
    pending = pending_state.get(pending_key)
    if not isinstance(pending, dict):
        return None
    try:
        created_at_ms = int(pending.get("created_at_ms") or 0)
    except (TypeError, ValueError):
        created_at_ms = 0
    now_ms = int(time() * 1000)
    if created_at_ms <= 0 or now_ms - created_at_ms > PENDING_KICK_TTL_MS:
        pending_state.delete(pending_key)
        return None
    return pending


async def resolve_self_wxid(context, wxpid):
    users = await context.api.get_logged_in_users()
    for item in users if isinstance(users, list) else []:
        try:
            if wxpid is None or int(item.get("wxpid") or item.get("pid") or -1) == int(wxpid):
                return normalize_text(item.get("wxid"))
        except (TypeError, ValueError):
            continue
    return ""


async def resolve_sender_name(event, context, roomid, sender_wxid, room_members=None):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        display_name = normalize_text(first_non_empty("room_sender_display_name", "sender_display_name"))
        if display_name and display_name != sender_wxid:
            return display_name

    members = room_members if isinstance(room_members, list) else await context.api.get_room_members(roomid, event.normalized_wxpid)
    for member in members if isinstance(members, list) else []:
        if not isinstance(member, dict):
            continue
        member_wxid = normalize_text(member.get("username") or member.get("wxid"))
        if member_wxid != sender_wxid:
            continue
        return normalize_text(member.get("room_nick_name") or member.get("nick_name") or member.get("remarks") or member_wxid) or sender_wxid

    return sender_wxid or "该成员"


def resolve_room_name(event, roomid):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        room_name = normalize_text(first_non_empty("conversation_display_name", "title_display"))
        if room_name and room_name != roomid:
            return room_name
    return roomid or "当前群聊"


def render_warning_text(template, sender_name, room_name):
    content = str(template or "").strip() or DEFAULT_WARNING_TEMPLATE
    mention_text = f"@{sender_name}\u2005"
    inserted_mention = False
    if "@{user_name}" in content:
        content = content.replace("@{user_name}", mention_text)
        inserted_mention = True
    content = content.replace("{user_name}", sender_name)
    content = content.replace("{room_name}", room_name)
    content = content.strip()
    if not inserted_mention:
        content = f"{mention_text}{content}".strip()
    return content


def resolve_downloaded_image_path(response):
    if not isinstance(response, dict):
        return None

    candidates = []
    for key in ("path", "save_path", "file_path", "download_path"):
        value = response.get(key)
        if value not in (None, ""):
            candidates.append(value)

    payload = response.get("data")
    if isinstance(payload, dict):
        for key in ("path", "save_path", "file_path", "download_path"):
            value = payload.get(key)
            if value not in (None, ""):
                candidates.append(value)

    for raw_path in candidates:
        path_text = normalize_text(raw_path)
        if not path_text:
            continue
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        if candidate.exists():
            return candidate
    return None


def detect_qrcode(image_path):
    if zxingcpp is None or np is None or Image is None:
        raise RuntimeError(f"缺少二维码识别依赖：{DETECTION_IMPORT_ERROR}")

    with Image.open(image_path) as image:
        pixel_array = np.asarray(image.convert("RGB"))

    barcode_items = zxingcpp.read_barcodes(pixel_array)
    qrcode_formats = []
    for barcode in barcode_items if isinstance(barcode_items, list) else barcode_items:
        format_value = getattr(getattr(barcode, "format", None), "name", "") or str(getattr(barcode, "format", ""))
        if "qr" in format_value.lower():
            qrcode_formats.append(format_value or "QRCode")

    return {
        "has_qrcode": bool(qrcode_formats),
        "qrcode_count": len(qrcode_formats),
        "formats": qrcode_formats,
    }


def build_log_payload(event, roomid, sender_wxid, sender_name, room_name, image_path, detection_result):
    return {
        "roomid": roomid,
        "room_name": room_name,
        "sender_wxid": sender_wxid,
        "sender_name": sender_name,
        "wxpid": event.normalized_wxpid,
        "msgid": event.normalized_msgid,
        "image_path": str(image_path),
        "qrcode_count": int(detection_result.get("qrcode_count") or 0),
        "formats": list(detection_result.get("formats") or []),
    }


async def startup(context):
    if DETECTION_IMPORT_ERROR is not None:
        context.logger.error(
            "群二维码检测插件缺少依赖，当前不会执行二维码检测",
            {
                "dependency": "zxing-cpp",
                "import_error": str(DETECTION_IMPORT_ERROR),
            },
        )


async def handle_message(event, context):
    roomid = normalize_text(event.conversation_wxid)
    if not roomid or not roomid.endswith("@chatroom"):
        return {"handled": False, "detail": ""}

    if not event.is_image:
        return {"handled": False, "detail": ""}

    active_room_ids = set(normalize_room_ids(context.config))
    if not active_room_ids or roomid not in active_room_ids:
        return {"handled": False, "detail": ""}

    if DETECTION_IMPORT_ERROR is not None:
        return {"handled": False, "detail": ""}

    msgid = normalize_text(event.normalized_msgid)
    sender_wxid = normalize_text(event.sender_wxid)
    if not msgid or not sender_wxid:
        return {"handled": False, "detail": ""}

    await sleep(PROCESS_DELAY_MS)

    self_wxid = await resolve_self_wxid(context, event.normalized_wxpid)
    if self_wxid and sender_wxid == self_wxid:
        return {"handled": False, "detail": ""}

    try:
        room_members = await context.api.get_room_members(roomid, event.normalized_wxpid)
    except Exception as exc:
        context.logger.warning(
            "群二维码检测插件读取群成员失败，已跳过本次校验",
            {"roomid": roomid, "sender_wxid": sender_wxid, "wxpid": event.normalized_wxpid, "error": str(exc)},
        )
        return {"handled": False, "detail": ""}

    if not isinstance(room_members, list):
        context.logger.warning(
            "群二维码检测插件读取群成员返回了非列表结果，已跳过本次校验",
            {"roomid": roomid, "sender_wxid": sender_wxid, "wxpid": event.normalized_wxpid, "result_type": type(room_members).__name__},
        )
        return {"handled": False, "detail": ""}

    sender_member = find_room_member(room_members, sender_wxid)
    if is_default_whitelist_member(sender_member):
        return {"handled": False, "detail": ""}

    try:
        download_response = await context.api.download_cdn_image(
            msgid=msgid,
            wxid=roomid,
            wxpid=event.normalized_wxpid,
            flag=1,
            wait=True,
            timeout=int(context.settings.image_download_timeout or 15),
        )
        image_path = resolve_downloaded_image_path(download_response)
        if image_path is None:
            context.logger.warning(
                "群二维码检测插件未找到图片下载结果路径，已跳过本次校验",
                {"roomid": roomid, "sender_wxid": sender_wxid, "msgid": msgid, "wxpid": event.normalized_wxpid, "response": download_response},
            )
            return {"handled": False, "detail": ""}
        detection_result = detect_qrcode(image_path)
    except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as exc:
        context.logger.warning(
            "群二维码检测插件识别图片失败，已跳过本次校验",
            {"roomid": roomid, "sender_wxid": sender_wxid, "msgid": msgid, "wxpid": event.normalized_wxpid, "error": str(exc)},
        )
        return {"handled": False, "detail": ""}
    except Exception as exc:
        context.logger.warning(
            "群二维码检测插件下载图片失败，已跳过本次校验",
            {"roomid": roomid, "sender_wxid": sender_wxid, "msgid": msgid, "wxpid": event.normalized_wxpid, "error": str(exc)},
        )
        return {"handled": False, "detail": ""}

    if not detection_result.get("has_qrcode"):
        return {"handled": False, "detail": ""}

    sender_name = await resolve_sender_name(event, context, roomid, sender_wxid, room_members)
    room_name = resolve_room_name(event, roomid)
    warning_text = render_warning_text(context.config.get("warning_template"), sender_name, room_name)
    kick_after_warning = is_truthy(context.config.get("kick_after_warning", True))
    log_payload = build_log_payload(event, roomid, sender_wxid, sender_name, room_name, image_path, detection_result)

    pending_state = context.state.namespace("pending_kicks")
    pending_key = f"{roomid}::{sender_wxid}"
    if kick_after_warning and get_active_pending_kick(pending_state, pending_key):
        context.logger.info("群二维码检测插件检测到重复违规，成员仍在待移出队列中", log_payload)
        return {"handled": True, "detail": "该成员已在待移出队列中", "data": log_payload}

    if kick_after_warning:
        pending_state.set(
            pending_key,
            {
                "created_at_ms": int(time() * 1000),
                "msgid": event.normalized_msgid,
                "sender_wxid": sender_wxid,
                "roomid": roomid,
            },
        )

    try:
        await context.api.send_text(wxid=roomid, content=warning_text, atlist=sender_wxid, wxpid=event.normalized_wxpid)
    except Exception as exc:
        if kick_after_warning:
            pending_state.delete(pending_key)
        context.logger.error("群二维码检测插件发送警告信息失败", {**log_payload, "error": str(exc)})
        return {"handled": False, "detail": "发送二维码警告失败", "data": {**log_payload, "error": str(exc)}}

    warning_count = context.state.increment("warning_count", 1)
    if not kick_after_warning:
        context.logger.info("群二维码检测插件已发送二维码警告", {**log_payload, "warning_count": warning_count})
        return {
            "handled": True,
            "detail": f"已提醒 {sender_name} 不要发送二维码图片",
            "data": {**log_payload, "action": "warned", "warning_count": warning_count},
        }

    delay_seconds = random_between(3, 5)
    await sleep(delay_seconds * 1000)

    removal_log_payload = {**log_payload, "warning_count": warning_count, "delay_seconds": delay_seconds}
    if not await can_current_account_remove_members(
        context,
        roomid,
        event.normalized_wxpid,
        self_wxid,
        removal_log_payload,
    ):
        pending_state.delete(pending_key)
        return {
            "handled": True,
            "detail": "已发送警告，但当前账号没有群管理权限，未移出群成员",
            "data": {**removal_log_payload, "action": "warned_only_no_permission"},
        }

    try:
        await context.api.delete_room_members(roomid=roomid, wxids=sender_wxid, wxpid=event.normalized_wxpid)
    except Exception as exc:
        pending_state.delete(pending_key)
        context.logger.error(
            "群二维码检测插件移出违规成员失败",
            {**removal_log_payload, "error": str(exc)},
        )
        return {
            "handled": True,
            "detail": "已发送警告，但移出群成员失败",
            "data": {**removal_log_payload, "action": "warned_only", "error": str(exc)},
        }
    finally:
        pending_state.delete(pending_key)

    kick_count = context.state.increment("kick_count", 1)
    context.logger.info(
        "群二维码检测插件已提醒并移出违规成员",
        {**log_payload, "warning_count": warning_count, "kick_count": kick_count, "delay_seconds": delay_seconds},
    )
    return {
        "handled": True,
        "detail": f"已提醒并移出发送二维码图片的成员 {sender_name}",
        "data": {
            **log_payload,
            "action": "warned_and_removed",
            "warning_count": warning_count,
            "kick_count": kick_count,
            "delay_seconds": delay_seconds,
        },
    }
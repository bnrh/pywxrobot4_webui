import hashlib
import re
from time import time

from ._plugin_sdk import async_http_get, format_unix_time, get_message_type, normalize_text, is_truthy


name = "vmq_monitor"
description = "监听指定公众号的微信收款消息并推送到配置服务"
event_filters = ["direct"]
schedule = {
    "interval_field": "heartbeat_interval_seconds",
    "default_interval_seconds": 15,
}

TARGET_BIZ_ACCOUNTS = {
    "gh_3dfda90e39d6",
    "gh_f0a92aa7146c",
}
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15
HTTP_TIMEOUT_SECONDS = 10.0
VMQ_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 NetType/WIFI MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090c25) XWEB/13639 Flue"
}
PAYMENT_AMOUNT_PATTERNS = [
    re.compile(r"微信支付收款\s*([\d.]+)"),
    re.compile(r"收款金额\s*[￥¥]?\s*([\d.]+)"),
]
REMARKS_PATTERN = re.compile(r"付款方备注\s*(.*?)\s*(?:汇总|收款金额|收款方|到账通知|微信支付|$)", re.S)

config_schema = [
    {
        "key": "host",
        "label": "服务地址",
        "type": "url",
        "default": "",
        "placeholder": "http://127.0.0.1:8888",
        "description": "VMQ 服务地址；若未填写 http/https 前缀，会自动补成 http://。",
    },
    {
        "key": "key",
        "label": "通信密钥 key",
        "type": "text",
        "default": "",
        "placeholder": "请输入与服务端一致的通信密钥",
    },
    {
        "key": "heartbeat_interval_seconds",
        "label": "心跳间隔时间(秒)",
        "type": "number",
        "default": DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        "min": 1,
        "max": 86400,
        "step": 1,
        "full_width": False,
        "description": "插件启动后会立即发送一次心跳，之后按这里的间隔持续发送。",
    },
]




def normalize_host(value):
    host = normalize_text(value)
    if not host:
        return ""
    if not re.match(r"^https?://", host, re.I):
        host = f"http://{host}"
    return host.rstrip("/")


def normalize_key(value):
    return normalize_text(value)


def resolve_heartbeat_interval_seconds(config):
    raw_value = config.get("heartbeat_interval_seconds") if isinstance(config, dict) else None
    try:
        interval_seconds = int(float(raw_value)) if raw_value not in (None, "") else DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    except (TypeError, ValueError):
        interval_seconds = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    return max(1, interval_seconds)


def resolve_service_settings(config):
    normalized_config = config if isinstance(config, dict) else {}
    return {
        "host": normalize_host(normalized_config.get("host")),
        "key": normalize_key(normalized_config.get("key")),
        "heartbeat_interval_seconds": resolve_heartbeat_interval_seconds(normalized_config),
    }


def resolve_target_biz_account(event):
    candidates = {
        normalize_text(getattr(event, "sender", "")).lower(),
        normalize_text(event.conversation_wxid).lower(),
        normalize_text(event.sender_wxid).lower(),
        normalize_text(getattr(event, "recipient", "")).lower(),
    }
    for biz_wxid in TARGET_BIZ_ACCOUNTS:
        if biz_wxid in candidates:
            return biz_wxid
    return ""


def is_self_message(event):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        return is_truthy(first_non_empty("is_self_msg", "is_self", "isSend", "is_send"))
    return False


def parse_payment_message(content):
    source = str(content or "")
    normalized_content = normalize_text(source)
    if not normalized_content:
        return None

    amount_match = None
    for pattern in PAYMENT_AMOUNT_PATTERNS:
        amount_match = pattern.search(normalized_content)
        if amount_match:
            break
    if amount_match is None:
        return None

    amount_text = normalize_text(amount_match.group(1)).replace(",", "")
    try:
        amount = float(amount_text)
    except ValueError:
        return None

    remarks_match = REMARKS_PATTERN.search(normalized_content)
    remarks = normalize_text(remarks_match.group(1)) if remarks_match else ""

    pay_time_text = ""
    pub_time_match = re.search(r"<pub_time>(\d+)</pub_time>", source)
    if pub_time_match:
        pay_time_text = format_unix_time(pub_time_match.group(1))

    return {
        "amount": amount,
        "amount_text": str(amount),
        "remarks": remarks,
        "pay_time": pay_time_text,
    }


def build_signed_params(request_type, amount_text, key):
    current_time_ms = int(time() * 1000)
    params = {
        "t": current_time_ms,
        "type": 1,
    }
    if request_type == "push":
        params["price"] = amount_text
        raw_sign = f"1{amount_text}{current_time_ms}{key}"
    else:
        raw_sign = f"{current_time_ms}{key}"
    params["sign"] = hashlib.md5(raw_sign.encode("utf-8")).hexdigest()
    return params


async def send_get_request(url, params):
    return await async_http_get(url, params=params, headers=VMQ_REQUEST_HEADERS, timeout=HTTP_TIMEOUT_SECONDS)


async def send_heartbeat(context, service_settings, reason):
    if not service_settings["host"] or not service_settings["key"]:
        return False

    params = build_signed_params("heartbeat", "", service_settings["key"])
    status, response_text = await send_get_request(f"{service_settings['host']}/appHeart", params)
    context.state.namespace(name).set(
        "last_heartbeat",
        {
            "reason": reason,
            "status": status,
            "response_text": response_text[:500],
            "requested_at": params["t"],
        },
    )
    return True


async def push_payment(context, service_settings, payment_info, sender_wxid):
    params = build_signed_params("push", payment_info["amount_text"], service_settings["key"])
    status, response_text = await send_get_request(f"{service_settings['host']}/appPush", params)
    context.state.namespace(name).set(
        "last_push",
        {
            "sender": sender_wxid,
            "amount": payment_info["amount"],
            "remarks": payment_info["remarks"],
            "pay_time": payment_info["pay_time"],
            "status": status,
            "response_text": response_text[:500],
            "requested_at": params["t"],
        },
    )
    return status, response_text


async def startup(context):
    service_settings = resolve_service_settings(context.config)
    if not service_settings["host"] or not service_settings["key"]:
        context.logger.warning("VMQ 监控插件未完成配置，已跳过启动心跳", {"has_host": bool(service_settings["host"]), "has_key": bool(service_settings["key"])})
        return

    try:
        await send_heartbeat(context, service_settings, "startup")
    except Exception as exc:
        context.logger.warning("VMQ 启动心跳发送失败", {"host": service_settings["host"], "error": str(exc)})
        return

    context.logger.info("VMQ 监控插件已启动", {"host": service_settings["host"], "heartbeat_interval_seconds": service_settings["heartbeat_interval_seconds"]})


async def tick(context):
    service_settings = resolve_service_settings(context.config)
    if not service_settings["host"] or not service_settings["key"]:
        return {"handled": False, "detail": ""}

    try:
        await send_heartbeat(context, service_settings, "tick")
    except Exception as exc:
        context.logger.warning("VMQ 周期心跳发送失败", {"host": service_settings["host"], "error": str(exc)})
    return {"handled": False, "detail": ""}


async def handle_message(event, context):
    if is_self_message(event):
        return {"handled": False, "detail": ""}

    sender_wxid = resolve_target_biz_account(event)
    if not sender_wxid:
        return {"handled": False, "detail": ""}

    content = event.normalized_content or getattr(event, "content", "")
    if not content:
        return {"handled": False, "detail": ""}

    message_type = get_message_type(event)
    if message_type is None and not re.search(r"微信支付收款|收款金额", str(content)):
        return {"handled": False, "detail": ""}

    payment_info = parse_payment_message(content)
    if not payment_info:
        return {"handled": False, "detail": ""}

    service_settings = resolve_service_settings(context.config)
    if not service_settings["host"] or not service_settings["key"]:
        context.logger.warning("VMQ 监控插件命中了收款消息，但未配置服务地址或通信密钥", {"sender": sender_wxid, "amount": payment_info["amount"], "pay_time": payment_info["pay_time"]})
        return {"handled": False, "detail": ""}

    try:
        status, response_text = await push_payment(context, service_settings, payment_info, sender_wxid)
    except Exception as exc:
        context.logger.error(
            "VMQ 收款推送失败",
            {
                "sender": sender_wxid,
                "amount": payment_info["amount"],
                "remarks": payment_info["remarks"],
                "pay_time": payment_info["pay_time"],
                "error": str(exc),
            },
        )
        return {
            "handled": True,
            "detail": f"识别到 {payment_info['amount']} 元收款消息，但推送失败",
            "data": {
                "sender": sender_wxid,
                "amount": payment_info["amount"],
                "remarks": payment_info["remarks"],
                "pay_time": payment_info["pay_time"],
            },
        }

    context.logger.info(
        "已推送微信收款消息",
        {
            "sender": sender_wxid,
            "amount": payment_info["amount"],
            "remarks": payment_info["remarks"],
            "pay_time": payment_info["pay_time"],
            "response_status": status,
        },
    )
    return {
        "handled": True,
        "detail": f"已推送 {payment_info['amount']} 元收款消息",
        "data": {
            "sender": sender_wxid,
            "amount": payment_info["amount"],
            "remarks": payment_info["remarks"],
            "pay_time": payment_info["pay_time"],
            "response_status": status,
            "response_text": response_text[:200],
        },
    }
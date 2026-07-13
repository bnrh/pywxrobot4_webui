import base64
import binascii
import json
import mimetypes
import re
from pathlib import Path
from time import time
from urllib.parse import urljoin, urlparse
import uuid

import httpx

from ai_assistant import run_openai_compatible_chat_completion
from config import PROJECT_ROOT

from ._plugin_sdk import (
    MESSAGE_TYPES,
    async_http_get_bytes,
    async_http_request,
    find_xml_tag_text,
    get_message_type,
    normalize_text,
    random_between,
    resolve_downloaded_image_path,
    resolve_local_image_path,
    sleep,
    unique_strings,
)


name = "room_ai_reply"
description = "按群聊配置 OpenAI-compatible AI 助手，仅在被 @ 时自动回复群文本消息"
event_filters = ["text", "image"]

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MARKDOWN_ARTICLE_GHID = ""
DEFAULT_MARKDOWN_ARTICLE_NICKNAME = ""
DEFAULT_MARKDOWN_ARTICLE_COVER_URL = "https://avatars.githubusercontent.com/u/67865462?s=200&v=4"
SEND_ARTICLE_COMPAT_GHID = "gh_98e6c50f500b"
SEND_ARTICLE_COMPAT_NICKNAME = "HedgeDoc 渲染器"
DEFAULT_MARKDOWN_ARTICLE_TITLE = "Markdown 回复"
HEDGEDOC_REQUEST_TIMEOUT_SECONDS = 20.0
HEDGEDOC_IMAGE_UPLOAD_TIMEOUT_SECONDS = 60.0
AI_REPLY_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 60.0
AI_REPLY_IMAGE_UPLOAD_DIR = PROJECT_ROOT / "uploads" / "room_ai_reply"
DEFAULT_PENDING_IMAGE_WAIT_SECONDS = 8
PENDING_IMAGE_STATE_NAMESPACE = "pending_room_images"
PENDING_IMAGE_DOWNLOAD_DELAY_MIN_SECONDS = 1
PENDING_IMAGE_DOWNLOAD_DELAY_MAX_SECONDS = 2
PENDING_IMAGE_DOWNLOAD_FLAG = 3
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
DATA_IMAGE_URL_PATTERN = re.compile(r"^data:(?P<media_type>image/[^;]+)?;base64,(?P<data>.+)$", re.I | re.S)
AT_MENTION_PATTERN = re.compile(r"(?<!\S)@[^@\n]+?(?=\u2005|$)")
MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?P<tail>\s+\&quot;[^\&]+\&quot;|\s+\"[^\"]*\")?\)")
MARKDOWN_STRONG_PATTERNS = [
    re.compile(r"```"),
    re.compile(r"(?m)^\s*#{1,6}\s+\S"),
    re.compile(r"(?m)^\s*>\s+\S"),
    re.compile(r"(?m)^\s*\|.+\|\s*$"),
    re.compile(r"\[[^\]]+\]\([^\)]+\)"),
    re.compile(r"!\[[^\]]*\]\([^\)]+\)"),
    re.compile(r"(?m)^\s*[-*_]{3,}\s*$"),
]
MARKDOWN_LIST_PATTERN = re.compile(r"(?m)^\s*(?:[-*+] |\d+\. )\S")
FRONT_MATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.S)
FRONT_MATTER_TITLE_PATTERN = re.compile(r"(?mi)^\s*title\s*:\s*[\"']?(.*?)[\"']?\s*$")
HEADING_PATTERN = re.compile(r"(?m)^\s*#{1,6}\s+(.+?)\s*$")

config_schema = [
    {
        "key": "room_configs",
        "aliases": ["roomid", "wxid", "base_url", "api_key", "model", "system_prompt", "prompt"],
        "label": "群聊 AI 助手",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "meaningful_keys": ["roomid", "base_url", "api_key", "model", "system_prompt"],
        "unique_by": ["roomid"],
        "unique_message": "同一个群聊只能保留一个 AI 助手配置",
        "empty_text": "暂无群聊 AI 助手配置，点击“新增”后为目标群聊单独设置模型、Key 和提示词。",
        "description": "每个群聊可单独配置一个 AI 助手，包括 Base URL、API Key、模型和系统提示词。模型支持手动填写，也可点击按钮获取模型列表。",
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
            {
                "key": "base_url",
                "label": "大模型 Base URL",
                "type": "url",
                "default": DEFAULT_BASE_URL,
                "placeholder": "https://api.openai.com/v1",
                "width": "wide",
                "editor_span": 6,
            },
            {
                "key": "api_key",
                "label": "大模型 API Key",
                "type": "password",
                "default": "",
                "placeholder": "输入可用的 API Key",
                "required": True,
                "required_message": "API Key 不能为空",
                "width": "wide",
                "editor_span": 6,
            },
            {
                "key": "model",
                "label": "模型",
                "type": "text",
                "options_source": "model_options",
                "options_loader": "openai_compatible",
                "manual_fetch_options": True,
                "fetch_options_button": True,
                "fetch_options_button_label": "获取模型列表",
                "fetch_options_select_placeholder": "从已获取的模型列表中选择",
                "base_url_key": "base_url",
                "api_key_key": "api_key",
                "placeholder": "可手动输入模型名，或点击右侧按钮获取列表后选择",
                "required": True,
                "required_message": "模型不能为空",
                "description": "支持手动输入模型名，也可根据当前 Base URL 和 API Key 获取模型列表。",
                "width": "wide",
                "editor_span": 6,
            },
            {
                "key": "system_prompt",
                "label": "系统提示词",
                "type": "textarea",
                "rows": 5,
                "default": "",
                "placeholder": "例如：你是这个群的售后助手，回答要礼貌、简洁，并优先给出可执行步骤",
                "description": "每个群聊都可以自定义 AI 助手提示词；留空时不会附带系统提示词。",
                "width": "wide",
                "editor_span": 12,
            },
        ],
    },
    {
        "key": "hedgedoc_url",
        "label": "HedgeDoc URL",
        "type": "url",
        "default": "",
        "placeholder": "例如：http://127.0.0.1:3000",
        "description": "当模型回复被识别为 Markdown 时，会先上传到该 HedgeDoc 实例，再发送图文链接。",
    },
    {
        "key": "pending_image_wait_seconds",
        "label": "图片关联等待时间(秒)",
        "type": "number",
        "default": DEFAULT_PENDING_IMAGE_WAIT_SECONDS,
        "min": 1,
        "max": 60,
        "step": 1,
        "full_width": False,
        "description": "群成员先发图片后，再在该时间窗口内发送 @ 消息时，会把该图片和文本一起发送给模型。",
    },
    {
        "key": "hedgedoc_email",
        "label": "HedgeDoc 邮箱",
        "type": "text",
        "default": "",
        "placeholder": "输入 HedgeDoc 本地账号邮箱",
        "description": "参考 tmp/1.py 的登录方式，使用本地邮箱密码登录 HedgeDoc。",
        "full_width": False,
    },
    {
        "key": "hedgedoc_password",
        "label": "HedgeDoc 密码",
        "type": "password",
        "default": "",
        "placeholder": "输入 HedgeDoc 本地账号密码",
        "description": "仅在模型回复为 Markdown 且需要发送图文链接时使用。",
        "full_width": False,
    },
]


def strip_room_sender_prefix(content, room_sender):
    normalized_content = str(content or "")
    normalized_sender = normalize_text(room_sender)
    if not normalized_sender:
        return normalized_content.strip()

    prefixes = [
        f"{normalized_sender}:",
        f"{normalized_sender}：",
        f"{normalized_sender}\n",
        f"{normalized_sender}:\n",
        f"{normalized_sender}：\n",
    ]
    for prefix in prefixes:
        if normalized_content.startswith(prefix):
            return normalized_content[len(prefix):].strip()
    return normalized_content.strip()


def resolve_sender_name(event):
    for candidate in [
        getattr(event, "room_sender_display_name", ""),
        getattr(event, "sender_display_name", ""),
        getattr(event, "room_sender", ""),
        getattr(event, "sender_wxid", ""),
    ]:
        text = str(candidate or "").strip()
        if text:
            return text
    return "群成员"


def resolve_room_name(event, roomid):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        room_name = str(first_non_empty("conversation_display_name", "title_display") or "").strip()
        if room_name and room_name != roomid:
            return room_name
    return roomid or "当前群聊"


def resolve_current_account_wxid(event):
    first_non_empty = getattr(event, "first_non_empty", None)
    if callable(first_non_empty):
        return normalize_text(
            first_non_empty(
                "self_wxid",
                "current_wxid",
                "login_wxid",
                "account_wxid",
                "recipient",
            )
        )
    return normalize_text(
        getattr(event, "current_account_wxid", "") or getattr(event, "recipient", "")
    )


def get_message_at_user_list(event):
    msgsource = getattr(event, "msgsource", "") or getattr(event, "source", "") or ""
    return unique_strings(find_xml_tag_text(msgsource, "atuserlist"))


def is_at_current_account(event):
    current_account_wxid = resolve_current_account_wxid(event)
    if not current_account_wxid:
        return False
    return current_account_wxid in get_message_at_user_list(event)


def remove_msg_at_text(content):
    normalized_content = str(content or "")
    cleaned_content = AT_MENTION_PATTERN.sub("", normalized_content)
    cleaned_content = cleaned_content.replace("\u2005", " ")
    return normalize_text(cleaned_content)


def now_milliseconds():
    return int(time() * 1000)


def resolve_pending_image_wait_seconds(config):
    raw_value = config.get("pending_image_wait_seconds") if isinstance(config, dict) else None
    try:
        wait_seconds = int(float(raw_value)) if raw_value not in (None, "") else DEFAULT_PENDING_IMAGE_WAIT_SECONDS
    except (TypeError, ValueError):
        wait_seconds = DEFAULT_PENDING_IMAGE_WAIT_SECONDS
    return max(1, min(60, wait_seconds))


def build_pending_room_image_key(roomid, sender_wxid):
    return f"{roomid}::{sender_wxid}"


def normalize_pending_room_image_record(value):
    payload = value if isinstance(value, dict) else {}
    try:
        created_at_ms = int(payload.get("created_at_ms") or 0)
    except (TypeError, ValueError):
        created_at_ms = 0
    try:
        expires_at_ms = int(payload.get("expires_at_ms") or 0)
    except (TypeError, ValueError):
        expires_at_ms = 0
    try:
        wxpid = int(payload.get("wxpid")) if payload.get("wxpid") not in (None, "") else None
    except (TypeError, ValueError):
        wxpid = None
    return {
        "msgid": normalize_text(payload.get("msgid")),
        "roomid": normalize_text(payload.get("roomid")),
        "sender_wxid": normalize_text(payload.get("sender_wxid")),
        "image_path": normalize_text(payload.get("image_path")),
        "download_error": normalize_text(payload.get("download_error")),
        "created_at_ms": created_at_ms,
        "expires_at_ms": expires_at_ms,
        "wxpid": wxpid,
    }


def cleanup_stale_pending_room_images(pending_state, now_ms):
    for pending_key, pending_value in pending_state.entries():
        pending = normalize_pending_room_image_record(pending_value)
        expires_at_ms = pending["expires_at_ms"] or pending["created_at_ms"]
        if expires_at_ms > 0 and now_ms <= expires_at_ms:
            continue
        pending_state.delete(pending_key)


def get_active_pending_room_image(pending_state, pending_key, now_ms):
    pending = normalize_pending_room_image_record(pending_state.get(pending_key))
    if not pending["msgid"] and not pending["image_path"]:
        pending_state.delete(pending_key)
        return None

    expires_at_ms = pending["expires_at_ms"] or pending["created_at_ms"]
    if expires_at_ms <= 0 or now_ms > expires_at_ms:
        pending_state.delete(pending_key)
        return None
    return pending


async def download_room_message_image(context, roomid, msgid, wxpid):
    timeout_seconds = int(getattr(getattr(context, "settings", None), "image_download_timeout", 15) or 15)
    response = await context.api.download_cdn_image(
        msgid=msgid,
        wxid=roomid,
        wxpid=wxpid,
        flag=PENDING_IMAGE_DOWNLOAD_FLAG,
        wait=True,
        timeout=timeout_seconds,
    )
    image_path = resolve_downloaded_image_path(response)
    if image_path is None:
        raise RuntimeError(f"下载图片成功但未找到可用文件路径: {response}")
    return image_path, response


async def prime_pending_room_image(context, pending_state, pending_key, roomid, sender_wxid, msgid, wxpid, expires_at_ms):
    pending_state.set(
        pending_key,
        {
            "msgid": msgid,
            "roomid": roomid,
            "sender_wxid": sender_wxid,
            "image_path": "",
            "download_error": "",
            "created_at_ms": now_milliseconds(),
            "expires_at_ms": expires_at_ms,
            "wxpid": wxpid,
        },
    )

    delay_seconds = random_between(PENDING_IMAGE_DOWNLOAD_DELAY_MIN_SECONDS, PENDING_IMAGE_DOWNLOAD_DELAY_MAX_SECONDS)
    await sleep(delay_seconds * 1000)

    try:
        image_path, _ = await download_room_message_image(context, roomid, msgid, wxpid)
    except Exception as exc:
        latest_pending = get_active_pending_room_image(pending_state, pending_key, now_milliseconds())
        if latest_pending is not None and latest_pending["msgid"] == msgid:
            pending_state.set(pending_key, {**latest_pending, "download_error": str(exc)})
        context.logger.warning(
            "群聊 AI 回复预下载上一条图片失败，等待后续消息时将按需重试",
            {"roomid": roomid, "sender_wxid": sender_wxid, "msgid": msgid, "wxpid": wxpid, "error": str(exc)},
        )
        return

    latest_pending = get_active_pending_room_image(pending_state, pending_key, now_milliseconds())
    if latest_pending is None or latest_pending["msgid"] != msgid:
        return
    pending_state.set(pending_key, {**latest_pending, "image_path": str(image_path), "download_error": ""})


async def ensure_pending_room_image_path(context, roomid, pending_image_record):
    local_image_path = resolve_local_image_path(pending_image_record.get("image_path"))
    if local_image_path is not None:
        return str(local_image_path)

    msgid = normalize_text(pending_image_record.get("msgid"))
    if not msgid:
        return ""

    image_path, _ = await download_room_message_image(context, roomid, msgid, pending_image_record.get("wxpid"))
    return str(image_path)


def build_local_image_data_url(image_path):
    image_file_path = resolve_local_image_path(image_path)
    if image_file_path is None or not image_file_path.is_file():
        raise RuntimeError(f"待发送给模型的图片不存在: {image_path}")

    media_type = mimetypes.guess_type(str(image_file_path))[0] or "image/png"
    image_base64 = base64.b64encode(image_file_path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{image_base64}"


def build_ai_user_message(message_text, image_path=""):
    normalized_text = str(message_text or "").strip()
    normalized_image_path = str(image_path or "").strip()
    if not normalized_image_path:
        return {"role": "user", "content": normalized_text}

    content_blocks = []
    if normalized_text:
        content_blocks.append({"type": "text", "text": normalized_text})
    content_blocks.append({"type": "image_url", "image_url": {"url": build_local_image_data_url(normalized_image_path)}})
    return {"role": "user", "content": content_blocks}


def normalize_markdown_delivery_config(config):
    normalized_config = config if isinstance(config, dict) else {}
    hedgedoc_url = str(normalized_config.get("hedgedoc_url") or "").strip().rstrip("/")
    return {
        "hedgedoc_url": hedgedoc_url,
        "hedgedoc_email": str(normalized_config.get("hedgedoc_email") or "").strip(),
        "hedgedoc_password": str(normalized_config.get("hedgedoc_password") or "").strip(),
        "article_ghid": DEFAULT_MARKDOWN_ARTICLE_GHID,
        "article_nickname": DEFAULT_MARKDOWN_ARTICLE_NICKNAME,
        "article_cover_url": DEFAULT_MARKDOWN_ARTICLE_COVER_URL,
    }


def get_missing_markdown_delivery_fields(markdown_config):
    missing_fields = []
    for field_key in ["hedgedoc_url", "hedgedoc_email", "hedgedoc_password"]:
        if not str(markdown_config.get(field_key) or "").strip():
            missing_fields.append(field_key)
    return missing_fields


def is_likely_markdown(content):
    normalized_content = str(content or "").strip()
    if not normalized_content:
        return False
    if any(pattern.search(normalized_content) for pattern in MARKDOWN_STRONG_PATTERNS):
        return True
    return len(MARKDOWN_LIST_PATTERN.findall(normalized_content)) >= 2


def trim_text(value, limit, fallback=""):
    normalized_value = str(value or "").strip() or str(fallback or "").strip()
    if len(normalized_value) <= limit:
        return normalized_value
    return f"{normalized_value[: max(0, limit - 1)].rstrip()}…"


def strip_markdown_to_text(markdown_text):
    normalized_text = str(markdown_text or "")
    normalized_text = re.sub(r"```[\s\S]*?```", " ", normalized_text)
    normalized_text = re.sub(r"`([^`]+)`", r"\1", normalized_text)
    normalized_text = re.sub(r"!\[([^\]]*)\]\([^\)]+\)", r"\1", normalized_text)
    normalized_text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", normalized_text)
    normalized_text = re.sub(r"(?m)^\s*#{1,6}\s*", "", normalized_text)
    normalized_text = re.sub(r"(?m)^\s*>\s*", "", normalized_text)
    normalized_text = re.sub(r"(?m)^\s*(?:[-*+] |\d+\. )", "", normalized_text)
    normalized_text = re.sub(r"(?m)^\s*\|", "", normalized_text)
    normalized_text = normalized_text.replace("|", " ")
    normalized_text = re.sub(r"[*_~]", "", normalized_text)
    normalized_text = re.sub(r"\s+", " ", normalized_text)
    return normalized_text.strip()


def extract_markdown_title(markdown_text, fallback_title=""):
    normalized_text = str(markdown_text or "").strip()
    if not normalized_text:
        return trim_text(fallback_title, 50, DEFAULT_MARKDOWN_ARTICLE_TITLE)

    front_matter_match = FRONT_MATTER_PATTERN.match(normalized_text)
    if front_matter_match:
        title_match = FRONT_MATTER_TITLE_PATTERN.search(front_matter_match.group(1))
        if title_match:
            return trim_text(strip_markdown_to_text(title_match.group(1)), 50, fallback_title)

    heading_match = HEADING_PATTERN.search(normalized_text)
    if heading_match:
        return trim_text(strip_markdown_to_text(heading_match.group(1)), 50, fallback_title)

    first_line = next((line for line in normalized_text.splitlines() if line.strip()), "")
    return trim_text(strip_markdown_to_text(first_line), 50, fallback_title or DEFAULT_MARKDOWN_ARTICLE_TITLE)


def resolve_send_article_publisher(markdown_config):
    ghid = str(markdown_config.get("article_ghid") or "").strip()
    nickname = str(markdown_config.get("article_nickname") or "").strip()
    return {
        "ghid": ghid or SEND_ARTICLE_COMPAT_GHID,
        "nickname": nickname or SEND_ARTICLE_COMPAT_NICKNAME,
    }


def extract_markdown_image_items(markdown_text):
    image_items = []
    for match in MARKDOWN_IMAGE_PATTERN.finditer(str(markdown_text or "")):
        image_url = str(match.group("url") or "").strip()
        if not image_url:
            continue
        image_items.append(
            {
                "url": image_url,
                "alt_text": str(match.group("alt") or "").strip(),
                "detail": "markdown",
            }
        )
    return image_items


def strip_markdown_image_syntax(markdown_text):
    normalized_text = MARKDOWN_IMAGE_PATTERN.sub("", str(markdown_text or ""))
    normalized_text = re.sub(r"\n{3,}", "\n\n", normalized_text)
    return normalized_text.strip()


def merge_reply_image_items(reply_text, image_items):
    merged_items = []
    seen_sources = set()
    for image_item in [*extract_markdown_image_items(reply_text), *(image_items or [])]:
        if not isinstance(image_item, dict):
            continue
        image_source = str(image_item.get("url") or "").strip()
        if not image_source or image_source in seen_sources:
            continue
        seen_sources.add(image_source)
        merged_items.append(dict(image_item))
    return merged_items


def build_markdown_reply_with_images(reply_text, image_items):
    sections = []
    normalized_text = str(reply_text or "").strip()
    if normalized_text:
        sections.append(normalized_text)

    for index, image_item in enumerate(image_items or [], start=1):
        image_url = str((image_item or {}).get("url") or "").strip()
        if not image_url:
            continue
        alt_text = trim_text(
            strip_markdown_to_text((image_item or {}).get("alt_text") or f"图片 {index}"),
            80,
            f"图片 {index}",
        )
        sections.append(f"![{alt_text}]({image_url})")

    return "\n\n".join(section for section in sections if str(section or "").strip()).strip()


def replace_markdown_image_urls(markdown_text, uploaded_link_map):
    if not uploaded_link_map:
        return str(markdown_text or "")

    def replace_match(match):
        original_url = str(match.group("url") or "").strip()
        replaced_url = str(uploaded_link_map.get(original_url) or original_url).strip()
        if not replaced_url:
            return match.group(0)
        alt_text = str(match.group("alt") or "")
        tail = str(match.group("tail") or "")
        return f"![{alt_text}]({replaced_url}{tail})"

    return MARKDOWN_IMAGE_PATTERN.sub(replace_match, str(markdown_text or ""))


def guess_ai_image_suffix(image_item, response_content_type=""):
    normalized_media_type = str((image_item or {}).get("media_type") or response_content_type or "").split(";", 1)[0].strip().lower()
    if normalized_media_type:
        guessed_suffix = mimetypes.guess_extension(normalized_media_type) or ""
        if guessed_suffix == ".jpe":
            guessed_suffix = ".jpg"
        if guessed_suffix:
            return guessed_suffix

    source_url = str((image_item or {}).get("url") or "").strip()
    if source_url.startswith(("http://", "https://")):
        url_path = urlparse(source_url).path
        path_suffix = Path(url_path).suffix.lower()
        if path_suffix:
            return path_suffix
    return ".png"


async def materialize_ai_image(image_item):
    normalized_item = image_item if isinstance(image_item, dict) else {}
    image_source = str(normalized_item.get("url") or "").strip()
    if not image_source:
        raise RuntimeError("AI 未返回可用的图片地址")

    candidate_path = Path(image_source)
    if candidate_path.is_file():
        return str(candidate_path)

    AI_REPLY_IMAGE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    data_url_match = DATA_IMAGE_URL_PATTERN.match(image_source)
    if data_url_match:
        media_type = str(data_url_match.group("media_type") or normalized_item.get("media_type") or "image/png").strip() or "image/png"
        try:
            image_bytes = base64.b64decode(data_url_match.group("data"), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise RuntimeError("AI 返回的 Base64 图片数据无效") from exc
        output_path = AI_REPLY_IMAGE_UPLOAD_DIR / f"{uuid.uuid4().hex}{guess_ai_image_suffix({**normalized_item, 'media_type': media_type})}"
        output_path.write_bytes(image_bytes)
        return str(output_path)

    if not image_source.startswith(("http://", "https://")):
        raise RuntimeError(f"AI 返回了当前无法处理的图片地址: {image_source}")

    try:
        _, image_bytes, response_content_type = await async_http_get_bytes(
            image_source,
            headers={"User-Agent": "wxrobot_webui/room_ai_reply"},
            timeout=AI_REPLY_IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise RuntimeError("下载 AI 图片超时") from exc
    except RuntimeError as exc:
        detail = str(exc)
        if detail.startswith("HTTP "):
            raise RuntimeError(f"下载 AI 图片失败，{detail[:300]}") from exc
        raise RuntimeError(f"下载 AI 图片失败: {exc}") from exc

    if not image_bytes:
        raise RuntimeError("下载 AI 图片失败：响应内容为空")

    output_path = AI_REPLY_IMAGE_UPLOAD_DIR / f"{uuid.uuid4().hex}{guess_ai_image_suffix(normalized_item, response_content_type)}"
    output_path.write_bytes(image_bytes)
    return str(output_path)


async def upload_image_to_hedgedoc(client: httpx.AsyncClient, hedgedoc_url, image_path):
    image_file_path = Path(image_path)
    if not image_file_path.is_file():
        raise RuntimeError(f"待上传的图片不存在: {image_path}")

    content_type = mimetypes.guess_type(str(image_file_path))[0] or "application/octet-stream"
    image_bytes = image_file_path.read_bytes()
    try:
        response = await async_http_request(
            "POST",
            urljoin(f"{hedgedoc_url}/", "uploadimage"),
            headers={
                "Accept": "*/*",
                "Origin": hedgedoc_url,
                "Referer": f"{hedgedoc_url}/",
            },
            files={"image": (image_file_path.name, image_bytes, content_type)},
            timeout=HEDGEDOC_IMAGE_UPLOAD_TIMEOUT_SECONDS,
            client=client,
        )
    except TimeoutError as exc:
        raise RuntimeError("HedgeDoc 上传图片超时") from exc
    except RuntimeError as exc:
        raise RuntimeError(f"HedgeDoc 上传图片失败: {exc}") from exc

    response_text = response.text
    if response.status_code >= 400:
        raise RuntimeError(f"HedgeDoc 上传图片失败，HTTP {response.status_code}: {response_text[:500]}")

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"HedgeDoc 上传图片返回了非 JSON 响应: {response_text[:500]}") from exc

    uploaded_link = str(payload.get("link") or "").strip() if isinstance(payload, dict) else ""
    if not uploaded_link:
        raise RuntimeError(f"HedgeDoc 上传图片返回异常: {payload}")
    return uploaded_link


async def prepare_markdown_reply_for_hedgedoc(markdown_text, image_items, markdown_config):
    normalized_markdown = str(markdown_text or "").strip()
    hedgedoc_client = await login_hedgedoc(
        markdown_config["hedgedoc_url"],
        markdown_config["hedgedoc_email"],
        markdown_config["hedgedoc_password"],
    )

    try:
        uploaded_link_map = {}
        embedded_image_items = extract_markdown_image_items(normalized_markdown)
        for image_item in embedded_image_items:
            image_source = str(image_item.get("url") or "").strip()
            if not image_source or image_source in uploaded_link_map:
                continue
            local_image_path = await materialize_ai_image(image_item)
            uploaded_link_map[image_source] = await upload_image_to_hedgedoc(
                hedgedoc_client, markdown_config["hedgedoc_url"], local_image_path
            )

        final_markdown = replace_markdown_image_urls(normalized_markdown, uploaded_link_map)
        handled_sources = set(uploaded_link_map.keys())
        appended_sections = []
        for index, image_item in enumerate(image_items or [], start=1):
            image_source = str((image_item or {}).get("url") or "").strip()
            if not image_source or image_source in handled_sources:
                continue
            local_image_path = await materialize_ai_image(image_item)
            uploaded_link = await upload_image_to_hedgedoc(
                hedgedoc_client, markdown_config["hedgedoc_url"], local_image_path
            )
            alt_text = trim_text(
                strip_markdown_to_text((image_item or {}).get("alt_text") or f"图片 {index}"),
                80,
                f"图片 {index}",
            )
            appended_sections.append(f"![{alt_text}]({uploaded_link})")
            handled_sources.add(image_source)

        if appended_sections:
            appended_markdown = "\n\n".join(appended_sections)
            final_markdown = f"{final_markdown}\n\n".strip() if final_markdown else ""
            final_markdown = f"{final_markdown}{appended_markdown}".strip()

        note_id, _ = await create_hedgedoc_note(hedgedoc_client, markdown_config["hedgedoc_url"], final_markdown)
        publish_link = await get_hedgedoc_publish_link(hedgedoc_client, markdown_config["hedgedoc_url"], note_id)
        return final_markdown, publish_link
    finally:
        await hedgedoc_client.aclose()


async def send_ai_image_reply(context, roomid, wxpid, image_items):
    sent_paths = []
    for image_item in image_items or []:
        image_path = await materialize_ai_image(image_item)
        await context.api.send_image(wxid=roomid, path=image_path, wxpid=wxpid)
        sent_paths.append(image_path)
    return sent_paths


def build_markdown_article_payload(markdown_text, publish_link, roomid, event, markdown_config):
    room_name = resolve_room_name(event, roomid)
    fallback_title = f"{room_name} {DEFAULT_MARKDOWN_ARTICLE_TITLE}".strip()
    title = extract_markdown_title(markdown_text, fallback_title)
    desc = trim_text(strip_markdown_to_text(markdown_text), 200, title)
    publisher = resolve_send_article_publisher(markdown_config)
    return {
        "title": title,
        "desc": desc,
        "url": publish_link,
        "cover": markdown_config["article_cover_url"],
        "ghid": publisher["ghid"],
        "nickname": publisher["nickname"],
    }


async def open_with_redirect_capture(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    try:
        response = await async_http_request(
            method,
            url,
            follow_redirects=False,
            client=client,
            **kwargs,
        )
    except TimeoutError as exc:
        raise RuntimeError("HedgeDoc 请求超时") from exc
    except RuntimeError as exc:
        raise RuntimeError(f"HedgeDoc 请求失败: {exc}") from exc

    status_code = int(response.status_code)
    response_text = response.text
    if status_code >= 400 and status_code not in REDIRECT_STATUS_CODES:
        raise RuntimeError(f"HedgeDoc 请求失败，HTTP {status_code}: {response_text[:500]}")
    return status_code, response.headers, response_text


async def login_hedgedoc(hedgedoc_url, email, password):
    client = httpx.AsyncClient(follow_redirects=True, timeout=HEDGEDOC_REQUEST_TIMEOUT_SECONDS)
    login_url = urljoin(f"{hedgedoc_url}/", "login")
    try:
        response = await async_http_request(
            "POST",
            login_url,
            data={"email": email, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
            timeout=HEDGEDOC_REQUEST_TIMEOUT_SECONDS,
            client=client,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HedgeDoc 登录失败，HTTP {response.status_code}: {response.text[:500]}")

        me_response = await async_http_request(
            "GET",
            urljoin(f"{hedgedoc_url}/", "me"),
            timeout=HEDGEDOC_REQUEST_TIMEOUT_SECONDS,
            client=client,
        )
        if me_response.status_code != 200:
            raise RuntimeError(f"HedgeDoc 登录校验失败：/me 返回 {me_response.status_code}")
        json.loads(me_response.text or "{}")
    except TimeoutError as exc:
        await client.aclose()
        raise RuntimeError("HedgeDoc 登录超时") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        await client.aclose()
        raise RuntimeError("HedgeDoc 登录成功，但 /me 返回了异常响应") from exc
    except Exception:
        await client.aclose()
        raise
    return client


async def create_hedgedoc_note(client: httpx.AsyncClient, hedgedoc_url, markdown_text):
    status_code, headers, response_text = await open_with_redirect_capture(
        client,
        "POST",
        urljoin(f"{hedgedoc_url}/", "new"),
        content=str(markdown_text or "").encode("utf-8"),
        headers={"Content-Type": "text/markdown; charset=utf-8"},
        timeout=HEDGEDOC_REQUEST_TIMEOUT_SECONDS,
    )
    if status_code not in REDIRECT_STATUS_CODES:
        raise RuntimeError(f"HedgeDoc 创建文档失败，HTTP {status_code}: {response_text[:500]}")

    location = headers.get("Location") if headers is not None else ""
    if not location:
        raise RuntimeError("HedgeDoc 创建文档成功但未返回 Location 头")

    note_url = urljoin(f"{hedgedoc_url}/", str(location).lstrip("/"))
    note_id = note_url.rstrip("/").split("/")[-1]
    if not note_id:
        raise RuntimeError("HedgeDoc 创建文档后未解析到 note_id")
    return note_id, note_url


async def get_hedgedoc_publish_link(client: httpx.AsyncClient, hedgedoc_url, note_id):
    status_code, headers, response_text = await open_with_redirect_capture(
        client,
        "GET",
        urljoin(f"{hedgedoc_url}/", f"{note_id}/publish"),
        timeout=HEDGEDOC_REQUEST_TIMEOUT_SECONDS,
    )
    if status_code == 200:
        return urljoin(f"{hedgedoc_url}/", f"{note_id}/publish")
    if status_code in REDIRECT_STATUS_CODES:
        location = headers.get("Location") if headers is not None else ""
        if location:
            return urljoin(f"{hedgedoc_url}/", str(location).lstrip("/"))
    raise RuntimeError(f"HedgeDoc 获取发布链接失败，HTTP {status_code}: {response_text[:500]}")


async def upload_markdown_to_hedgedoc(markdown_text, markdown_config):
    hedgedoc_client = await login_hedgedoc(
        markdown_config["hedgedoc_url"],
        markdown_config["hedgedoc_email"],
        markdown_config["hedgedoc_password"],
    )
    try:
        note_id, _ = await create_hedgedoc_note(hedgedoc_client, markdown_config["hedgedoc_url"], markdown_text)
        return await get_hedgedoc_publish_link(hedgedoc_client, markdown_config["hedgedoc_url"], note_id)
    finally:
        await hedgedoc_client.aclose()


def normalize_room_ai_entry(item):
    if not isinstance(item, dict):
        return None

    roomid = normalize_text(item.get("roomid") or item.get("wxid"))
    if not roomid:
        return None

    return {
        "roomid": roomid,
        "base_url": str(item.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        "api_key": str(item.get("api_key") or "").strip(),
        "model": str(item.get("model") or "").strip(),
        "system_prompt": str(item.get("system_prompt") or item.get("prompt") or "").strip(),
    }


def build_legacy_room_ai_entry(config):
    if not isinstance(config, dict):
        return None
    return normalize_room_ai_entry(
        {
            "roomid": config.get("roomid") or config.get("wxid"),
            "base_url": config.get("base_url"),
            "api_key": config.get("api_key"),
            "model": config.get("model"),
            "system_prompt": config.get("system_prompt") or config.get("prompt"),
        }
    )


def get_room_config_map(config):
    room_config_map = {}
    raw_room_configs = config.get("room_configs") if isinstance(config, dict) else []

    if isinstance(raw_room_configs, list):
        for item in raw_room_configs:
            entry = normalize_room_ai_entry(item)
            if entry is not None:
                room_config_map[entry["roomid"]] = entry
        if room_config_map:
            return room_config_map

    legacy_entry = build_legacy_room_ai_entry(config)
    if legacy_entry is not None:
        room_config_map[legacy_entry["roomid"]] = legacy_entry
    return room_config_map


async def handle_message(event, context):
    roomid = normalize_text(event.conversation_wxid or "")
    room_config = get_room_config_map(context.config).get(roomid)
    if room_config is None:
        return {"handled": False, "detail": ""}

    pending_image_state = context.state.namespace(PENDING_IMAGE_STATE_NAMESPACE)
    cleanup_stale_pending_room_images(pending_image_state, now_milliseconds())

    sender_wxid = normalize_text(event.sender_wxid)
    current_account_wxid = resolve_current_account_wxid(event)

    if event.is_image:
        msgid = normalize_text(event.normalized_msgid)
        if not roomid or not sender_wxid or not msgid:
            return {"handled": False, "detail": ""}
        if current_account_wxid and sender_wxid == current_account_wxid:
            return {"handled": False, "detail": ""}

        pending_key = build_pending_room_image_key(roomid, sender_wxid)
        expires_at_ms = now_milliseconds() + resolve_pending_image_wait_seconds(context.config) * 1000
        await prime_pending_room_image(
            context,
            pending_image_state,
            pending_key,
            roomid,
            sender_wxid,
            msgid,
            event.normalized_wxpid,
            expires_at_ms,
        )
        return {"handled": False, "detail": ""}

    if get_message_type(event) != MESSAGE_TYPES.TEXT:
        return {"handled": False, "detail": ""}

    pending_key = build_pending_room_image_key(roomid, sender_wxid) if roomid and sender_wxid else ""
    pending_image_record = get_active_pending_room_image(pending_image_state, pending_key, now_milliseconds()) if pending_key else None
    if not is_at_current_account(event):
        if pending_key and pending_image_record is not None:
            pending_image_state.delete(pending_key)
        return {"handled": False, "detail": ""}

    base_url = room_config["base_url"]
    api_key = room_config["api_key"]
    model = room_config["model"]
    system_prompt = room_config["system_prompt"]
    if not api_key or not model:
        return {"handled": False, "detail": ""}

    raw_content = getattr(event, "content", "") or getattr(event, "normalized_content", "") or ""
    room_sender = getattr(event, "room_sender", "") or getattr(event, "sender_wxid", "") or ""
    message_text = remove_msg_at_text(strip_room_sender_prefix(raw_content, room_sender))
    prompt_image_path = ""
    if pending_key and pending_image_record is not None:
        try:
            prompt_image_path = await ensure_pending_room_image_path(context, roomid, pending_image_record)
        except Exception as exc:
            context.logger.warning(
                "群聊 AI 回复关联上一条图片失败，回退为纯文本提问",
                {
                    "roomid": roomid,
                    "model": model,
                    "sender": resolve_sender_name(event),
                    "pending_msgid": pending_image_record.get("msgid"),
                    "error": str(exc),
                },
            )
        finally:
            pending_image_state.delete(pending_key)

    if not message_text and not prompt_image_path:
        return {"handled": False, "detail": ""}

    try:
        user_message = build_ai_user_message(message_text, prompt_image_path)
    except Exception as exc:
        if not message_text:
            return {
                "handled": False,
                "detail": f"群聊 AI 回复准备图片输入失败: {exc}",
                "data": {"roomid": roomid, "model": model, "error": str(exc)},
            }
        prompt_image_path = ""
        user_message = build_ai_user_message(message_text)
        context.logger.warning(
            "群聊 AI 回复读取关联图片失败，已回退为纯文本提问",
            {"roomid": roomid, "model": model, "sender": resolve_sender_name(event), "error": str(exc)},
        )

    try:
        ai_result = await run_openai_compatible_chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[user_message],
            system_prompt=system_prompt,
        )
    except Exception as exc:
        context.logger.error(
            "群聊 AI 回复调用失败",
            {
                "roomid": roomid,
                "model": model,
                "sender": resolve_sender_name(event),
                "error": str(exc),
            },
        )
        return {
            "handled": False,
            "detail": f"群聊 AI 回复调用失败: {exc}",
            "data": {"roomid": roomid, "model": model, "error": str(exc)},
        }

    raw_reply_text = str(ai_result.get("content") or "").strip()
    structured_reply_images = ai_result.get("image_items") if isinstance(ai_result.get("image_items"), list) else []
    reply_images = merge_reply_image_items(raw_reply_text, structured_reply_images)
    reply_text = strip_markdown_image_syntax(raw_reply_text) if raw_reply_text else ""
    reply_text = str(reply_text or "").strip()
    has_reply_text = bool(reply_text)
    has_reply_images = bool(reply_images)
    if not has_reply_text and not has_reply_images:
        return {"handled": False, "detail": "模型未返回可发送的回复"}

    reply_mode = "text"
    article_payload = {}
    sent_image_paths = []
    markdown_config = normalize_markdown_delivery_config(context.config)
    markdown_detected = is_likely_markdown(raw_reply_text)
    markdown_reply_source = build_markdown_reply_with_images(reply_text, reply_images) if has_reply_text and has_reply_images else (raw_reply_text if has_reply_text else "")
    should_send_article = bool(has_reply_text and has_reply_images) or (has_reply_text and markdown_detected)
    if should_send_article:
        missing_markdown_fields = get_missing_markdown_delivery_fields(markdown_config)
        if missing_markdown_fields:
            context.logger.warning(
                "检测到 Markdown 回复，但 HedgeDoc 图文配置不完整，回退为文本发送",
                {
                    "roomid": roomid,
                    "model": model,
                    "missing_fields": missing_markdown_fields,
                    "has_images": has_reply_images,
                },
            )
        else:
            try:
                prepared_markdown_text, publish_link = await prepare_markdown_reply_for_hedgedoc(
                    markdown_reply_source,
                    reply_images,
                    markdown_config,
                )
                article_payload = build_markdown_article_payload(prepared_markdown_text, publish_link, roomid, event, markdown_config)
                await context.api.send_article(wxid=roomid, wxpid=event.normalized_wxpid, **article_payload)
                reply_mode = "article"
            except Exception as exc:
                context.logger.warning(
                    "群聊 AI Markdown 回复转图文失败，回退为文本发送",
                    {
                        "roomid": roomid,
                        "model": model,
                        "sender": resolve_sender_name(event),
                        "has_images": has_reply_images,
                        "error": str(exc),
                    },
                )

    try:
        if reply_mode == "article":
            pass
        elif has_reply_images and not has_reply_text:
            sent_image_paths = await send_ai_image_reply(context, roomid, event.normalized_wxpid, reply_images)
            reply_mode = "image"
        else:
            if has_reply_text:
                await context.api.send_text(wxid=roomid, content=reply_text, wxpid=event.normalized_wxpid)
            if has_reply_images:
                sent_image_paths = await send_ai_image_reply(context, roomid, event.normalized_wxpid, reply_images)
                reply_mode = "text+image" if has_reply_text else "image"
    except Exception as exc:
        context.logger.error(
            "群聊 AI 回复发送失败",
            {
                "roomid": roomid,
                "model": model,
                "sender": resolve_sender_name(event),
                "reply_mode": reply_mode,
                "error": str(exc),
            },
        )
        return {
            "handled": False,
            "detail": f"群聊 AI 回复发送失败: {exc}",
            "data": {"roomid": roomid, "model": model, "error": str(exc)},
        }

    log_message = "已发送群聊 AI Markdown 图文回复" if reply_mode == "article" else "已发送群聊 AI 回复"
    log_payload = {
        "roomid": roomid,
        "model": model,
        "sender": resolve_sender_name(event),
        "message_length": len(message_text),
        "reply_length": len(reply_text),
        "reply_mode": reply_mode,
        "image_count": len(reply_images),
        "has_prompt_image": bool(prompt_image_path),
    }
    if reply_mode == "article":
        log_payload.update({
            "article_url": article_payload.get("url"),
            "article_title": article_payload.get("title"),
        })
    if prompt_image_path:
        log_payload["prompt_image_path"] = prompt_image_path
    if sent_image_paths:
        log_payload["image_paths"] = sent_image_paths
    context.logger.info(log_message, log_payload)
    return {
        "handled": True,
        "detail": f"已对群聊 {roomid} 的消息发送 AI 回复",
        "data": {
            "roomid": roomid,
            "model": model,
            "sender": resolve_sender_name(event),
            "message": message_text,
            "prompt_image_path": prompt_image_path,
            "reply": reply_text,
            "reply_mode": reply_mode,
            "article_url": article_payload.get("url") or "",
            "article_title": article_payload.get("title") or "",
            "image_count": len(reply_images),
            "image_paths": sent_image_paths,
        },
    }
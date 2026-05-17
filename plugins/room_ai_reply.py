import asyncio
import json
import re
from http.cookiejar import CookieJar
from urllib import error, parse, request
from urllib.parse import urljoin

from ai_assistant import run_openai_compatible_chat_completion

from ._plugin_sdk import MESSAGE_TYPES, get_message_type, normalize_text


name = "room_ai_reply"
description = "按群聊配置 OpenAI-compatible AI 助手，自动回复群文本消息"
event_filters = ["text"]

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MARKDOWN_ARTICLE_GHID = ""
DEFAULT_MARKDOWN_ARTICLE_NICKNAME = ""
DEFAULT_MARKDOWN_ARTICLE_COVER_URL = "https://docs.hedgedoc.org/images/hedgedoc_logo_black.svg"
SEND_ARTICLE_COMPAT_GHID = "gh_hedgedoc_renderer"
SEND_ARTICLE_COMPAT_NICKNAME = "HedgeDoc 渲染器"
DEFAULT_MARKDOWN_ARTICLE_TITLE = "Markdown 回复"
HEDGEDOC_REQUEST_TIMEOUT_SECONDS = 20.0
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
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


class _NoRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


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


def build_model_prompt(event, roomid, message_text):
    sender_name = resolve_sender_name(event)
    room_name = resolve_room_name(event, roomid)
    return (
        f"群聊：{room_name}\n"
        f"发送者：{sender_name}\n"
        f"消息内容：{message_text}\n\n"
        "请直接给出适合发回群聊的回复。"
    )


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


def build_hedgedoc_openers():
    cookie_jar = CookieJar()
    redirect_opener = request.build_opener(request.HTTPCookieProcessor(cookie_jar))
    no_redirect_opener = request.build_opener(request.HTTPCookieProcessor(cookie_jar), _NoRedirectHandler())
    return redirect_opener, no_redirect_opener


def open_with_redirect_capture(opener, req, timeout):
    try:
        with opener.open(req, timeout=timeout) as response:
            return response.getcode(), response.headers, response.read().decode("utf-8", errors="ignore")
    except error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="ignore")
        if exc.code in REDIRECT_STATUS_CODES:
            return exc.code, exc.headers, response_text
        raise RuntimeError(f"HedgeDoc 请求失败，HTTP {exc.code}: {response_text[:500]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"HedgeDoc 请求失败: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("HedgeDoc 请求超时") from exc


def login_hedgedoc(hedgedoc_url, email, password):
    redirect_opener, no_redirect_opener = build_hedgedoc_openers()
    login_url = urljoin(f"{hedgedoc_url}/", "login")
    login_request = request.Request(
        login_url,
        data=parse.urlencode({"email": email, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )
    try:
        with redirect_opener.open(login_request, timeout=HEDGEDOC_REQUEST_TIMEOUT_SECONDS) as response:
            response.read()
    except error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HedgeDoc 登录失败，HTTP {exc.code}: {response_text[:500]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"HedgeDoc 登录失败: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("HedgeDoc 登录超时") from exc

    me_request = request.Request(urljoin(f"{hedgedoc_url}/", "me"), method="GET")
    try:
        with redirect_opener.open(me_request, timeout=HEDGEDOC_REQUEST_TIMEOUT_SECONDS) as response:
            response_text = response.read().decode("utf-8", errors="ignore")
            if response.getcode() != 200:
                raise RuntimeError(f"HedgeDoc 登录校验失败：/me 返回 {response.getcode()}")
            json.loads(response_text or "{}")
    except error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HedgeDoc 登录校验失败，HTTP {exc.code}: {response_text[:500]}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("HedgeDoc 登录成功，但 /me 返回了异常响应") from exc

    return no_redirect_opener


def create_hedgedoc_note(opener, hedgedoc_url, markdown_text):
    create_request = request.Request(
        urljoin(f"{hedgedoc_url}/", "new"),
        data=str(markdown_text or "").encode("utf-8"),
        headers={"Content-Type": "text/markdown; charset=utf-8"},
        method="POST",
    )
    status_code, headers, response_text = open_with_redirect_capture(opener, create_request, HEDGEDOC_REQUEST_TIMEOUT_SECONDS)
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


def get_hedgedoc_publish_link(opener, hedgedoc_url, note_id):
    publish_request = request.Request(urljoin(f"{hedgedoc_url}/", f"{note_id}/publish"), method="GET")
    status_code, headers, response_text = open_with_redirect_capture(opener, publish_request, HEDGEDOC_REQUEST_TIMEOUT_SECONDS)
    if status_code == 200:
        return urljoin(f"{hedgedoc_url}/", f"{note_id}/publish")
    if status_code in REDIRECT_STATUS_CODES:
        location = headers.get("Location") if headers is not None else ""
        if location:
            return urljoin(f"{hedgedoc_url}/", str(location).lstrip("/"))
    raise RuntimeError(f"HedgeDoc 获取发布链接失败，HTTP {status_code}: {response_text[:500]}")


def upload_markdown_to_hedgedoc(markdown_text, markdown_config):
    hedgedoc_opener = login_hedgedoc(
        markdown_config["hedgedoc_url"],
        markdown_config["hedgedoc_email"],
        markdown_config["hedgedoc_password"],
    )
    note_id, _ = create_hedgedoc_note(hedgedoc_opener, markdown_config["hedgedoc_url"], markdown_text)
    return get_hedgedoc_publish_link(hedgedoc_opener, markdown_config["hedgedoc_url"], note_id)


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
    if get_message_type(event) != MESSAGE_TYPES.TEXT:
        return {"handled": False, "detail": ""}

    roomid = normalize_text(event.conversation_wxid or "")
    room_config = get_room_config_map(context.config).get(roomid)
    if room_config is None:
        return {"handled": False, "detail": ""}

    base_url = room_config["base_url"]
    api_key = room_config["api_key"]
    model = room_config["model"]
    system_prompt = room_config["system_prompt"]
    if not api_key or not model:
        return {"handled": False, "detail": ""}

    raw_content = getattr(event, "content", "") or getattr(event, "normalized_content", "") or ""
    room_sender = getattr(event, "room_sender", "") or getattr(event, "sender_wxid", "") or ""
    message_text = strip_room_sender_prefix(raw_content, room_sender)
    if not message_text:
        return {"handled": False, "detail": ""}

    try:
        ai_result = await run_openai_compatible_chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=[{"role": "user", "content": build_model_prompt(event, roomid, message_text)}],
            system_prompt=system_prompt,
            temperature=0.4,
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

    reply_text = str(ai_result.get("content") or "").strip()
    if not reply_text:
        return {"handled": False, "detail": "模型未返回可发送的回复"}

    reply_mode = "text"
    article_payload = {}
    markdown_config = normalize_markdown_delivery_config(context.config)
    markdown_detected = is_likely_markdown(reply_text)
    if markdown_detected:
        missing_markdown_fields = get_missing_markdown_delivery_fields(markdown_config)
        if missing_markdown_fields:
            context.logger.warning(
                "检测到 Markdown 回复，但 HedgeDoc 图文配置不完整，回退为文本发送",
                {
                    "roomid": roomid,
                    "model": model,
                    "missing_fields": missing_markdown_fields,
                },
            )
        else:
            try:
                publish_link = await asyncio.to_thread(upload_markdown_to_hedgedoc, reply_text, markdown_config)
                article_payload = build_markdown_article_payload(reply_text, publish_link, roomid, event, markdown_config)
                await context.api.send_article(wxid=roomid, wxpid=event.normalized_wxpid, **article_payload)
                reply_mode = "article"
            except Exception as exc:
                context.logger.warning(
                    "群聊 AI Markdown 回复转图文失败，回退为文本发送",
                    {
                        "roomid": roomid,
                        "model": model,
                        "sender": resolve_sender_name(event),
                        "error": str(exc),
                    },
                )

    try:
        if reply_mode == "article":
            pass
        else:
            await context.api.send_text(wxid=roomid, content=reply_text, wxpid=event.normalized_wxpid)
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
    }
    if reply_mode == "article":
        log_payload.update({
            "article_url": article_payload.get("url"),
            "article_title": article_payload.get("title"),
        })
    context.logger.info(log_message, log_payload)
    return {
        "handled": True,
        "detail": f"已对群聊 {roomid} 的文本消息发送 AI 回复",
        "data": {
            "roomid": roomid,
            "model": model,
            "sender": resolve_sender_name(event),
            "message": message_text,
            "reply": reply_text,
            "reply_mode": reply_mode,
            "article_url": article_payload.get("url") or "",
            "article_title": article_payload.get("title") or "",
        },
    }
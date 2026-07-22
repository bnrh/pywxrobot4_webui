import json
import re
import time
import uuid
import base64
import hashlib
import hmac
import random
import math
import statistics
from pathlib import Path

from core.config import PROJECT_ROOT

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

# ==============================
# 插件元信息
# ==============================
name = "room_robot_reply"
description = "按群聊配置关键字回复或 OpenAI-compatible AI 助手，仅在被 @ 时自动回复"
event_filters = ["text", "image"]

DEFAULT_PENDING_IMAGE_WAIT_SECONDS = 8
PENDING_IMAGE_STATE_NAMESPACE = "pending_room_images"

IMAGE_UPLOAD_DIR = "uploads/room_robot_reply"    #选择图片后上传到项目中保存的文件夹

# ==============================
# 配置 Schema（网页端）
# ==============================
config_schema = [
    {
        "key": "room_configs",
        "label": "群聊 AI 助手（可选）",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "unique_by": ["roomid"],
        "description": "不配置 AI 时，仍可单独使用关键字回复。",
        "columns": [
            {
                "key": "roomid",
                "label": "群聊",
                "type": "select",
                "searchable": True,
                "options_source": "room_options",
                "required": True,
            },
            {
                "key": "base_url",
                "label": "Base URL",
                "type": "url",
                "default": "https://api.openai.com/v1",
            },
            {
                "key": "api_key",
                "label": "API Key",
                "type": "password",
            },
            {
                "key": "model",
                "label": "模型",
                "type": "text",
            },
            {
                "key": "system_prompt",
                "label": "系统提示词",
                "type": "textarea",
                "rows": 5,
            },
        ],
    },
    # ✅ 关键字回复（完全独立）
    {
        "key": "keyword_reply_rules",
        "label": "群聊关键字回复规则（优先于 AI）",
        "type": "object-list",
        "display_mode": "table",
        "default": [],
        "unique_by": ["roomid", "keyword"],
        "empty_text": "暂无规则，点击「新增」添加",
        "unique_message": "同一群内不能重复添加相同关键字",
        "description": "被 @ 时优先匹配关键词规则；命中后直接回复，不再调用 AI。文本回复直接填内容；图片回复通过「选择图片」或「选择文件夹」按钮填入路径。",
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
                "key": "keyword",
                "label": "匹配关键词（逗号分隔）",
                "type": "text",
                "default": "",
                "placeholder": "例如：多大了,age,你多大了",
                "required": True,
                "required_message": "关键词不能为空",
                "width": "wide",
                "editor_span": 5,
            },
            {
                "key": "full_match",
                "label": "是否全匹配",
                "type": "checkbox",
                "default": False,
            },
            {
                "key": "reply_content",
                "label": "回复内容 / Python 代码 / 图片路径",
                "type": "textarea",
                "default": "",
                "rows": 3,
                "placeholder":
"""固定文本：直接填写回复内容，可使用 {sender}、{message}、{roomid} 变量
执行代码：需定义 main(event, context) 函数并返回字符串
指定图片：点击「选择图片」按钮，路径会自动填入此处
随机图片：点击「选择文件夹」按钮，文件夹路径会自动填入此处""",
                "width": "wide",
                "editor_span": 9,
                "file_pickers": [
                    {
                        "type": "project-image",
                        "label": "选择图片",
                        "accept": "image/*,.png,.jpg,.jpeg,.gif,.webp,.bmp",
                        "upload_dir": IMAGE_UPLOAD_DIR,
                    },
                    {
                        "type": "project-file",
                        "label": "选择文件",
                        "accept": "image/*,.png,.jpg,.jpeg,.gif,.webp,.bmp",
                    },
                    {
                        "type": "project-folder",
                        "label": "选择文件夹",
                    },
                ],
            },
            {
                "key": "reply_type",
                "label": "回复类型",
                "type": "select",
                "options": [
                    {"label": "固定文本", "value": "text"},
                    {"label": "执行代码", "value": "code"},
                    {"label": "指定图片", "value": "image_fixed"},
                    {"label": "随机图片", "value": "image_random"},
                ],
                "default": "text",
            },

        ],
    },
    {
        "key": "pending_image_wait_seconds",
        "label": "图片关联等待时间(秒)",
        "type": "number",
        "default": DEFAULT_PENDING_IMAGE_WAIT_SECONDS,
        "min": 1,
        "max": 60,
    },
]

# ==============================
# 工具函数
# ==============================

def now_ms():
    return int(time.time() * 1000)

def build_pending_key(roomid, sender_wxid):
    return f"{roomid}|{sender_wxid}"

def cleanup_pending(state, now):
    for k in list(state.keys()):
        e = state.get(k)
        if not e:
            continue
        if e.get("expires_at_ms", 0) <= now:
            state.pop(k, None)

async def prime_pending_image(context, state, key, roomid, sender_wxid, msgid, wxpid, expire):
    state.set(
        key,
        {
            "roomid": roomid,
            "sender_wxid": sender_wxid,
            "msgid": msgid,
            "wxpid": wxpid,
            "expires_at_ms": expire,
        },
        ttl_seconds=int((expire - now_ms()) / 1000) + 5,
    )

def resolve_sender_name(event):
    for v in [
        getattr(event, "room_sender_display_name", ""),
        getattr(event, "sender_display_name", ""),
        getattr(event, "room_sender", ""),
        getattr(event, "sender_wxid", ""),
    ]:
        if v and str(v).strip():
            return str(v).strip()
    return "群成员"

def strip_sender_prefix(content, sender):
    if not content or not sender:
        return content or ""
    for p in [f"{sender}:", f"{sender}：", f"{sender}\n"]:
        if content.startswith(p):
            return content[len(p):].strip()
    return content.strip()

# ✅ 最终版 @ 判断（不依赖 current_account_wxid）
_AT_SPACE_RE = re.compile(r"[\u2000-\u200A\u2028\u2029\u3000\s]+")

def is_at_me(event):
    raw = getattr(event, "content", "") or ""
    if not raw:
        return False

    # 情况 1：包含 @ 字样（最通用）
    if "@" in raw:
        return True

    # 情况 2：XML <at> 标签（部分客户端）
    if "<at>" in raw and "</at>" in raw:
        return True

    return False

def remove_at_text(content):
    # 移除 XML @ 标签
    content = re.sub(r"<at>.*?</at>", "", content or "")
    # 移除 @昵称 + 各种空格（含 \u2005）
    content = re.sub(r"@[^@\n]+?[\u2005\u2003\s]*", "", content)
    return _AT_SPACE_RE.sub(" ", content).strip()

# ==============================
# 图片工具函数（参考 enter_room_tip.py）
# ==============================

def normalize_image_path(value):
    """标准化图片路径格式"""
    return str(value or "").strip().replace("\\", "/")

def resolve_image_path(raw_path):
    """将配置中的图片路径解析为绝对路径，不存在则返回 None"""
    normalized_path = normalize_image_path(raw_path)
    if not normalized_path:
        return None
    candidate = Path(normalized_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate if candidate.exists() else None

def pick_random_image_from_folder(folder_path):
    """从文件夹中随机选一张图片"""
    normalized_path = normalize_image_path(folder_path)
    if not normalized_path:
        return None
    candidate = Path(normalized_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    if not candidate.is_dir():
        return None

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    images = [
        f for f in candidate.iterdir()
        if f.is_file() and f.suffix.lower() in image_exts
    ]
    return random.choice(images) if images else None

# ==============================
# 关键字逻辑
# ==============================

KEYWORD_SEP_RE = re.compile(r"[,，]")

def normalize_keywords(keyword_raw: str):
    if not keyword_raw:
        return []

    return [
        k.strip().lower()
        for k in KEYWORD_SEP_RE.split(keyword_raw)
        if k.strip()
    ]

def get_keyword_rules(config):
    rules = config.get("keyword_reply_rules")
    if not isinstance(rules, list):
        return {}

    m = {}
    for r in rules:
        roomid = normalize_text(r.get("roomid"))
        keyword_raw = normalize_text(r.get("keyword"))
        if not roomid or not keyword_raw:
            continue

        keywords = normalize_keywords(keyword_raw)
        if not keywords:
            continue

        m.setdefault(roomid, []).append({
            "keywords": keywords,
            "exact": bool(r.get("full_match", False)),
            "type": r.get("reply_type", "text"),
            "content": (r.get("reply_content") or "").strip(),
        })

    return m

def match_keyword(text, rules, roomid):
    if not text or not rules:
        return None

    text = text.lower()

    for r in rules.get(roomid, []):
        keywords = r.get("keywords", [])
        exact = r.get("exact", False)

        if not keywords:
            continue

        # ✅ 精确匹配
        if exact:
            pattern = (
                r"(?:^|\s)"
                + "("
                + "|".join(re.escape(k) for k in keywords)
                + r")"
                + r"(?:\s|$|[?？!！])"
            )
            if re.search(pattern, text):
                return r

        # ✅ 模糊匹配（包含）
        else:
            if any(kw in text for kw in keywords):
                return r

    return None

def render_text(tpl, event, msg):
    return tpl.format(
        sender=resolve_sender_name(event),
        room_sender=normalize_text(event.room_sender),
        message=msg,
        roomid=normalize_text(event.conversation_wxid),
    )

def run_code(code, event, context, msg):
    safe_builtins = {
        # 基础
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "round": round,
        "len": len,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "sorted": sorted,
        "any": any,
        "all": all,

        # 常用模块
        "json": json,
        "re": re,
        "time": time,
        "uuid": uuid,
        "base64": base64,
        "hashlib": hashlib,
        "hmac": hmac,
        "random": random,
        "math": math,
        "statistics": statistics,
        "datetime": __import__("datetime"),
        "calendar": __import__("calendar"),

        # 必须
        "__import__": __import__,
    }

    ns = {
        "__builtins__": safe_builtins,
        "event": event,
        "context": context,
        "message": msg,
    }

    try:
        compiled = compile(code, "<user_code>", "exec")
        exec(compiled, ns)

        main_func = ns.get("main")
        if not callable(main_func):
            context.logger.warning("关键字代码未定义 main(event, context)")
            return ""

        result = main_func(event, context)
        if result:
            return str(result).strip()

    except SyntaxError as e:
        context.logger.warning(
            "关键字代码语法错误",
            {"error": str(e), "lineno": e.lineno}
        )
    except Exception as e:
        context.logger.warning(
            "关键字代码执行失败",
            {"error": str(e)}
        )

    return ""

# ==============================
# ✅ 主入口
# ==============================

async def handle_message(event, context):
    roomid = normalize_text(event.conversation_wxid)
    if not roomid:
        return {"handled": False}

    state = context.state.namespace(PENDING_IMAGE_STATE_NAMESPACE)
    cleanup_pending(state, now_ms())

    # ---------- 1. 图片 ----------
    if getattr(event, "is_image", False):
        sender = normalize_text(event.sender_wxid)
        msgid = normalize_text(event.normalized_msgid)
        if sender and msgid:
            key = build_pending_key(roomid, sender)
            expire = now_ms() + int(context.config.get("pending_image_wait_seconds", 8)) * 1000
            await prime_pending_image(
                context, state, key, roomid, sender, msgid,
                event.normalized_wxpid, expire
            )
        return {"handled": False}

    # ---------- 2. ✅ 正确判断文本消息 ----------
    raw = getattr(event, "content", "") or ""
    msg_type = getattr(event, "msg_type", None)

    # ✅ pywxrobot4_webui 下唯一靠谱的判断方式
    if msg_type != 1 or not isinstance(raw, str) or not raw.strip():
        context.logger.debug("非文本消息", {"msg_type": msg_type})
        return {"handled": False}

    # ---------- 3. 是否被 @ ----------
    if not is_at_me(event):
        context.logger.debug("未命中 @", {"content": raw})
        return {"handled": False}

    # ---------- 4. 清洗消息 ----------
    msg = remove_at_text(
        strip_sender_prefix(raw, getattr(event, "room_sender", ""))
    ).strip()
    if not msg:
        context.logger.debug("清洗后消息为空", {"raw": raw})
        return {"handled": False}

    context.logger.debug("进入业务逻辑", {"msg": msg})

    # ---------- 5. 关键字优先 ----------
    rules = get_keyword_rules(context.config)
    hit = match_keyword(msg, rules, roomid)
    if hit:
        reply_type = hit["type"]
        content = hit["content"]

        # ✅ 固定文本
        if reply_type == "text":
            if content:
                reply = render_text(content, event, msg)
                if reply:
                    await context.api.send_text(
                        wxid=roomid,
                        content=reply,
                        wxpid=event.normalized_wxpid,
                    )
                    context.logger.info("已发送关键字文本回复", {"reply": reply})
                    return {"handled": True, "detail": "keyword_text"}
            return {"handled": False}

        # ✅ 执行代码
        elif reply_type == "code":
            reply = run_code(content, event, context, msg)
            if reply:
                await context.api.send_text(
                    wxid=roomid,
                    content=reply,
                    wxpid=event.normalized_wxpid,
                )
                context.logger.info("已发送关键字代码回复", {"reply": reply})
                return {"handled": True, "detail": "keyword_code"}
            return {"handled": False}

        # ✅ 指定图片（reply_content 为图片路径）
        elif reply_type == "image_fixed":
            image_path = resolve_image_path(content)
            if image_path is not None:
                if image_path.exists():
                    await context.api.send_image(
                        wxid=roomid,
                        path=str(image_path),
                        wxpid=event.normalized_wxpid,
                    )
                    context.logger.info("已发送指定图片回复", {
                        "path": str(image_path),
                        "keywords": hit["keywords"],
                    })
                    return {"handled": True, "detail": "keyword_image_fixed"}
                else:
                    context.logger.warning("指定图片不存在，已跳过", {
                        "path": str(image_path),
                        "keywords": hit["keywords"],
                    })
            else:
                context.logger.warning("指定图片路径为空或无效", {
                    "content": content,
                    "keywords": hit["keywords"],
                })
            return {"handled": False}

        # ✅ 随机图片（reply_content 为文件夹路径）
        elif reply_type == "image_random":
            random_image = pick_random_image_from_folder(content)
            if random_image is not None:
                await context.api.send_image(
                    wxid=roomid,
                    path=str(random_image),
                    wxpid=event.normalized_wxpid,
                )
                context.logger.info("已发送随机图片回复", {
                    "path": str(random_image),
                    "keywords": hit["keywords"],
                })
                return {"handled": True, "detail": "keyword_image_random"}
            else:
                context.logger.warning("随机图片文件夹为空或无效", {
                    "content": content,
                    "keywords": hit["keywords"],
                })
            return {"handled": False}

    # ---------- 6. AI（可选） ----------
    return {"handled": False}

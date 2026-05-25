import asyncio
import json
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from itertools import count
from os import PathLike
from pathlib import Path
import re
from time import monotonic
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from ai_assistant import (
    AI_ASSISTANT_SETTINGS_KEY,
    PROVIDER_CATALOG,
    build_ai_assistant_payload,
    get_default_ai_assistant_settings,
    load_openai_compatible_model_options,
    normalize_ai_assistant_settings,
    resolve_ai_assistant_prompt_plugin,
    run_ai_assistant,
)
from client import WxRobotApiClient
from config import (
    CONFIG_PATH,
    PROJECT_ROOT,
    SETTINGS_DB_PATH,
    PluginServiceSettings,
    WebuiSettingsStore,
    normalize_plugin_module_name,
)
from manager import PluginManager
from message import MessageEvent
from plugin_base import PluginContext


FRONTEND_DIR = Path(__file__).with_name("frontend")
FRONTEND_INDEX_PAGE = FRONTEND_DIR / "index.html"
STATIC_DIR = Path(__file__).with_name("static")
LOG_DIR = SETTINGS_DB_PATH.parent / "logs"
PLUGIN_ASSET_UPLOAD_ROOT = PROJECT_ROOT / "uploads"
PLUGIN_ASSET_MAX_BYTES = 10 * 1024 * 1024
PLUGIN_ASSET_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
RECENT_MESSAGE_LIMIT = 200
PLUGIN_LOG_LIMIT = 1000
RESTART_REQUIRED_FIELDS = {"host", "port", "callback_path", "worker_count", "queue_size"}
SYSTEM_SETTINGS_FIELDS = (
    "host",
    "port",
    "callback_path",
    "wxrobot_api_base_url",
    "request_timeout",
    "worker_count",
    "queue_size",
    "heartbeat_interval_seconds",
    "image_download_flag",
    "image_download_wait",
    "image_download_timeout",
)
REMOVED_PLUGIN_MODULES = {normalize_plugin_module_name("webui.plugins.monitor_biz")}
INVITE_TO_ROOM_PLUGIN_MODULE = normalize_plugin_module_name("webui.plugins.invite_to_toom")
ENTER_ROOM_TIP_PLUGIN_MODULE = normalize_plugin_module_name("plugins.enter_room_tip")
ROOM_AI_REPLY_PLUGIN_MODULE = normalize_plugin_module_name("plugins.room_ai_reply")
DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE = normalize_plugin_module_name("plugins.download_recent_user_images")
LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) \| (?P<level>[A-Z]+)\s+\| (?P<module>[^:]+):(?P<function>[^:]+):(?P<line>\d+) - (?P<message>.*)$"
)
LOG_TIME_RANGE_TO_DELTA = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "1d": timedelta(days=1),
}
AI_ASSISTANT_CONVERSATIONS_KEY = "ai_assistant_conversations"
AI_ASSISTANT_CONVERSATION_LIMIT = 40
AI_ASSISTANT_MESSAGE_LIMIT = 240
AI_ASSISTANT_JOB_LIMIT = 80
AI_ASSISTANT_JOB_TERMINAL_STATUSES = {"completed", "failed", "stopped"}
AI_ASSISTANT_JOB_ACTIVE_STATUSES = {"queued", "running", "stopping"}
MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES = {"completed", "failed", "stopped"}
MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES = {"queued", "running", "stopping"}
ai_assistant_storage_lock = asyncio.Lock()
ai_assistant_job_lock = asyncio.Lock()
ai_assistant_jobs: dict[str, dict[str, Any]] = {}
ai_assistant_job_tasks: dict[str, asyncio.Task[Any]] = {}


class PluginToggleRequest(BaseModel):
    enabled: bool


class PluginConfigUpdateRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class PluginExecuteRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class SystemSettingsUpdateRequest(BaseModel):
    host: str
    port: int = Field(..., ge=1, le=65535)
    callback_path: str
    api_base_url: str
    request_timeout: float = Field(..., gt=0, le=120)
    worker_count: int = Field(..., ge=1, le=32)
    queue_size: int = Field(..., ge=1, le=100000)
    heartbeat_interval_seconds: int = Field(..., ge=0, le=3600)


class AiAssistantSettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class AiAssistantChatMessage(BaseModel):
    role: str
    content: str = ""
    reasoning_content: str = ""


class AiAssistantChatRequest(BaseModel):
    provider: str | None = None
    provider_config_id: str | None = None
    prompt_plugin_id: str | None = None
    model: str | None = None
    messages: list[AiAssistantChatMessage] = Field(default_factory=list)


class AiAssistantChatJobCreateRequest(BaseModel):
    conversation_id: str
    prompt: str
    provider: str | None = None
    provider_config_id: str | None = None
    prompt_plugin_id: str | None = None
    model: str | None = None


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_conversation_label(value: Any, limit: int = 32) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    return text if len(text) <= limit else f"{text[:limit]}..."


def _default_ai_assistant_conversation_title(created_at: str | None = None) -> str:
    if created_at:
        try:
            parsed = datetime.fromisoformat(created_at)
            return f"新对话 {parsed.strftime('%m-%d %H:%M')}"
        except ValueError:
            pass
    return "新对话"


def _derive_ai_assistant_conversation_title(messages: list[dict[str, Any]] | None, fallback: str = "新对话") -> str:
    for message in messages or []:
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        content = _safe_conversation_label(message.get("content"), limit=28)
        if content:
            return content
    return fallback


def _normalize_ai_assistant_tool_trace_payload(item: Any) -> dict[str, Any]:
    payload = item if isinstance(item, dict) else {}
    status = str(payload.get("status") or "ok").strip().lower()
    if status not in {"running", "ok", "error"}:
        status = "ok"
    return {
        "id": str(payload.get("id") or payload.get("name") or uuid4().hex),
        "name": str(payload.get("name") or "unknown_tool"),
        "arguments": payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
        "status": status,
        "error": str(payload.get("error") or ""),
    }


def _normalize_ai_assistant_message_payload(message: Any) -> dict[str, Any]:
    payload = message if isinstance(message, dict) else {}
    role = str(payload.get("role") or "assistant").strip().lower()
    if role not in {"user", "assistant"}:
        role = "assistant"
    created_at = str(payload.get("created_at") or "").strip() or _now_iso()
    updated_at = str(payload.get("updated_at") or "").strip() or created_at
    status = str(payload.get("status") or ("running" if role == "assistant" and payload.get("progress_message") else "completed")).strip().lower()
    if status not in {"running", "completed", "failed", "stopped"}:
        status = "completed"
    error_flag = bool(payload.get("error"))
    if error_flag and status == "completed":
        status = "failed"
    tool_traces = payload.get("tool_traces") if isinstance(payload.get("tool_traces"), list) else []
    return {
        "id": str(payload.get("id") or uuid4().hex),
        "role": role,
        "content": str(payload.get("content") or ""),
        "reasoning_content": str(payload.get("reasoning_content") or ""),
        "provider": str(payload.get("provider") or ""),
        "provider_label": str(payload.get("provider_label") or ""),
        "provider_config_id": str(payload.get("provider_config_id") or ""),
        "prompt_plugin_id": str(payload.get("prompt_plugin_id") or ""),
        "prompt_plugin_name": str(payload.get("prompt_plugin_name") or ""),
        "model": str(payload.get("model") or ""),
        "tool_traces": [_normalize_ai_assistant_tool_trace_payload(item) for item in tool_traces],
        "progress_message": str(payload.get("progress_message") or ""),
        "status": status,
        "error": error_flag,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _build_new_ai_assistant_conversation(title: str = "") -> dict[str, Any]:
    created_at = _now_iso()
    normalized_title = _safe_conversation_label(title, limit=40) or _default_ai_assistant_conversation_title(created_at)
    return {
        "id": uuid4().hex,
        "title": normalized_title,
        "created_at": created_at,
        "updated_at": created_at,
        "messages": [],
    }


def _normalize_ai_assistant_conversation_payload(conversation: Any) -> dict[str, Any]:
    payload = conversation if isinstance(conversation, dict) else {}
    created_at = str(payload.get("created_at") or "").strip() or _now_iso()
    messages = [_normalize_ai_assistant_message_payload(item) for item in (payload.get("messages") if isinstance(payload.get("messages"), list) else [])]
    title = _safe_conversation_label(payload.get("title"), limit=40) or _derive_ai_assistant_conversation_title(messages, _default_ai_assistant_conversation_title(created_at))
    return {
        "id": str(payload.get("id") or uuid4().hex),
        "title": title,
        "created_at": created_at,
        "updated_at": str(payload.get("updated_at") or "").strip() or created_at,
        "messages": messages[-AI_ASSISTANT_MESSAGE_LIMIT:],
    }


def _normalize_ai_assistant_conversation_store(payload: Any) -> dict[str, Any]:
    raw_payload = payload if isinstance(payload, dict) else {}
    conversations = [_normalize_ai_assistant_conversation_payload(item) for item in (raw_payload.get("conversations") if isinstance(raw_payload.get("conversations"), list) else [])]
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for conversation in conversations:
        if conversation["id"] in seen_ids:
            continue
        seen_ids.add(conversation["id"])
        deduped.append(conversation)
    if not deduped:
        deduped.append(_build_new_ai_assistant_conversation())
    active_conversation_id = str(raw_payload.get("active_conversation_id") or "").strip()
    if active_conversation_id not in {item["id"] for item in deduped}:
        active_conversation_id = deduped[0]["id"]
    return {
        "active_conversation_id": active_conversation_id,
        "conversations": deduped[:AI_ASSISTANT_CONVERSATION_LIMIT],
    }


def _load_ai_assistant_conversation_store() -> dict[str, Any]:
    payload = WebuiSettingsStore().get_json_setting(AI_ASSISTANT_CONVERSATIONS_KEY, {})
    return _normalize_ai_assistant_conversation_store(payload)


def _save_ai_assistant_conversation_store(store: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_ai_assistant_conversation_store(store)
    WebuiSettingsStore().set_json_setting(AI_ASSISTANT_CONVERSATIONS_KEY, normalized)
    return normalized


def _get_ai_assistant_conversation(store: dict[str, Any], conversation_id: str) -> dict[str, Any] | None:
    normalized_id = str(conversation_id or "").strip()
    for conversation in store.get("conversations", []):
        if conversation["id"] == normalized_id:
            return conversation
    return None


def _move_ai_assistant_conversation_to_front(store: dict[str, Any], conversation_id: str) -> None:
    conversations = store.get("conversations", [])
    for index, conversation in enumerate(conversations):
        if conversation["id"] != conversation_id:
            continue
        conversations.insert(0, conversations.pop(index))
        return


def _build_ai_assistant_conversation_summary(conversation: dict[str, Any], active_conversation_id: str) -> dict[str, Any]:
    messages = conversation.get("messages", []) if isinstance(conversation.get("messages"), list) else []
    last_message = messages[-1] if messages else {}
    last_preview = _safe_conversation_label(last_message.get("content") or last_message.get("progress_message") or "暂无消息", limit=54)
    return {
        "id": conversation["id"],
        "title": conversation["title"],
        "created_at": conversation["created_at"],
        "updated_at": conversation["updated_at"],
        "message_count": len(messages),
        "last_message_preview": last_preview,
        "last_message_role": str(last_message.get("role") or ""),
        "has_running_message": any(str(message.get("status") or "") == "running" for message in messages),
        "is_active": conversation["id"] == active_conversation_id,
    }


def _build_ai_assistant_conversation_payload(store: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_store = _normalize_ai_assistant_conversation_store(store or _load_ai_assistant_conversation_store())
    active_conversation_id = normalized_store["active_conversation_id"]
    current_conversation = _get_ai_assistant_conversation(normalized_store, active_conversation_id) or normalized_store["conversations"][0]
    return {
        "active_conversation_id": active_conversation_id,
        "conversations": [
            _build_ai_assistant_conversation_summary(conversation, active_conversation_id)
            for conversation in normalized_store["conversations"]
        ],
        "current_conversation": deepcopy(current_conversation),
    }


async def _mutate_ai_assistant_conversation_store(mutator) -> tuple[Any, dict[str, Any]]:
    async with ai_assistant_storage_lock:
        store = _load_ai_assistant_conversation_store()
        result = mutator(store)
        normalized_store = _save_ai_assistant_conversation_store(store)
    return result, normalized_store


async def _ensure_ai_assistant_conversation_payload() -> dict[str, Any]:
    async with ai_assistant_storage_lock:
        store = _save_ai_assistant_conversation_store(_load_ai_assistant_conversation_store())
    return _build_ai_assistant_conversation_payload(store)


async def _create_ai_assistant_conversation_payload() -> dict[str, Any]:
    def mutator(store: dict[str, Any]) -> None:
        conversation = _build_new_ai_assistant_conversation()
        store["conversations"].insert(0, conversation)
        store["active_conversation_id"] = conversation["id"]

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def _activate_ai_assistant_conversation_payload(conversation_id: str) -> dict[str, Any]:
    normalized_id = str(conversation_id or "").strip()

    def mutator(store: dict[str, Any]) -> None:
        conversation = _get_ai_assistant_conversation(store, normalized_id)
        if conversation is None:
            raise ValueError("未找到指定对话")
        store["active_conversation_id"] = normalized_id
        _move_ai_assistant_conversation_to_front(store, normalized_id)

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def _clear_ai_assistant_conversation_payload(conversation_id: str) -> dict[str, Any]:
    normalized_id = str(conversation_id or "").strip()

    def mutator(store: dict[str, Any]) -> None:
        conversation = _get_ai_assistant_conversation(store, normalized_id)
        if conversation is None:
            raise ValueError("未找到指定对话")
        conversation["messages"] = []
        conversation["updated_at"] = _now_iso()
        conversation["title"] = _default_ai_assistant_conversation_title(conversation["updated_at"])
        store["active_conversation_id"] = normalized_id
        _move_ai_assistant_conversation_to_front(store, normalized_id)

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def _append_ai_assistant_chat_placeholders(
    conversation_id: str,
    prompt: str,
    provider: str,
    model: str,
    prompt_plugin_id: str = "",
    prompt_plugin_name: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_id = str(conversation_id or "").strip()
    normalized_prompt = str(prompt or "").strip()
    if not normalized_prompt:
        raise ValueError("问题不能为空")

    context: dict[str, Any] = {}

    def mutator(store: dict[str, Any]) -> None:
        conversation = _get_ai_assistant_conversation(store, normalized_id)
        if conversation is None:
            raise ValueError("未找到指定对话")
        now = _now_iso()
        user_message = _normalize_ai_assistant_message_payload(
            {
                "id": uuid4().hex,
                "role": "user",
                "content": normalized_prompt,
                "status": "completed",
                "created_at": now,
                "updated_at": now,
            }
        )
        assistant_message = _normalize_ai_assistant_message_payload(
            {
                "id": uuid4().hex,
                "role": "assistant",
                "content": "",
                "provider": provider,
                "provider_label": PROVIDER_CATALOG.get(provider, {}).get("label", ""),
                "prompt_plugin_id": str(prompt_plugin_id or ""),
                "prompt_plugin_name": str(prompt_plugin_name or ""),
                "model": model,
                "status": "running",
                "progress_message": "等待模型响应...",
                "created_at": now,
                "updated_at": now,
            }
        )
        conversation["messages"] = [*conversation.get("messages", []), user_message, assistant_message][-AI_ASSISTANT_MESSAGE_LIMIT:]
        conversation["updated_at"] = now
        if not conversation.get("title") or str(conversation.get("title") or "").startswith("新对话"):
            conversation["title"] = _derive_ai_assistant_conversation_title(conversation["messages"], _default_ai_assistant_conversation_title(now))
        store["active_conversation_id"] = normalized_id
        _move_ai_assistant_conversation_to_front(store, normalized_id)
        context["user_message_id"] = user_message["id"]
        context["assistant_message_id"] = assistant_message["id"]

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return context, _build_ai_assistant_conversation_payload(store)


async def _update_ai_assistant_message_payload(conversation_id: str, message_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    normalized_updates = dict(updates or {})

    def mutator(store: dict[str, Any]) -> None:
        conversation = _get_ai_assistant_conversation(store, normalized_conversation_id)
        if conversation is None:
            raise ValueError("未找到指定对话")
        target_message = next((item for item in conversation.get("messages", []) if item.get("id") == normalized_message_id), None)
        if target_message is None:
            raise ValueError("未找到指定消息")
        for key, value in normalized_updates.items():
            target_message[key] = value
        target_message["updated_at"] = _now_iso()
        conversation["updated_at"] = target_message["updated_at"]
        if conversation.get("messages") and (not conversation.get("title") or str(conversation.get("title") or "").startswith("新对话")):
            conversation["title"] = _derive_ai_assistant_conversation_title(conversation["messages"], _default_ai_assistant_conversation_title(conversation["updated_at"]))
        _move_ai_assistant_conversation_to_front(store, normalized_conversation_id)

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def _get_ai_assistant_message_payload(conversation_id: str, message_id: str) -> dict[str, Any] | None:
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    async with ai_assistant_storage_lock:
        store = _load_ai_assistant_conversation_store()
    conversation = _get_ai_assistant_conversation(store, normalized_conversation_id)
    if conversation is None:
        return None
    message = next((item for item in conversation.get("messages", []) if item.get("id") == normalized_message_id), None)
    return deepcopy(message) if message is not None else None


async def _get_ai_assistant_conversation_history(conversation_id: str) -> list[dict[str, Any]]:
    async with ai_assistant_storage_lock:
        store = _load_ai_assistant_conversation_store()
    conversation = _get_ai_assistant_conversation(store, conversation_id)
    if conversation is None:
        raise ValueError("未找到指定对话")
    return [
        {
            "role": message.get("role", "assistant"),
            "content": message.get("content", ""),
            "reasoning_content": message.get("reasoning_content", ""),
        }
        for message in conversation.get("messages", [])
        if str(message.get("role") or "") in {"user", "assistant"}
    ]


def _normalize_ai_assistant_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(job)
    payload.setdefault("progress_message", "")
    payload.setdefault("stage", "queued")
    payload.setdefault("status", "queued")
    payload.setdefault("error", "")
    payload.setdefault("provider_config_id", "")
    payload.setdefault("prompt_plugin_id", "")
    payload.setdefault("prompt_plugin_name", "")
    payload.setdefault("created_at", _now_iso())
    payload.setdefault("updated_at", payload["created_at"])
    return payload


async def _set_ai_assistant_job(job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    normalized_job_id = str(job_id or "").strip() or uuid4().hex
    async with ai_assistant_job_lock:
        current = _normalize_ai_assistant_job_payload(ai_assistant_jobs.get(normalized_job_id, {"id": normalized_job_id}))
        current.update(updates)
        current["id"] = normalized_job_id
        current["updated_at"] = _now_iso()
        ai_assistant_jobs[normalized_job_id] = current

        completed_jobs = [
            item for item in ai_assistant_jobs.values()
            if str(item.get("status") or "") in AI_ASSISTANT_JOB_TERMINAL_STATUSES
        ]
        if len(completed_jobs) > AI_ASSISTANT_JOB_LIMIT:
            completed_jobs.sort(key=lambda item: str(item.get("updated_at") or ""))
            for stale in completed_jobs[:-AI_ASSISTANT_JOB_LIMIT]:
                ai_assistant_jobs.pop(str(stale.get("id") or ""), None)

        return deepcopy(current)


async def _get_ai_assistant_job(job_id: str) -> dict[str, Any] | None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        job = ai_assistant_jobs.get(normalized_job_id)
        return deepcopy(job) if job is not None else None


async def _set_ai_assistant_job_task(job_id: str, task: asyncio.Task[Any]) -> None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        ai_assistant_job_tasks[normalized_job_id] = task


async def _get_ai_assistant_job_task(job_id: str) -> asyncio.Task[Any] | None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        return ai_assistant_job_tasks.get(normalized_job_id)


async def _pop_ai_assistant_job_task(job_id: str) -> asyncio.Task[Any] | None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        return ai_assistant_job_tasks.pop(normalized_job_id, None)


async def _mark_ai_assistant_job_stopped(
    job_id: str,
    conversation_id: str,
    assistant_message_id: str,
    provider_key: str,
    provider_config_id: str | None,
    prompt_plugin_id: str | None,
    prompt_plugin_name: str | None,
    selected_model: str,
    progress_message: str = "本次对话已手动停止。",
) -> dict[str, Any]:
    current_job = await _get_ai_assistant_job(job_id)
    if current_job is not None and str(current_job.get("status") or "") == "stopped":
        return current_job

    current_message = await _get_ai_assistant_message_payload(conversation_id, assistant_message_id) or {}
    preserved_content = str(current_message.get("content") or "").strip()
    await _update_ai_assistant_message_payload(
        conversation_id,
        assistant_message_id,
        {
            "content": preserved_content or progress_message,
            "reasoning_content": str(current_message.get("reasoning_content") or ""),
            "tool_traces": current_message.get("tool_traces") if isinstance(current_message.get("tool_traces"), list) else [],
            "progress_message": progress_message,
            "status": "stopped",
            "error": False,
            "provider": str(current_message.get("provider") or provider_key),
            "provider_label": str(current_message.get("provider_label") or PROVIDER_CATALOG.get(provider_key, {}).get("label", "")),
            "provider_config_id": str(current_message.get("provider_config_id") or provider_config_id or ""),
            "prompt_plugin_id": str(current_message.get("prompt_plugin_id") or prompt_plugin_id or ""),
            "prompt_plugin_name": str(current_message.get("prompt_plugin_name") or prompt_plugin_name or ""),
            "model": str(current_message.get("model") or selected_model),
        },
    )
    return await _set_ai_assistant_job(
        job_id,
        {
            "conversation_id": conversation_id,
            "assistant_message_id": assistant_message_id,
            "status": "stopped",
            "stage": "stopped",
            "progress_message": progress_message,
            "error": "",
            "provider": provider_key,
            "provider_config_id": str(provider_config_id or ""),
            "prompt_plugin_id": str(prompt_plugin_id or ""),
            "prompt_plugin_name": str(prompt_plugin_name or ""),
            "model": selected_model,
        },
    )


def _format_local_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _parse_log_line(line: str) -> dict[str, Any] | None:
    match = LOG_LINE_PATTERN.match(line)
    if not match:
        return None
    groups = match.groupdict()
    try:
        groups["parsed_timestamp"] = datetime.strptime(groups["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None
    return groups


def _build_log_entries(lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        parsed_line = _parse_log_line(line)
        entries.append(
            {
                "line_number": line_number,
                "raw": line,
                "parsed": parsed_line is not None,
                "timestamp": parsed_line["timestamp"] if parsed_line is not None else "",
                "level": parsed_line["level"] if parsed_line is not None else "",
                "module": parsed_line["module"] if parsed_line is not None else "",
                "function": parsed_line["function"] if parsed_line is not None else "",
                "source_line": int(parsed_line["line"]) if parsed_line is not None else None,
                "message": parsed_line["message"] if parsed_line is not None else line,
                "_parsed_timestamp": parsed_line["parsed_timestamp"] if parsed_line is not None else None,
            }
        )
    return entries


def _filter_log_entries(
    entries: list[dict[str, Any]],
    time_range: str,
    level: str,
    module_query: str,
    keyword: str,
) -> list[dict[str, Any]]:
    normalized_time_range = (time_range or "all").strip().lower()
    normalized_level = (level or "").strip().upper()
    normalized_module_query = (module_query or "").strip().lower()
    normalized_keyword = (keyword or "").strip().lower()
    cutoff_time = None
    if normalized_time_range in LOG_TIME_RANGE_TO_DELTA:
        cutoff_time = datetime.now() - LOG_TIME_RANGE_TO_DELTA[normalized_time_range]

    filtered_entries: list[dict[str, Any]] = []
    for entry in entries:
        parsed_timestamp = entry.get("_parsed_timestamp")
        if cutoff_time is not None:
            if parsed_timestamp is None or parsed_timestamp < cutoff_time:
                continue
        if normalized_level:
            if str(entry.get("level") or "").upper() != normalized_level:
                continue
        if normalized_module_query:
            searchable_target = " ".join(
                filter(
                    None,
                    [
                        str(entry.get("module") or ""),
                        str(entry.get("function") or ""),
                        str(entry.get("raw") or "") if not entry.get("parsed") else "",
                    ],
                )
            )
            if normalized_module_query not in searchable_target.lower():
                continue
        if normalized_keyword:
            searchable_message = " ".join(
                filter(
                    None,
                    [
                        str(entry.get("message") or ""),
                        str(entry.get("raw") or ""),
                        str(entry.get("module") or ""),
                        str(entry.get("function") or ""),
                    ],
                )
            )
            if normalized_keyword not in searchable_message.lower():
                continue
        filtered_entries.append(entry)
    return filtered_entries


def _sanitize_upload_path_segment(value: str | PathLike[str] | None, fallback: str = "file") -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._")
    return sanitized or fallback


def _resolve_project_relative_dir(value: str | None, default: str = "uploads") -> Path:
    raw_value = str(value or default).strip().replace("\\", "/").strip("/")
    relative_dir = Path(raw_value or default)
    if relative_dir.is_absolute() or any(part == ".." for part in relative_dir.parts):
        raise ValueError("上传目录必须是项目根目录下的相对路径")
    resolved_dir = (PROJECT_ROOT / relative_dir).resolve()
    project_root = PROJECT_ROOT.resolve()
    if resolved_dir != project_root and project_root not in resolved_dir.parents:
        raise ValueError("上传目录超出项目根目录范围")
    return resolved_dir


@dataclass(slots=True)
class ContactProfile:
    wxid: str
    display_name: str
    avatar_url: str
    nickname: str = ""


@dataclass(slots=True)
class RoomMemberProfile:
    wxid: str
    display_name: str
    avatar_url: str
    nick_name: str = ""
    room_nick_name: str = ""


CONTACT_MISS_CACHE_TTL_SECONDS = 30.0
CONTACT_REFRESH_COOLDOWN_SECONDS = 3.0


class ContactDirectoryCache:
    def __init__(self, api_client: WxRobotApiClient):
        self.api_client = api_client
        self._contacts: dict[int, dict[str, ContactProfile]] = {}
        self._contact_miss_cache: dict[int, dict[str, float]] = {}
        self._contact_refresh_attempted_at: dict[int, float] = {}
        self._room_members: dict[tuple[int, str], dict[str, RoomMemberProfile]] = {}
        self._contact_locks: dict[int, asyncio.Lock] = {}
        self._room_member_locks: dict[tuple[int, str], asyncio.Lock] = {}

    @staticmethod
    def _pid_key(wxpid: int | None) -> int:
        return -1 if wxpid in (None, "") else int(wxpid)

    def _get_contact_lock(self, wxpid: int | None) -> asyncio.Lock:
        key = self._pid_key(wxpid)
        lock = self._contact_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._contact_locks[key] = lock
        return lock

    def _clear_contact_miss_cache(self, wxpid: int | None) -> None:
        self._contact_miss_cache.pop(self._pid_key(wxpid), None)

    def _remember_contact_miss(self, wxid: str, wxpid: int | None) -> None:
        normalized_wxid = str(wxid or "").strip()
        if not normalized_wxid:
            return
        pid_key = self._pid_key(wxpid)
        miss_cache = self._contact_miss_cache.get(pid_key)
        if miss_cache is None:
            miss_cache = {}
            self._contact_miss_cache[pid_key] = miss_cache
        miss_cache[normalized_wxid] = monotonic() + CONTACT_MISS_CACHE_TTL_SECONDS

    def _is_contact_miss_cached(self, wxid: str, wxpid: int | None) -> bool:
        normalized_wxid = str(wxid or "").strip()
        if not normalized_wxid:
            return False
        pid_key = self._pid_key(wxpid)
        miss_cache = self._contact_miss_cache.get(pid_key)
        if not miss_cache:
            return False
        expires_at = miss_cache.get(normalized_wxid)
        if expires_at is None:
            return False
        if expires_at <= monotonic():
            miss_cache.pop(normalized_wxid, None)
            if not miss_cache:
                self._contact_miss_cache.pop(pid_key, None)
            return False
        return True

    def _get_room_member_lock(self, roomid: str, wxpid: int | None) -> asyncio.Lock:
        key = (self._pid_key(wxpid), roomid)
        lock = self._room_member_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._room_member_locks[key] = lock
        return lock

    @staticmethod
    def _build_contact_profile(item: dict[str, Any]) -> ContactProfile | None:
        wxid = str(item.get("wxid") or "").strip()
        if not wxid:
            return None
        nickname = str(item.get("nickname") or "").strip()
        remarks = str(item.get("remarks") or "").strip()
        display_name = nickname or remarks or wxid
        avatar_url = str(item.get("small_head_url") or item.get("big_head_url") or "").strip()
        return ContactProfile(wxid=wxid, display_name=display_name, avatar_url=avatar_url, nickname=nickname)

    @staticmethod
    def _build_room_member_profile(item: dict[str, Any]) -> RoomMemberProfile | None:
        wxid = str(item.get("username") or item.get("wxid") or "").strip()
        if not wxid:
            return None
        nick_name = str(item.get("nick_name") or "").strip()
        room_nick_name = str(item.get("room_nick_name") or "").strip()
        display_name = room_nick_name or nick_name or wxid
        avatar_url = str(item.get("small_head_url") or item.get("big_head_url") or "").strip()
        return RoomMemberProfile(
            wxid=wxid,
            display_name=display_name,
            avatar_url=avatar_url,
            nick_name=nick_name,
            room_nick_name=room_nick_name,
        )

    @staticmethod
    def _coerce_message_type(value: Any) -> int | None:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(stripped, 16) if stripped.lower().startswith("0x") else int(stripped)
            except ValueError:
                return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    async def warmup(self) -> None:
        wxpids: set[int | None] = {None}
        try:
            users = await self.api_client.get_logged_in_users()
        except Exception as exc:
            logger.warning("获取已登录微信账号列表失败，使用默认账号预热联系人缓存: {}", exc)
            users = []

        for item in users or []:
            wxpid = item.get("wxpid")
            if wxpid not in (None, ""):
                wxpids.add(int(wxpid))

        await asyncio.gather(*(self.refresh_contacts(wxpid) for wxpid in wxpids), return_exceptions=True)

    async def refresh_contacts(self, wxpid: int | None) -> dict[str, ContactProfile]:
        lock = self._get_contact_lock(wxpid)
        pid_key = self._pid_key(wxpid)
        async with lock:
            last_attempted_at = self._contact_refresh_attempted_at.get(pid_key)
            if last_attempted_at is not None and (monotonic() - last_attempted_at) < CONTACT_REFRESH_COOLDOWN_SECONDS:
                return self._contacts.get(pid_key, {})
            try:
                user_list, room_list, biz_list = await asyncio.gather(
                    self.api_client.get_user_list(wxpid),
                    self.api_client.get_room_list(wxpid),
                    self.api_client.get_biz_list(wxpid),
                )
            except Exception as exc:
                self._contact_refresh_attempted_at[pid_key] = monotonic()
                logger.warning("刷新联系人缓存失败(wxpid={}): {}", wxpid, exc)
                return self._contacts.get(pid_key, {})

            profiles: dict[str, ContactProfile] = {}
            for payload in (user_list, room_list, biz_list):
                for item in payload or []:
                    profile = self._build_contact_profile(item)
                    if profile is not None:
                        profiles[profile.wxid] = profile

            # Cache empty results as well so repeated message enrichment does not
            # fan out into the same contact refresh storm on every lookup.
            self._contacts[pid_key] = profiles
            self._clear_contact_miss_cache(wxpid)
            self._contact_refresh_attempted_at[pid_key] = monotonic()
            return self._contacts.get(pid_key, {})

    async def get_contact(self, wxid: str, wxpid: int | None) -> ContactProfile | None:
        normalized_wxid = str(wxid or "").strip()
        if not normalized_wxid:
            return None
        pid_keys = [self._pid_key(wxpid)]
        if wxpid not in (None, ""):
            pid_keys.append(self._pid_key(None))

        for pid_key in pid_keys:
            profile = self._contacts.get(pid_key, {}).get(normalized_wxid)
            if profile is not None:
                return profile

        if self._is_contact_miss_cached(normalized_wxid, wxpid):
            return None

        await self.refresh_contacts(wxpid)
        for pid_key in pid_keys:
            profile = self._contacts.get(pid_key, {}).get(normalized_wxid)
            if profile is not None:
                return profile

        self._remember_contact_miss(normalized_wxid, wxpid)
        return None

    async def refresh_room_members(self, roomid: str, wxpid: int | None) -> dict[str, RoomMemberProfile]:
        lock = self._get_room_member_lock(roomid, wxpid)
        cache_key = (self._pid_key(wxpid), roomid)
        async with lock:
            cached_profiles = self._room_members.get(cache_key)
            if cached_profiles is not None:
                return cached_profiles
            try:
                members = await self.api_client.get_room_members(roomid, wxpid)
            except Exception as exc:
                logger.warning("刷新群成员缓存失败(roomid={}, wxpid={}): {}", roomid, wxpid, exc)
                return self._room_members.get(cache_key, {})

            profiles: dict[str, RoomMemberProfile] = {}
            for item in members or []:
                profile = self._build_room_member_profile(item)
                if profile is not None:
                    profiles[profile.wxid] = profile

            # Mirror contact-cache behavior: even an empty member list should
            # suppress repeated refreshes until a later explicit invalidation.
            self._room_members[cache_key] = profiles
            return self._room_members.get(cache_key, {})

    async def get_room_member(self, roomid: str, wxid: str, wxpid: int | None) -> RoomMemberProfile | None:
        if not roomid or not wxid:
            return None
        cache_key = (self._pid_key(wxpid), roomid)
        cached_profiles = self._room_members.get(cache_key)
        if cached_profiles is not None:
            return cached_profiles.get(wxid)

        await self.refresh_room_members(roomid, wxpid)
        return self._room_members.get(cache_key, {}).get(wxid)

    async def enrich_message(self, message: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(message)
        wxpid = enriched.get("wxpid")
        conversation_wxid = str(enriched.get("conversation_wxid") or "").strip()
        sender_wxid = str(enriched.get("sender_wxid") or "").strip()
        is_group_message = bool(enriched.get("is_group_message"))

        conversation_profile = await self.get_contact(conversation_wxid, wxpid) if conversation_wxid else None
        sender_profile = None if is_group_message else (await self.get_contact(sender_wxid, wxpid) if sender_wxid else None)
        room_member_profile = (
            await self.get_room_member(conversation_wxid, sender_wxid, wxpid)
            if is_group_message and conversation_wxid and sender_wxid
            else None
        )

        conversation_display_name = (
            conversation_profile.display_name if conversation_profile is not None else conversation_wxid or "未知会话"
        )
        sender_display_name = sender_profile.display_name if sender_profile is not None else sender_wxid or "未知发送者"
        room_sender_display_name = (
            room_member_profile.display_name if room_member_profile is not None else sender_wxid or "未知发送者"
        )
        avatar_url = ""
        if is_group_message:
            avatar_url = conversation_profile.avatar_url if conversation_profile is not None else ""
        else:
            avatar_url = (
                sender_profile.avatar_url
                if sender_profile is not None
                else conversation_profile.avatar_url if conversation_profile is not None else ""
            )

        text_content = ""
        message_type_code = self._coerce_message_type(enriched.get("local_type") or enriched.get("msg_type"))
        if message_type_code == 1:
            text_content = str(
                enriched.get("content")
                or (enriched.get("payload") or {}).get("message_content")
                or (enriched.get("payload") or {}).get("content")
                or ""
            )
            for candidate in (
                sender_wxid,
                conversation_wxid,
                str((enriched.get("payload") or {}).get("room_sender") or ""),
                str((enriched.get("payload") or {}).get("sender") or ""),
            ):
                if candidate and text_content.startswith(f"{candidate}:"):
                    text_content = text_content[len(candidate) + 1 :].lstrip()
                    break

        enriched.update(
            {
                "conversation_display_name": conversation_display_name,
                "sender_display_name": sender_display_name,
                "room_sender_display_name": room_sender_display_name,
                "avatar_url": avatar_url,
                "conversation_avatar_url": conversation_profile.avatar_url if conversation_profile is not None else "",
                "sender_avatar_url": sender_profile.avatar_url if sender_profile is not None else "",
                "room_sender_avatar_url": room_member_profile.avatar_url if room_member_profile is not None else "",
                "title_display": conversation_display_name if is_group_message else (sender_display_name or conversation_display_name),
                "text_content": text_content,
            }
        )
        return enriched


class PluginRuntime:
    def __init__(self, settings: PluginServiceSettings):
        self.settings = settings
        self.api_client = WxRobotApiClient(settings.wxrobot_api_base_url, settings.request_timeout)
        self.directory_cache = ContactDirectoryCache(self.api_client)
        self.context = PluginContext(
            settings=settings,
            api_client=self.api_client,
            login_account_cache_getter=self.get_cached_login_accounts,
            login_account_cache_refresher=self.refresh_login_account_cache,
            login_account_serializer=self._serialize_login_accounts,
        )
        self.manager = PluginManager(
            self.context,
            settings.plugins,
            settings.plugin_settings,
            plugin_log_sink=self._remember_plugin_log,
        )
        self.queue: asyncio.Queue[tuple[int, MessageEvent] | None] = asyncio.Queue(maxsize=settings.queue_size)
        self._workers: list[asyncio.Task] = []
        self._message_sequence = count(1)
        self._plugin_log_sequence = count(1)
        self.recent_messages: deque[dict[str, Any]] = deque(maxlen=RECENT_MESSAGE_LIMIT)
        self.recent_plugin_logs: deque[dict[str, Any]] = deque(maxlen=PLUGIN_LOG_LIMIT)
        self.started_at: datetime | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._manual_plugin_execution_lock = asyncio.Lock()
        self._manual_plugin_executions: dict[str, dict[str, Any]] = {}
        self._manual_plugin_execution_tasks: dict[str, asyncio.Task[Any]] = {}
        self.heartbeat_accounts: list[dict[str, Any]] = []
        self.heartbeat_last_checked_at: datetime | None = None
        self.heartbeat_error = ""
        self.heartbeat_healthy: bool | None = None

    @staticmethod
    def _serialize_login_accounts(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
        accounts: list[dict[str, Any]] = []
        for item in users or []:
            wxid = str(item.get("wxid") or "").strip()
            wxh = str(item.get("wxh") or item.get("alias") or "").strip()
            nickname = str(item.get("nickname") or "").strip()
            wxpid = item.get("wxpid")
            if wxpid in (None, ""):
                wxpid = item.get("pid")
            display_name = nickname or wxh or wxid or "未命名账号"
            accounts.append(
                {
                    "display_name": display_name,
                    "nickname": nickname,
                    "wxid": wxid,
                    "wxh": wxh,
                    "wxpid": wxpid,
                }
            )
        return accounts

    def _clear_heartbeat_state(self) -> None:
        self.heartbeat_accounts = []
        self.heartbeat_last_checked_at = None
        self.heartbeat_error = ""
        self.heartbeat_healthy = None

    def get_cached_login_accounts(self) -> list[dict[str, Any]]:
        return list(self.heartbeat_accounts)

    def _normalize_manual_plugin_execution_payload(self, module_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        current = deepcopy(payload if isinstance(payload, dict) else self._manual_plugin_executions.get(normalized_module_name, {}))
        status = str(current.get("status") or "idle").strip().lower()
        valid_statuses = {"idle", *MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES, *MANUAL_PLUGIN_EXECUTION_TERMINAL_STATUSES}
        if status not in valid_statuses:
            status = "idle"
        if status == "idle":
            return {
                "module": normalized_module_name,
                "status": "idle",
                "active": False,
                "detail": "",
                "error": "",
                "started_at": "",
                "updated_at": "",
                "result": None,
            }
        return {
            "module": normalized_module_name,
            "status": status,
            "active": status in MANUAL_PLUGIN_EXECUTION_ACTIVE_STATUSES,
            "detail": str(current.get("detail") or "").strip(),
            "error": str(current.get("error") or "").strip(),
            "started_at": str(current.get("started_at") or "").strip(),
            "updated_at": str(current.get("updated_at") or "").strip(),
            "result": deepcopy(current.get("result")) if isinstance(current.get("result"), dict) else current.get("result"),
        }

    async def _set_manual_plugin_execution(self, module_name: str, updates: dict[str, Any]) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            current = deepcopy(self._manual_plugin_executions.get(normalized_module_name, {}))
            next_payload = {
                **current,
                **deepcopy(updates),
                "module": normalized_module_name,
                "updated_at": _now_iso(),
            }
            if not str(next_payload.get("started_at") or "").strip() and str(next_payload.get("status") or "").strip().lower() != "idle":
                next_payload["started_at"] = _now_iso()
            normalized_payload = self._normalize_manual_plugin_execution_payload(normalized_module_name, next_payload)
            self._manual_plugin_executions[normalized_module_name] = normalized_payload
            return deepcopy(normalized_payload)

    async def _set_manual_plugin_execution_task(self, module_name: str, task: asyncio.Task[Any]) -> None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            self._manual_plugin_execution_tasks[normalized_module_name] = task

    async def _get_manual_plugin_execution_task(self, module_name: str) -> asyncio.Task[Any] | None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            return self._manual_plugin_execution_tasks.get(normalized_module_name)

    async def _pop_manual_plugin_execution_task(self, module_name: str) -> asyncio.Task[Any] | None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            return self._manual_plugin_execution_tasks.pop(normalized_module_name, None)

    async def get_manual_plugin_execution(self, module_name: str) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        async with self._manual_plugin_execution_lock:
            payload = deepcopy(self._manual_plugin_executions.get(normalized_module_name, {}))
        return self._normalize_manual_plugin_execution_payload(normalized_module_name, payload)

    def get_manual_plugin_execution_snapshot(self, module_name: str) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        return self._normalize_manual_plugin_execution_payload(
            normalized_module_name,
            deepcopy(self._manual_plugin_executions.get(normalized_module_name, {})),
        )

    async def _run_manual_plugin_execution(self, module_name: str, config_override: dict[str, Any] | None = None) -> None:
        normalized_module_name = normalize_plugin_module_name(module_name)
        await self._set_manual_plugin_execution(
            normalized_module_name,
            {
                "status": "running",
                "detail": "插件正在执行...",
                "error": "",
                "result": None,
            },
        )
        try:
            result = await self.manager.execute_plugin(normalized_module_name, dict(config_override or {}))
        except asyncio.CancelledError:
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "stopped",
                    "detail": "插件已停止",
                    "error": "",
                    "result": None,
                },
            )
            raise
        except ValueError as exc:
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "failed",
                    "detail": str(exc),
                    "error": str(exc),
                    "result": None,
                },
            )
        except Exception as exc:
            logger.exception("手动执行插件失败: {}", normalized_module_name)
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "failed",
                    "detail": f"执行插件失败: {exc}",
                    "error": str(exc),
                    "result": None,
                },
            )
        else:
            await self._set_manual_plugin_execution(
                normalized_module_name,
                {
                    "status": "completed",
                    "detail": str(result.get("detail") or "").strip() or "执行完成",
                    "error": "",
                    "result": result,
                },
            )
        finally:
            await self._pop_manual_plugin_execution_task(normalized_module_name)

    async def start_manual_plugin_execution(self, module_name: str, config_override: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        current = await self.get_manual_plugin_execution(normalized_module_name)
        if current.get("active"):
            raise ValueError("插件正在执行中")

        await self._set_manual_plugin_execution(
            normalized_module_name,
            {
                "status": "queued",
                "detail": "插件已开始执行",
                "error": "",
                "result": None,
            },
        )
        task = asyncio.create_task(
            self._run_manual_plugin_execution(normalized_module_name, dict(config_override or {})),
            name=f"manual-plugin-{normalized_module_name.rsplit('.', 1)[-1]}",
        )
        await self._set_manual_plugin_execution_task(normalized_module_name, task)
        return await self.get_manual_plugin_execution(normalized_module_name)

    async def stop_manual_plugin_execution(self, module_name: str) -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        current = await self.get_manual_plugin_execution(normalized_module_name)
        if not current.get("active"):
            raise ValueError("当前没有正在执行的插件")
        task = await self._get_manual_plugin_execution_task(normalized_module_name)
        if task is None:
            raise ValueError("当前没有正在执行的插件")

        await self._set_manual_plugin_execution(
            normalized_module_name,
            {
                "status": "stopping",
                "detail": "正在停止插件...",
                "error": "",
            },
        )
        task.cancel()
        return await self.get_manual_plugin_execution(normalized_module_name)

    async def _cancel_manual_plugin_executions(self) -> None:
        async with self._manual_plugin_execution_lock:
            tasks = list(self._manual_plugin_execution_tasks.items())
        for module_name, task in tasks:
            if task.done():
                continue
            await self._set_manual_plugin_execution(
                module_name,
                {
                    "status": "stopping",
                    "detail": "正在停止插件...",
                    "error": "",
                },
            )
            task.cancel()
        if tasks:
            await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)

    async def refresh_login_account_cache(self, users: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        self.heartbeat_last_checked_at = datetime.now().astimezone()
        login_users = users if isinstance(users, list) else None
        try:
            if login_users is None:
                login_users = await self.api_client.get_logged_in_users()
        except Exception as exc:
            self.heartbeat_error = str(exc)
            self.heartbeat_healthy = False
            return list(self.heartbeat_accounts)

        self.heartbeat_accounts = self._serialize_login_accounts(login_users if isinstance(login_users, list) else [])
        self.heartbeat_error = ""
        self.heartbeat_healthy = True
        return list(self.heartbeat_accounts)

    async def _run_heartbeat_check(self) -> None:
        await self.refresh_login_account_cache()

    async def _heartbeat_loop(self) -> None:
        while True:
            interval_seconds = max(0, int(getattr(self.settings, "heartbeat_interval_seconds", 0) or 0))
            if interval_seconds <= 0:
                self._clear_heartbeat_state()
                await asyncio.sleep(1)
                continue

            await self._run_heartbeat_check()
            await asyncio.sleep(interval_seconds)

    async def start(self) -> None:
        if self.started_at is None:
            self.started_at = datetime.now().astimezone()
        await self.manager.load_plugins()
        await self.directory_cache.warmup()
        if self.settings.heartbeat_interval_seconds > 0:
            await self._run_heartbeat_check()
        else:
            self._clear_heartbeat_state()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="plugin-heartbeat")
        self._workers = [
            asyncio.create_task(self._worker(index), name=f"plugin-worker-{index}")
            for index in range(self.settings.worker_count)
        ]
        logger.info("插件服务已启动，消息回调地址: {}", self.settings.callback_url)

    async def reload(self, settings: PluginServiceSettings | None = None) -> None:
        await self._cancel_manual_plugin_executions()
        next_settings = settings or PluginServiceSettings.from_storage()
        next_api_client = WxRobotApiClient(next_settings.wxrobot_api_base_url, next_settings.request_timeout)
        next_directory_cache = ContactDirectoryCache(next_api_client)
        next_context = PluginContext(
            settings=next_settings,
            api_client=next_api_client,
            login_account_cache_getter=self.get_cached_login_accounts,
            login_account_cache_refresher=self.refresh_login_account_cache,
            login_account_serializer=self._serialize_login_accounts,
        )
        next_manager = PluginManager(
            next_context,
            next_settings.plugins,
            next_settings.plugin_settings,
            plugin_log_sink=self._remember_plugin_log,
        )
        await next_manager.load_plugins()
        await next_directory_cache.warmup()

        old_manager = self.manager
        self.settings = next_settings
        self.api_client = next_api_client
        self.directory_cache = next_directory_cache
        self.context = next_context
        self.manager = next_manager
        await old_manager.shutdown()
        logger.info("插件配置已重载，当前启用插件: {}", [plugin.name for plugin in self.manager.plugins])

    async def stop(self) -> None:
        await self._cancel_manual_plugin_executions()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
            self._heartbeat_task = None
        for _ in self._workers:
            await self.queue.put(None)
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        await self.manager.shutdown()

    async def enqueue(self, event: MessageEvent) -> int:
        internal_id = self._remember_message(event)
        try:
            self.queue.put_nowait((internal_id, event))
        except asyncio.QueueFull as exc:
            self._patch_message(
                internal_id,
                status="rejected",
                processed_at=self._now_iso(),
                error="插件消息队列已满",
            )
            raise HTTPException(status_code=503, detail="插件消息队列已满") from exc
        return internal_id

    def _remember_message(self, event: MessageEvent) -> int:
        internal_id = next(self._message_sequence)
        self.recent_messages.appendleft(
            {
                "internal_id": internal_id,
                "received_at": self._now_iso(),
                "processed_at": None,
                "status": "queued",
                "error": "",
                "msgid": event.normalized_msgid,
                "conversation_wxid": event.conversation_wxid,
                "sender_wxid": event.sender_wxid,
                "msg_type": event.normalized_msg_type,
                "local_type": event.normalized_local_type,
                "wxpid": event.normalized_wxpid,
                "is_group_message": event.is_group_message,
                "content": event.normalized_content,
                "plugin_results": [],
                "payload": event.raw_payload,
            }
        )
        return internal_id

    def _patch_message(self, internal_id: int, **updates: Any) -> None:
        for item in self.recent_messages:
            if item["internal_id"] == internal_id:
                item.update(updates)
                return

    def _now_iso(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _remember_plugin_log(self, entry: dict[str, Any]) -> None:
        self.recent_plugin_logs.appendleft(
            {
                "internal_id": next(self._plugin_log_sequence),
                "recorded_at": self._now_iso(),
                "module": str(entry.get("module") or ""),
                "plugin": str(entry.get("plugin") or entry.get("module") or ""),
                "level": str(entry.get("level") or "INFO"),
                "scope": str(entry.get("scope") or ""),
                "message": str(entry.get("message") or ""),
                "data": entry.get("data"),
            }
        )

    def get_plugin_logs(self, limit: int, module_name: str | None = None, level: str | None = None, keyword: str | None = None) -> tuple[list[dict[str, Any]], int]:
        normalized_level = str(level or "").strip().upper()
        normalized_keyword = str(keyword or "").strip().casefold()
        filtered_logs = [
            dict(item)
            for item in self.recent_plugin_logs
            if (not module_name or item["module"] == module_name)
            and (not normalized_level or str(item.get("level") or "").upper() == normalized_level)
            and (
                not normalized_keyword
                or normalized_keyword in "\n".join(
                    part
                    for part in [
                        str(item.get("module") or ""),
                        str(item.get("plugin") or ""),
                        str(item.get("scope") or ""),
                        str(item.get("message") or ""),
                        json.dumps(item.get("data"), ensure_ascii=False, sort_keys=True, default=str) if item.get("data") is not None else "",
                    ]
                    if part
                ).casefold()
            )
        ]
        return filtered_logs[:limit], len(filtered_logs)

    async def get_message_views(self, limit: int) -> list[dict[str, Any]]:
        messages = [dict(item) for item in list(self.recent_messages)[:limit]]
        if not messages:
            return []
        return await asyncio.gather(*(self.directory_cache.enrich_message(item) for item in messages))

    async def _worker(self, index: int) -> None:
        while True:
            queued_item = await self.queue.get()
            try:
                if queued_item is None:
                    return

                internal_id, event = queued_item
                results = await self.manager.dispatch(event)
                self._patch_message(
                    internal_id,
                    status="processed",
                    processed_at=self._now_iso(),
                    plugin_results=results,
                )
                if results:
                    logger.debug(
                        "worker={} msgid={} plugins={}",
                        index,
                        event.normalized_msgid,
                        results,
                    )
            except Exception as exc:
                if queued_item is not None:
                    self._patch_message(
                        queued_item[0],
                        status="failed",
                        processed_at=self._now_iso(),
                        error=str(exc),
                    )
                logger.exception("插件 worker 处理消息失败")
            finally:
                self.queue.task_done()


def create_app(settings: PluginServiceSettings | None = None) -> FastAPI:
    settings = settings or PluginServiceSettings.from_storage()
    removed_plugin_modules = REMOVED_PLUGIN_MODULES
    sanitized_plugins = [module_name for module_name in settings.plugins if module_name not in removed_plugin_modules]
    sanitized_plugin_settings = {
        key: value
        for key, value in settings.plugin_settings.items()
        if key not in removed_plugin_modules
    }
    if sanitized_plugins != settings.plugins or sanitized_plugin_settings != settings.plugin_settings:
        settings = settings.model_copy(
            update={
                "plugins": sanitized_plugins,
                "plugin_settings": sanitized_plugin_settings,
            }
        )
        settings.save_to_storage()
    runtime = PluginRuntime(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.plugin_runtime = runtime
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(
        title="wxrobot_api webui plugin server",
        description="接收微信消息推送并分发给 webui 插件处理",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def normalize_wxpid(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def sort_option_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(items, key=lambda item: (str(item.get("label") or "").lower(), str(item.get("value") or "").lower()))

    def normalize_plugin_config_for_payload(module_name: str, config: Any) -> Any:
        normalized_module_name = normalize_plugin_module_name(module_name)
        if normalized_module_name == DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE and isinstance(config, dict):
            normalized_config = {
                key: value
                for key, value in config.items()
                if key not in {"db_name", "wait", "timeout"}
            }
            if not str(normalized_config.get("start_time") or "").strip():
                normalized_config["start_time"] = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            return normalized_config

        if normalized_module_name == ENTER_ROOM_TIP_PLUGIN_MODULE and isinstance(config, dict):
            normalized_rows: list[dict[str, Any]] = []
            raw_rows = config.get("room_welcomes")

            def normalize_image_path(value: Any) -> str:
                return str(value or "").strip().replace("\\", "/")

            def append_room_welcome(roomid: Any, content: Any = "", path: Any = "") -> None:
                normalized_roomid = str(roomid or "").strip()
                normalized_content = str(content or "").strip()
                normalized_path = normalize_image_path(path)
                if not normalized_roomid or (not normalized_content and not normalized_path):
                    return
                row = {
                    "roomid": normalized_roomid,
                    "content": normalized_content,
                    "path": normalized_path,
                }
                existing_index = next((index for index, item in enumerate(normalized_rows) if item.get("roomid") == normalized_roomid), -1)
                if existing_index >= 0:
                    normalized_rows[existing_index] = row
                else:
                    normalized_rows.append(row)

            if isinstance(raw_rows, list):
                for item in raw_rows:
                    if not isinstance(item, dict):
                        continue
                    append_room_welcome(
                        item.get("roomid") or item.get("wxid"),
                        item.get("content") or item.get("text"),
                        item.get("path") or item.get("image_path") or item.get("image"),
                    )
            else:
                legacy_rows = raw_rows if isinstance(raw_rows, dict) else config.get("welcome_file")
                if isinstance(legacy_rows, dict):
                    for roomid, items in legacy_rows.items():
                        if isinstance(items, dict):
                            append_room_welcome(roomid, items.get("content") or items.get("text"), items.get("path") or items.get("image_path") or items.get("image"))
                            continue
                        if isinstance(items, str):
                            append_room_welcome(roomid, items, "")
                            continue
                        if not isinstance(items, list):
                            continue
                        text_segments: list[str] = []
                        image_path = ""
                        for item in items:
                            if isinstance(item, str):
                                text_segments.append(str(item).strip())
                                continue
                            if not isinstance(item, dict):
                                continue
                            content = str(item.get("content") or item.get("text") or "").strip()
                            path = normalize_image_path(item.get("path") or item.get("image_path") or item.get("image"))
                            if content:
                                text_segments.append(content)
                            if path and not image_path:
                                image_path = path
                        append_room_welcome(roomid, "\n".join(segment for segment in text_segments if segment).strip(), image_path)

            if normalized_rows:
                return {
                    **config,
                    "room_welcomes": normalized_rows,
                }
            return config

        if normalized_module_name == ROOM_AI_REPLY_PLUGIN_MODULE and isinstance(config, dict):
            normalized_rows: list[dict[str, Any]] = []

            def append_room_config(roomid: Any, base_url: Any = "", api_key: Any = "", model: Any = "", system_prompt: Any = "") -> None:
                normalized_roomid = str(roomid or "").strip()
                if not normalized_roomid:
                    return
                row = {
                    "roomid": normalized_roomid,
                    "base_url": str(base_url or "").strip(),
                    "api_key": str(api_key or "").strip(),
                    "model": str(model or "").strip(),
                    "system_prompt": str(system_prompt or "").strip(),
                }
                existing_index = next((index for index, item in enumerate(normalized_rows) if item.get("roomid") == normalized_roomid), -1)
                if existing_index >= 0:
                    normalized_rows[existing_index] = row
                else:
                    normalized_rows.append(row)

            raw_rows = config.get("room_configs")
            if isinstance(raw_rows, list):
                for item in raw_rows:
                    if not isinstance(item, dict):
                        continue
                    append_room_config(
                        item.get("roomid") or item.get("wxid"),
                        item.get("base_url"),
                        item.get("api_key"),
                        item.get("model"),
                        item.get("system_prompt") or item.get("prompt"),
                    )

            if not normalized_rows:
                append_room_config(
                    config.get("roomid") or config.get("wxid"),
                    config.get("base_url"),
                    config.get("api_key"),
                    config.get("model"),
                    config.get("system_prompt") or config.get("prompt"),
                )

            if normalized_rows:
                return {
                    **config,
                    "room_configs": normalized_rows,
                }
            return config

        if normalized_module_name != INVITE_TO_ROOM_PLUGIN_MODULE or not isinstance(config, dict):
            return config

        normalized_rules: list[dict[str, Any]] = []
        seen_rules: set[tuple[str, str, bool]] = set()

        def normalize_rule_full_match(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y", "是"}

        def append_rule(roomid: Any, keyword: Any, full_match: Any = False) -> None:
            normalized_roomid = str(roomid or "").strip()
            normalized_keyword = str(keyword or "").strip()
            normalized_full_match = normalize_rule_full_match(full_match)
            rule_key = (normalized_roomid, normalized_keyword, normalized_full_match)
            if not normalized_roomid or not normalized_keyword or rule_key in seen_rules:
                return
            seen_rules.add(rule_key)
            normalized_rules.append(
                {
                    "roomid": normalized_roomid,
                    "keyword": normalized_keyword,
                    "full_match": normalized_full_match,
                }
            )

        raw_rules = config.get("keyword_rooms")
        if isinstance(raw_rules, list):
            for item in raw_rules:
                if not isinstance(item, dict):
                    continue
                append_rule(item.get("roomid"), item.get("keyword"), item.get("full_match"))
        elif isinstance(raw_rules, dict):
            for keyword, roomid in raw_rules.items():
                append_rule(roomid, keyword, False)

        legacy_keywords = config.get("keywords")
        if isinstance(legacy_keywords, dict):
            for roomid, keyword_values in legacy_keywords.items():
                for keyword in [str(item or "").strip() for item in str(keyword_values or "").replace("，", ",").replace("\n", ",").split(",") if str(item or "").strip()]:
                    append_rule(roomid, keyword, False)

        if not normalized_rules and not isinstance(raw_rules, list):
            return config

        return {
            **config,
            "keyword_rooms": normalized_rules,
        }

    def build_plugin_payload() -> list[dict]:
        module_names = list(dict.fromkeys(PluginManager.discover_plugin_modules() + runtime.settings.plugins))
        plugin_descriptions = PluginManager.describe_modules(module_names)
        loaded_plugins = {
            getattr(plugin, "module_name", plugin.__class__.__module__): plugin
            for plugin in runtime.manager.plugins
        }
        payload: list[dict] = []
        for item in plugin_descriptions:
            loaded_plugin = loaded_plugins.get(item["module"])
            config = runtime.settings.plugin_settings.get(item["module"], {})
            if not config and loaded_plugin is not None:
                config = loaded_plugin.config
            config = normalize_plugin_config_for_payload(item["module"], config)
            payload.append(
                {
                    **item,
                    "enabled": item["module"] in runtime.settings.plugins,
                    "loaded": loaded_plugin is not None,
                    "config": config,
                    "config_schema": item.get("config_schema") or [],
                    "scope_targets": item.get("scope_targets") or [],
                    "manual_execution": runtime.get_manual_plugin_execution_snapshot(item["module"]),
                }
            )
        return payload

    def resolve_plugin_model_options_field(module_name: str, field_key: str = "", parent_field_key: str = "") -> dict[str, Any]:
        normalized_module_name = normalize_plugin_module_name(module_name)
        if not normalized_module_name:
            raise HTTPException(status_code=400, detail="插件模块不能为空")

        available_modules = set(PluginManager.discover_plugin_modules()) | set(runtime.settings.plugins)
        if normalized_module_name not in available_modules:
            raise HTTPException(status_code=404, detail="未找到指定插件模块")

        metadata_list = PluginManager.describe_modules([normalized_module_name])
        metadata = metadata_list[0] if metadata_list else None
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=404, detail="未找到指定插件模块")
        if not metadata.get("loadable", True):
            raise HTTPException(status_code=400, detail=f"插件无法加载: {metadata.get('error') or '未知错误'}")

        normalized_field_key = str(field_key or "").strip().lower()
        normalized_parent_field_key = str(parent_field_key or "").strip().lower()
        config_schema = metadata.get("config_schema") if isinstance(metadata.get("config_schema"), list) else []

        def match_candidate(candidate_key: Any, candidate_parent_key: Any = "") -> bool:
            normalized_candidate_key = str(candidate_key or "").strip().lower()
            normalized_candidate_parent_key = str(candidate_parent_key or "").strip().lower()
            if normalized_field_key and normalized_candidate_key != normalized_field_key:
                return False
            if normalized_parent_field_key and normalized_candidate_parent_key != normalized_parent_field_key:
                return False
            return True

        model_field = None
        for field in config_schema:
            if not isinstance(field, dict):
                continue
            if str(field.get("options_source") or "").strip().lower() == "model_options" and match_candidate(field.get("key")):
                model_field = field
                break
            for column in field.get("columns") if isinstance(field.get("columns"), list) else []:
                if not isinstance(column, dict):
                    continue
                if str(column.get("options_source") or "").strip().lower() != "model_options":
                    continue
                if not match_candidate(column.get("key"), field.get("key")):
                    continue
                model_field = {
                    **column,
                    "__parent_field_key": field.get("key"),
                }
                break
            if isinstance(model_field, dict):
                break

        if not isinstance(model_field, dict):
            raise HTTPException(status_code=400, detail="当前插件未声明模型列表选项")
        return model_field

    async def build_plugin_target_payload() -> dict:
        users_payload = await runtime.api_client.get_logged_in_users()
        users = users_payload if isinstance(users_payload, list) else []
        wxpids: list[int] = []
        wxpid_options: list[dict[str, Any]] = []
        seen_wxpids: set[int] = set()
        for item in users:
            wxpid = normalize_wxpid(item.get("wxpid"))
            if wxpid is None or wxpid in seen_wxpids:
                continue
            seen_wxpids.add(wxpid)
            wxpids.append(wxpid)
            wxid = str(item.get("wxid") or "").strip()
            wxh = str(item.get("wxh") or item.get("alias") or "").strip()
            nickname = str(item.get("nickname") or item.get("remarks") or wxh or wxid or f"微信进程 {wxpid}").strip()
            search_parts = [nickname, wxh, wxid, str(wxpid)]
            wxpid_options.append(
                {
                    "label": f"{nickname}({wxpid})",
                    "search_text": " ".join(part for part in search_parts if part),
                    "value": wxpid,
                }
            )

        room_options: list[dict[str, Any]] = []
        label_options: list[dict[str, Any]] = []
        seen_rooms: set[str] = set()
        seen_labels: set[str] = set()
        for wxpid in wxpids:
            room_payload, label_payload = await asyncio.gather(
                runtime.api_client.get_room_list(wxpid=wxpid),
                runtime.api_client.get_labels(wxpid=wxpid),
                return_exceptions=True,
            )

            if not isinstance(room_payload, Exception) and isinstance(room_payload, list):
                for room in room_payload:
                    roomid = str(room.get("wxid") or room.get("roomid") or "").strip()
                    if not roomid or roomid in seen_rooms:
                        continue
                    room_name = str(room.get("nickname") or room.get("remarks") or "").strip()
                    if room_name == "":
                        continue
                    seen_rooms.add(roomid)
                    room_options.append(
                        {
                            "label": f"{room_name}({roomid})",
                            "search_text": room_name,
                            "value": roomid,
                            "wxpid": wxpid,
                        }
                    )

            if not isinstance(label_payload, Exception) and isinstance(label_payload, dict):
                for label_name in label_payload:
                    normalized_name = str(label_name or "").strip()
                    if not normalized_name or normalized_name in seen_labels:
                        continue
                    seen_labels.add(normalized_name)
                    label_options.append(
                        {
                            "label": normalized_name,
                            "search_text": normalized_name,
                            "value": normalized_name,
                        }
                    )

        return {
            "default_wxpid": wxpids[0] if wxpids else None,
            "wxpid_options": sort_option_items(wxpid_options),
            "room_options": sort_option_items(room_options),
            "label_options": sort_option_items(label_options),
        }

    def build_user_payload() -> dict:
        heartbeat_interval_seconds = max(0, int(getattr(runtime.settings, "heartbeat_interval_seconds", 0) or 0))
        return {
            "enabled": heartbeat_interval_seconds > 0,
            "interval_seconds": heartbeat_interval_seconds,
            "healthy": runtime.heartbeat_healthy,
            "last_checked_at": _format_local_datetime(runtime.heartbeat_last_checked_at),
            "total": len(runtime.heartbeat_accounts),
            "users": list(runtime.heartbeat_accounts),
            "error": runtime.heartbeat_error,
        }

    def build_overview() -> dict:
        settings_payload = build_settings_payload()
        uptime_seconds = int((datetime.now().astimezone() - runtime.started_at).total_seconds()) if runtime.started_at else 0
        user_payload = build_user_payload()
        return {
            "name": "wxrobot_api webui plugin server",
            "settings_storage_path": str(SETTINGS_DB_PATH),
            "callback_url": runtime.settings.callback_url,
            "wxrobot_api_base_url": runtime.settings.wxrobot_api_base_url,
            "listen_host": runtime.settings.host,
            "listen_port": runtime.settings.port,
            "plugins": [plugin.name for plugin in runtime.manager.plugins],
            "queue_size": runtime.settings.queue_size,
            "queued_messages": runtime.queue.qsize(),
            "worker_count": runtime.settings.worker_count,
            "enabled_plugin_count": len(runtime.settings.plugins),
            "loaded_plugin_count": len(runtime.manager.plugins),
            "pending_restart_fields": settings_payload["restart_required_fields"],
            "runtime_started_at": _format_local_datetime(runtime.started_at),
            "uptime_seconds": uptime_seconds,
            "heartbeat": {
                "enabled": user_payload["enabled"],
                "interval_seconds": user_payload["interval_seconds"],
                "healthy": user_payload["healthy"],
                "last_checked_at": user_payload["last_checked_at"],
                "account_count": user_payload["total"],
                "error": user_payload["error"],
            },
        }

    def serialize_system_settings(settings_obj: PluginServiceSettings) -> dict[str, Any]:
        payload = {field: getattr(settings_obj, field) for field in SYSTEM_SETTINGS_FIELDS if field != "wxrobot_api_base_url"}
        payload["api_base_url"] = settings_obj.wxrobot_api_base_url
        return payload

    def build_settings_payload() -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        runtime_payload = serialize_system_settings(runtime.settings)
        configured_payload = serialize_system_settings(configured_settings)
        restart_required_fields = [
            field
            for field in RESTART_REQUIRED_FIELDS
            if runtime_payload.get(field) != configured_payload.get(field)
        ]
        return {
            "runtime": runtime_payload,
            "config": configured_payload,
            "restart_required": bool(restart_required_fields),
            "restart_required_fields": restart_required_fields,
        }

    async def build_ai_assistant_settings_payload(settings: dict[str, Any] | None = None) -> dict:
        normalized_settings = normalize_ai_assistant_settings(
            settings
            if settings is not None
            else WebuiSettingsStore().get_json_setting(
                AI_ASSISTANT_SETTINGS_KEY,
                get_default_ai_assistant_settings(),
            )
        )
        return await build_ai_assistant_payload(normalized_settings)

    async def build_ai_assistant_page_payload(settings: dict[str, Any] | None = None) -> dict:
        settings_payload = await build_ai_assistant_settings_payload(settings)
        conversation_payload = await _ensure_ai_assistant_conversation_payload()
        return {
            **settings_payload,
            **conversation_payload,
        }

    async def run_ai_assistant_chat_job(
        job_id: str,
        conversation_id: str,
        assistant_message_id: str,
        provider_key: str,
        provider_config_id: str | None,
        prompt_plugin_id: str | None,
        prompt_plugin_name: str | None,
        selected_model: str,
    ) -> None:
        settings_payload = WebuiSettingsStore().get_json_setting(
            AI_ASSISTANT_SETTINGS_KEY,
            get_default_ai_assistant_settings(),
        )
        normalized_settings = normalize_ai_assistant_settings(settings_payload)

        async def handle_progress(progress: dict[str, Any]) -> None:
            progress_status = str(progress.get("status") or "running").strip().lower()
            message_status = "running" if progress_status == "running" else "completed"
            await _update_ai_assistant_message_payload(
                conversation_id,
                assistant_message_id,
                {
                    "content": str(progress.get("content") or ""),
                    "reasoning_content": str(progress.get("reasoning_content") or ""),
                    "tool_traces": progress.get("tool_traces") if isinstance(progress.get("tool_traces"), list) else [],
                    "progress_message": str(progress.get("progress_message") or ""),
                    "status": message_status,
                    "error": False,
                    "provider": provider_key,
                    "provider_label": PROVIDER_CATALOG.get(provider_key, {}).get("label", ""),
                    "provider_config_id": str(provider_config_id or ""),
                    "prompt_plugin_id": str(prompt_plugin_id or ""),
                    "prompt_plugin_name": str(prompt_plugin_name or ""),
                    "model": selected_model,
                },
            )
            await _set_ai_assistant_job(
                job_id,
                {
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_message_id,
                    "status": progress_status if progress_status in {"running", "completed"} else "running",
                    "stage": str(progress.get("stage") or "thinking"),
                    "progress_message": str(progress.get("progress_message") or ""),
                    "error": "",
                    "provider": provider_key,
                    "provider_config_id": str(provider_config_id or ""),
                    "prompt_plugin_id": str(prompt_plugin_id or ""),
                    "prompt_plugin_name": str(prompt_plugin_name or ""),
                    "model": selected_model,
                },
            )

        try:
            await _set_ai_assistant_job(
                job_id,
                {
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "running",
                    "stage": "thinking",
                    "progress_message": "模型思考中...",
                    "error": "",
                    "provider": provider_key,
                    "provider_config_id": str(provider_config_id or ""),
                    "prompt_plugin_id": str(prompt_plugin_id or ""),
                    "prompt_plugin_name": str(prompt_plugin_name or ""),
                    "model": selected_model,
                },
            )
            history = await _get_ai_assistant_conversation_history(conversation_id)
            result = await run_ai_assistant(
                normalized_settings,
                runtime.api_client,
                history,
                provider_key,
                selected_model,
                provider_config_id,
                prompt_plugin_id,
                handle_progress,
            )
            final_model = str(result.get("model") or selected_model)
            await _update_ai_assistant_message_payload(
                conversation_id,
                assistant_message_id,
                {
                    "content": str(result.get("reply") or "已执行完成，但没有返回文本说明。"),
                    "reasoning_content": str(result.get("reasoning_content") or ""),
                    "tool_traces": result.get("tool_traces") if isinstance(result.get("tool_traces"), list) else [],
                    "progress_message": "",
                    "status": "completed",
                    "error": False,
                    "provider": str(result.get("provider") or provider_key),
                    "provider_label": str(result.get("provider_label") or PROVIDER_CATALOG.get(provider_key, {}).get("label", "")),
                    "provider_config_id": str(result.get("provider_config_id") or provider_config_id or ""),
                    "prompt_plugin_id": str(result.get("prompt_plugin_id") or prompt_plugin_id or ""),
                    "prompt_plugin_name": str(result.get("prompt_plugin_name") or prompt_plugin_name or ""),
                    "model": final_model,
                },
            )
            await _set_ai_assistant_job(
                job_id,
                {
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "completed",
                    "stage": "completed",
                    "progress_message": "回复已完成",
                    "error": "",
                    "provider": str(result.get("provider") or provider_key),
                    "provider_config_id": str(result.get("provider_config_id") or provider_config_id or ""),
                    "prompt_plugin_id": str(result.get("prompt_plugin_id") or prompt_plugin_id or ""),
                    "prompt_plugin_name": str(result.get("prompt_plugin_name") or prompt_plugin_name or ""),
                    "model": final_model,
                },
            )
        except asyncio.CancelledError:
            await _mark_ai_assistant_job_stopped(
                job_id,
                conversation_id,
                assistant_message_id,
                provider_key,
                provider_config_id,
                prompt_plugin_id,
                prompt_plugin_name,
                selected_model,
            )
            return
        except Exception as exc:
            error_message = str(exc)
            logger.exception("智能插件异步任务执行失败")
            await _update_ai_assistant_message_payload(
                conversation_id,
                assistant_message_id,
                {
                    "content": f"执行失败：{error_message}",
                    "progress_message": "",
                    "status": "failed",
                    "error": True,
                    "provider": provider_key,
                    "provider_label": PROVIDER_CATALOG.get(provider_key, {}).get("label", ""),
                    "provider_config_id": str(provider_config_id or ""),
                    "prompt_plugin_id": str(prompt_plugin_id or ""),
                    "prompt_plugin_name": str(prompt_plugin_name or ""),
                    "model": selected_model,
                },
            )
            await _set_ai_assistant_job(
                job_id,
                {
                    "conversation_id": conversation_id,
                    "assistant_message_id": assistant_message_id,
                    "status": "failed",
                    "stage": "failed",
                    "progress_message": "执行失败",
                    "error": error_message,
                    "provider": provider_key,
                    "provider_config_id": str(provider_config_id or ""),
                    "prompt_plugin_id": str(prompt_plugin_id or ""),
                    "prompt_plugin_name": str(prompt_plugin_name or ""),
                    "model": selected_model,
                },
            )
        finally:
            await _pop_ai_assistant_job_task(job_id)

    def build_log_payload(
        file_name: str | None = None,
        limit: int = 200,
        time_range: str = "all",
        level: str = "",
        module_query: str = "",
        keyword: str = "",
    ) -> dict:
        if not LOG_DIR.exists():
            return {
                "files": [],
                "active_file": None,
                "lines": [],
            }

        limit = max(1, min(limit, 5000))
        log_files = sorted(LOG_DIR.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not log_files:
            return {
                "files": [],
                "active_file": None,
                "lines": [],
            }

        if file_name:
            target_file = next((path for path in log_files if path.name == file_name), None)
            if target_file is None:
                raise HTTPException(status_code=404, detail="未找到指定日志文件")
        else:
            target_file = log_files[0]

        all_lines = target_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        all_entries = _build_log_entries(all_lines)
        matched_entries = _filter_log_entries(all_entries, time_range, level, module_query, keyword)
        visible_entries = list(reversed(matched_entries[-limit:]))
        return {
            "files": [path.name for path in log_files],
            "active_file": target_file.name,
            "lines": [entry["raw"] for entry in visible_entries],
            "entries": [
                {key: value for key, value in entry.items() if key != "_parsed_timestamp"}
                for entry in visible_entries
            ],
            "line_count": len(visible_entries),
            "matched_line_count": len(matched_entries),
            "total_line_count": len(all_lines),
            "parsed_line_count": sum(1 for entry in all_entries if entry["parsed"]),
            "filters": {
                "time_range": time_range,
                "level": level,
                "module_query": module_query,
                "keyword": keyword,
            },
            "updated_at": datetime.fromtimestamp(target_file.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
        }

    def build_plugin_log_payload(module_name: str | None = None, level: str = "", keyword: str = "", limit: int = 200) -> dict:
        limit = max(1, min(limit, PLUGIN_LOG_LIMIT))
        normalized_level = str(level or "").strip().upper()
        normalized_keyword = str(keyword or "").strip()
        logs, filtered_total = runtime.get_plugin_logs(limit, module_name, normalized_level, normalized_keyword)
        plugin_options = [
            {"module": item["module"], "name": item["name"]}
            for item in build_plugin_payload()
        ]
        available_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        return {
            "logs": logs,
            "total": len(runtime.recent_plugin_logs),
            "filtered_total": filtered_total,
            "module_name": module_name or "",
            "level": normalized_level,
            "keyword": normalized_keyword,
            "available_plugins": plugin_options,
            "available_levels": available_levels,
            "updated_at": logs[0]["recorded_at"] if logs else None,
        }

    def plan_runtime_reload(configured_settings: PluginServiceSettings) -> tuple[PluginServiceSettings, list[str], list[str], list[str]]:
        changed_fields = [
            field
            for field in configured_settings.model_fields
            if getattr(runtime.settings, field) != getattr(configured_settings, field)
        ]
        hot_reload_fields = [field for field in changed_fields if field not in RESTART_REQUIRED_FIELDS]
        restart_required_fields = [field for field in changed_fields if field in RESTART_REQUIRED_FIELDS]
        effective_settings = runtime.settings
        if hot_reload_fields:
            effective_settings = runtime.settings.model_copy(
                update={field: getattr(configured_settings, field) for field in hot_reload_fields}
            )
        return effective_settings, changed_fields, hot_reload_fields, restart_required_fields

    async def sync_runtime_with_config(configured_settings: PluginServiceSettings) -> dict:
        effective_settings, changed_fields, hot_reload_fields, restart_required_fields = plan_runtime_reload(configured_settings)
        if hot_reload_fields:
            await runtime.reload(effective_settings)
        return {
            "changed_fields": changed_fields,
            "applied_fields": hot_reload_fields,
            "restart_required_fields": restart_required_fields,
            "restart_required": bool(restart_required_fields),
        }

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_INDEX_PAGE)

    @app.get("/api/overview")
    async def overview() -> dict:
        return build_overview()

    @app.get("/api/messages")
    async def list_messages(limit: int = 40) -> dict:
        limit = max(1, min(limit, RECENT_MESSAGE_LIMIT))
        messages = await runtime.get_message_views(limit)
        return {
            "messages": messages,
            "total": len(runtime.recent_messages),
        }

    @app.get("/api/users")
    async def get_users() -> dict:
        return build_user_payload()

    @app.get("/api/plugin-targets")
    async def get_plugin_targets() -> dict:
        try:
            return await build_plugin_target_payload()
        except Exception as exc:
            logger.exception("读取插件作用范围选项失败")
            raise HTTPException(status_code=502, detail=f"读取插件作用范围选项失败: {exc}") from exc

    @app.post("/api/plugins/{module_name}/model-options")
    async def get_plugin_model_options(module_name: str, item: PluginConfigUpdateRequest) -> dict:
        config = dict(item.config) if isinstance(item.config, dict) else {}
        requested_field_key = str(config.pop("__model_field_key", "") or "").strip()
        requested_parent_field_key = str(config.pop("__model_parent_field_key", "") or "").strip()
        model_field = resolve_plugin_model_options_field(module_name, requested_field_key, requested_parent_field_key)
        options_loader = str(model_field.get("options_loader") or "openai_compatible").strip().lower()
        if options_loader != "openai_compatible":
            raise HTTPException(status_code=400, detail="当前插件不支持该模型选项加载方式")

        base_url_key = str(model_field.get("base_url_key") or "base_url").strip() or "base_url"
        api_key_key = str(model_field.get("api_key_key") or "api_key").strip() or "api_key"
        current_model_key = str(model_field.get("key") or "model").strip() or "model"

        try:
            return await load_openai_compatible_model_options(
                str(config.get(base_url_key) or ""),
                str(config.get(api_key_key) or ""),
                str(config.get(current_model_key) or ""),
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("读取插件模型选项失败: {}", module_name)
            raise HTTPException(status_code=502, detail=f"读取插件模型选项失败: {exc}") from exc

    @app.get("/api/rooms/{roomid}/members")
    async def get_room_members(roomid: str, wxpid: int | None = None) -> dict:
        normalized_roomid = str(roomid or "").strip()
        if not normalized_roomid:
            raise HTTPException(status_code=400, detail="群聊 roomid 不能为空")

        try:
            room_members_payload = await runtime.api_client.get_room_members(normalized_roomid, wxpid)
        except Exception as exc:
            logger.exception("读取群成员列表失败")
            raise HTTPException(status_code=502, detail=f"读取群成员列表失败: {exc}") from exc

        member_options: list[dict[str, Any]] = []
        seen_member_wxids: set[str] = set()
        for item in room_members_payload if isinstance(room_members_payload, list) else []:
            member_wxid = str(item.get("username") or item.get("wxid") or "").strip()
            if not member_wxid or member_wxid in seen_member_wxids:
                continue
            seen_member_wxids.add(member_wxid)
            nick_name = str(item.get("nick_name") or "").strip()
            room_nick_name = str(item.get("room_nick_name") or "").strip()
            display_name = room_nick_name or nick_name or member_wxid
            member_options.append(
                {
                    "label": display_name,
                    "value": member_wxid,
                    "wxid": member_wxid,
                    "display_name": display_name,
                    "nick_name": nick_name,
                    "room_nick_name": room_nick_name,
                    "avatar_url": str(item.get("small_head_url") or item.get("big_head_url") or "").strip(),
                    "search_text": " ".join(part for part in [display_name, room_nick_name, nick_name, member_wxid] if part),
                }
            )

        return {
            "roomid": normalized_roomid,
            "wxpid": wxpid,
            "count": len(member_options),
            "members": sort_option_items(member_options),
        }

    @app.post("/api/plugin-assets/upload")
    async def upload_plugin_asset(
        module_name: str = Form(...),
        field_key: str = Form(""),
        upload_dir: str = Form("uploads"),
        file: UploadFile = File(...),
    ) -> dict:
        normalized_module_name = normalize_plugin_module_name(module_name)
        if not normalized_module_name:
            raise HTTPException(status_code=400, detail="插件模块不能为空")

        original_file_name = Path(str(file.filename or "")).name
        if not original_file_name:
            raise HTTPException(status_code=400, detail="请选择要上传的文件")

        suffix = Path(original_file_name).suffix.lower()
        if suffix not in PLUGIN_ASSET_IMAGE_EXTENSIONS:
            raise HTTPException(status_code=400, detail="仅支持上传常见图片格式")

        try:
            target_dir = _resolve_project_relative_dir(upload_dir, default="uploads")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")
        if len(content) > PLUGIN_ASSET_MAX_BYTES:
            raise HTTPException(status_code=400, detail="图片不能超过 10MB")

        target_dir.mkdir(parents=True, exist_ok=True)
        file_stem = _sanitize_upload_path_segment(Path(original_file_name).stem, fallback="image")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        target_path = target_dir / f"{file_stem}_{timestamp}{suffix}"
        target_path.write_bytes(content)
        relative_path = target_path.relative_to(PROJECT_ROOT).as_posix()

        return {
            "module_name": normalized_module_name,
            "field_key": str(field_key or "").strip(),
            "path": relative_path,
            "file_name": target_path.name,
            "size": len(content),
        }

    @app.get("/api/settings")
    async def get_settings() -> dict:
        return build_settings_payload()

    @app.post("/api/settings")
    async def update_settings(item: SystemSettingsUpdateRequest) -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        next_settings = configured_settings.model_copy(
            update={
                "host": item.host,
                "port": item.port,
                "callback_path": item.callback_path,
                "wxrobot_api_base_url": item.api_base_url,
                "request_timeout": item.request_timeout,
                "worker_count": item.worker_count,
                "queue_size": item.queue_size,
                "heartbeat_interval_seconds": item.heartbeat_interval_seconds,
            }
        )
        next_settings.save_to_storage()
        reload_state = await sync_runtime_with_config(next_settings)
        return {
            **reload_state,
            "settings": build_settings_payload(),
            "overview": build_overview(),
        }

    @app.get("/api/ai-assistant")
    async def get_ai_assistant() -> dict:
        return await build_ai_assistant_page_payload()

    @app.post("/api/ai-assistant/settings")
    async def update_ai_assistant_settings(item: AiAssistantSettingsUpdateRequest) -> dict:
        normalized_settings = normalize_ai_assistant_settings(item.settings)
        WebuiSettingsStore().set_json_setting(AI_ASSISTANT_SETTINGS_KEY, normalized_settings)
        return await build_ai_assistant_page_payload(normalized_settings)

    @app.post("/api/ai-assistant/conversations")
    async def create_ai_assistant_conversation() -> dict:
        return await _create_ai_assistant_conversation_payload()

    @app.post("/api/ai-assistant/conversations/{conversation_id}/activate")
    async def activate_ai_assistant_conversation(conversation_id: str) -> dict:
        try:
            return await _activate_ai_assistant_conversation_payload(conversation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/ai-assistant/conversations/{conversation_id}/clear")
    async def clear_ai_assistant_conversation(conversation_id: str) -> dict:
        try:
            return await _clear_ai_assistant_conversation_payload(conversation_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/ai-assistant/chat-jobs")
    async def create_ai_assistant_chat_job(item: AiAssistantChatJobCreateRequest) -> dict:
        settings_payload = WebuiSettingsStore().get_json_setting(
            AI_ASSISTANT_SETTINGS_KEY,
            get_default_ai_assistant_settings(),
        )
        normalized_settings = normalize_ai_assistant_settings(settings_payload)
        selected_provider = str(item.provider or normalized_settings["active_provider"] or "").strip().lower()
        if selected_provider not in PROVIDER_CATALOG:
            raise HTTPException(status_code=400, detail="未找到可用的 AI 厂商配置")
        selected_provider_config_id = str(item.provider_config_id or "").strip()
        selected_prompt_plugin = resolve_ai_assistant_prompt_plugin(normalized_settings, item.prompt_plugin_id)
        selected_prompt_plugin_id = str(selected_prompt_plugin.get("id") or "").strip()
        selected_prompt_plugin_name = str(selected_prompt_plugin.get("name") or "").strip()
        selected_model = str(
            item.model
            or PROVIDER_CATALOG[selected_provider]["default_model"]
            or ""
        ).strip()
        try:
            placeholder_context, conversation_payload = await _append_ai_assistant_chat_placeholders(
                item.conversation_id,
                item.prompt,
                selected_provider,
                selected_model,
                selected_prompt_plugin_id,
                selected_prompt_plugin_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        job_id = uuid4().hex
        job = await _set_ai_assistant_job(
            job_id,
            {
                "conversation_id": str(item.conversation_id or "").strip(),
                "assistant_message_id": placeholder_context["assistant_message_id"],
                "status": "queued",
                "stage": "queued",
                "progress_message": "任务已创建，等待执行...",
                "error": "",
                "provider": selected_provider,
                "provider_config_id": selected_provider_config_id,
                "prompt_plugin_id": selected_prompt_plugin_id,
                "prompt_plugin_name": selected_prompt_plugin_name,
                "model": selected_model,
                "created_at": _now_iso(),
            },
        )
        task = asyncio.create_task(
            run_ai_assistant_chat_job(
                job_id,
                str(item.conversation_id or "").strip(),
                placeholder_context["assistant_message_id"],
                selected_provider,
                selected_provider_config_id,
                selected_prompt_plugin_id,
                selected_prompt_plugin_name,
                selected_model,
            )
        )
        await _set_ai_assistant_job_task(job_id, task)
        return {
            "job": job,
            **conversation_payload,
        }

    @app.get("/api/ai-assistant/chat-jobs/{job_id}")
    async def get_ai_assistant_chat_job(job_id: str) -> dict:
        job = await _get_ai_assistant_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到指定智能插件任务")
        conversation_payload = await _ensure_ai_assistant_conversation_payload()
        return {
            "job": job,
            **conversation_payload,
        }

    @app.post("/api/ai-assistant/chat-jobs/{job_id}/stop")
    async def stop_ai_assistant_chat_job(job_id: str) -> dict:
        job = await _get_ai_assistant_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到指定智能插件任务")

        job_status = str(job.get("status") or "").strip().lower()
        if job_status in AI_ASSISTANT_JOB_TERMINAL_STATUSES:
            raise HTTPException(status_code=400, detail="当前对话任务已经结束，无需停止")
        if job_status not in AI_ASSISTANT_JOB_ACTIVE_STATUSES:
            raise HTTPException(status_code=400, detail="当前对话任务不支持停止")

        conversation_id = str(job.get("conversation_id") or "").strip()
        assistant_message_id = str(job.get("assistant_message_id") or "").strip()
        provider_key = str(job.get("provider") or "").strip().lower()
        provider_config_id = str(job.get("provider_config_id") or "").strip()
        prompt_plugin_id = str(job.get("prompt_plugin_id") or "").strip()
        prompt_plugin_name = str(job.get("prompt_plugin_name") or "").strip()
        selected_model = str(job.get("model") or "").strip()

        if conversation_id and assistant_message_id:
            await _update_ai_assistant_message_payload(
                conversation_id,
                assistant_message_id,
                {
                    "progress_message": "正在停止当前对话...",
                    "status": "running",
                    "error": False,
                },
            )

        job = await _set_ai_assistant_job(
            job_id,
            {
                "status": "stopping",
                "stage": "stopping",
                "progress_message": "正在停止当前对话...",
                "error": "",
            },
        )

        task = await _get_ai_assistant_job_task(job_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.sleep(0)

        current_job = await _get_ai_assistant_job(job_id)
        if current_job is not None and str(current_job.get("status") or "") == "stopping" and conversation_id and assistant_message_id:
            current_job = await _mark_ai_assistant_job_stopped(
                job_id,
                conversation_id,
                assistant_message_id,
                provider_key,
                provider_config_id,
                prompt_plugin_id,
                prompt_plugin_name,
                selected_model,
            )

        conversation_payload = await _ensure_ai_assistant_conversation_payload()
        return {
            "job": current_job or job,
            **conversation_payload,
        }

    @app.post("/api/ai-assistant/chat")
    async def chat_with_ai_assistant(item: AiAssistantChatRequest) -> dict:
        settings_payload = WebuiSettingsStore().get_json_setting(
            AI_ASSISTANT_SETTINGS_KEY,
            get_default_ai_assistant_settings(),
        )
        normalized_settings = normalize_ai_assistant_settings(settings_payload)
        try:
            return await run_ai_assistant(
                normalized_settings,
                runtime.api_client,
                [message.model_dump(mode="python") for message in item.messages],
                item.provider,
                item.model,
                item.provider_config_id,
                item.prompt_plugin_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("智能插件执行失败")
            raise HTTPException(status_code=502, detail=f"智能插件执行失败: {exc}") from exc

    @app.get("/api/logs")
    async def get_logs(
        file_name: str | None = None,
        limit: int = 200,
        time_range: str = "all",
        level: str = "",
        module_query: str = "",
        keyword: str = "",
    ) -> dict:
        return build_log_payload(file_name, limit, time_range, level, module_query, keyword)

    @app.get("/api/plugin-logs")
    async def get_plugin_logs(module_name: str | None = None, level: str = "", keyword: str = "", limit: int = 200) -> dict:
        return build_plugin_log_payload(module_name, level, keyword, limit)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "queued_messages": runtime.queue.qsize(),
            "plugins": [plugin.name for plugin in runtime.manager.plugins],
        }

    @app.get("/plugins")
    async def list_plugins() -> dict:
        return build_overview()

    @app.get("/api/plugins")
    async def list_plugins_api() -> dict:
        return {
            "plugins": build_plugin_payload(),
        }

    @app.post("/api/plugins/reload")
    async def reload_plugins() -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        reload_state = await sync_runtime_with_config(configured_settings)
        return {
            **reload_state,
            "overview": build_overview(),
            "plugins": build_plugin_payload(),
            "settings": build_settings_payload(),
        }

    @app.post("/api/plugins/{module_name}/toggle")
    async def toggle_plugin(module_name: str, item: PluginToggleRequest) -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        available_modules = set(PluginManager.discover_plugin_modules()) | set(configured_settings.plugins)
        if module_name not in available_modules:
            raise HTTPException(status_code=404, detail="未找到指定插件模块")

        next_plugins = list(dict.fromkeys(configured_settings.plugins))
        if item.enabled and module_name not in next_plugins:
            next_plugins.append(module_name)
        if not item.enabled:
            next_plugins = [name for name in next_plugins if name != module_name]

        next_settings = configured_settings.model_copy(update={"plugins": next_plugins})
        next_settings.save_to_storage()
        reload_state = await sync_runtime_with_config(next_settings)
        return {
            **reload_state,
            "overview": build_overview(),
            "plugins": build_plugin_payload(),
            "settings": build_settings_payload(),
        }

    @app.post("/api/plugins/{module_name}/config")
    async def update_plugin_config(module_name: str, item: PluginConfigUpdateRequest) -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        available_modules = set(PluginManager.discover_plugin_modules()) | set(configured_settings.plugins)
        if module_name not in available_modules:
            raise HTTPException(status_code=404, detail="未找到指定插件模块")

        next_plugin_settings = dict(configured_settings.plugin_settings)
        if item.config:
            next_plugin_settings[module_name] = item.config
        else:
            next_plugin_settings.pop(module_name, None)

        next_settings = configured_settings.model_copy(update={"plugin_settings": next_plugin_settings})
        next_settings.save_to_storage()
        reload_state = await sync_runtime_with_config(next_settings)
        return {
            **reload_state,
            "overview": build_overview(),
            "plugins": build_plugin_payload(),
            "settings": build_settings_payload(),
        }

    @app.post("/api/plugins/{module_name}/execute")
    async def execute_plugin(module_name: str, item: PluginExecuteRequest) -> dict:
        available_modules = set(PluginManager.discover_plugin_modules())
        if module_name not in available_modules:
            raise HTTPException(status_code=404, detail="未找到指定插件模块")

        metadata_list = PluginManager.describe_modules([module_name])
        metadata = metadata_list[0] if metadata_list else None
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=404, detail="未找到指定插件模块")
        if metadata.get("message_dependent"):
            raise HTTPException(status_code=400, detail="消息插件不支持手动执行")

        try:
            execution = await runtime.start_manual_plugin_execution(module_name, item.config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("手动执行插件失败: {}", module_name)
            raise HTTPException(status_code=500, detail=f"执行插件失败: {exc}") from exc

        return {
            "execution": execution,
            "result": execution.get("result"),
            "overview": build_overview(),
            "plugins": build_plugin_payload(),
            "settings": build_settings_payload(),
        }

    @app.post("/api/plugins/{module_name}/stop")
    async def stop_plugin_execution(module_name: str) -> dict:
        available_modules = set(PluginManager.discover_plugin_modules())
        if module_name not in available_modules:
            raise HTTPException(status_code=404, detail="未找到指定插件模块")

        try:
            execution = await runtime.stop_manual_plugin_execution(module_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("停止手动执行插件失败: {}", module_name)
            raise HTTPException(status_code=500, detail=f"停止插件失败: {exc}") from exc

        return {
            "execution": execution,
            "overview": build_overview(),
            "plugins": build_plugin_payload(),
            "settings": build_settings_payload(),
        }

    async def receive_message(payload: dict) -> dict:
        event = MessageEvent.model_validate(payload)
        if event.is_empty:
            logger.warning("忽略空消息回调: {}", payload)
            return {
                "queued": False,
                "ignored": True,
                "reason": "empty-payload",
                "plugin_count": len(runtime.manager.plugins),
            }
        internal_id = await runtime.enqueue(event)
        return {
            "queued": True,
            "internal_id": internal_id,
            "msgid": event.normalized_msgid,
            "conversation_wxid": event.conversation_wxid,
            "plugin_count": len(runtime.manager.plugins),
        }

    app.add_api_route(
        settings.callback_path,
        receive_message,
        methods=["POST"],
        summary="接收微信消息并投递给插件队列",
    )
    return app


def main() -> FastAPI:
    settings = PluginServiceSettings.from_storage()
    logger.info("请将 config.ini 中 base.post_api 设置为: {}", settings.callback_url)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, reload=False)
    return app
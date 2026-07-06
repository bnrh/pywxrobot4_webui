import asyncio
import json
from copy import deepcopy
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from os import PathLike
from pathlib import Path
import re
from time import monotonic
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

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
from api_schemas import (
    AiAssistantChatJobCreateRequest,
    AiAssistantChatRequest,
    AiAssistantSettingsUpdateRequest,
    PluginConfigUpdateRequest,
    PluginExecuteRequest,
    PluginToggleRequest,
    SystemSettingsUpdateRequest,
)
from config import (
    CONFIG_PATH,
    PROJECT_ROOT,
    SETTINGS_DB_PATH,
    PluginServiceSettings,
    WebuiSettingsStore,
    normalize_plugin_module_name,
)
from contact_directory_cache import PLUGIN_TARGETS_CACHE_TTL_SECONDS
from manager import PluginManager
from message import MessageEvent
from plugin_config_payload import normalize_plugin_config_for_payload
from runtime import PLUGIN_LOG_LIMIT, RECENT_MESSAGE_LIMIT, PluginRuntime
from security import (
    is_api_auth_enabled,
    is_callback_auth_enabled,
    is_public_request_path,
    verify_api_token,
    verify_callback_secret,
)


FRONTEND_DIR = Path(__file__).with_name("frontend")
FRONTEND_INDEX_PAGE = FRONTEND_DIR / "index.html"
STATIC_DIR = Path(__file__).with_name("static")
LOG_DIR = SETTINGS_DB_PATH.parent / "logs"
PLUGIN_ASSET_UPLOAD_ROOT = PROJECT_ROOT / "uploads"
PLUGIN_ASSET_MAX_BYTES = 10 * 1024 * 1024
PLUGIN_ASSET_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
RESTART_REQUIRED_FIELDS = {"host", "port", "callback_path", "worker_count", "queue_size"}
RUNTIME_LIGHT_REFRESH_FIELDS = {
    "api_token",
    "callback_secret",
    "request_timeout",
    "wxrobot_api_base_url",
    "heartbeat_interval_seconds",
    "queue_enqueue_wait_seconds",
    "image_download_flag",
    "image_download_wait",
    "image_download_timeout",
}
PLUGIN_MANAGER_RELOAD_FIELDS = {"plugins", "plugin_settings"}
SYSTEM_SETTINGS_FIELDS = (
    "host",
    "port",
    "callback_path",
    "wxrobot_api_base_url",
    "request_timeout",
    "worker_count",
    "queue_size",
    "queue_enqueue_wait_seconds",
    "heartbeat_interval_seconds",
    "image_download_flag",
    "image_download_wait",
    "image_download_timeout",
    "api_token",
    "callback_secret",
)
SECRET_SETTINGS_PLACEHOLDER = "******"
REMOVED_PLUGIN_MODULES = {normalize_plugin_module_name("webui.plugins.monitor_biz")}
DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE = normalize_plugin_module_name("plugins.download_recent_user_images")
DONT_REVOKE_PLUGIN_MODULE = normalize_plugin_module_name("plugins.dont_revoke")
DIRECT_EXECUTE_PLUGIN_MODULES = {
    normalize_plugin_module_name("plugins.room_msg_summary"),
    normalize_plugin_module_name("plugins.user_msg_summary"),
    normalize_plugin_module_name("plugins.export_contacts"),
    DOWNLOAD_RECENT_USER_IMAGES_PLUGIN_MODULE,
    DONT_REVOKE_PLUGIN_MODULE,
}
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
ai_assistant_storage_lock = asyncio.Lock()
ai_assistant_job_lock = asyncio.Lock()
ai_assistant_jobs: dict[str, dict[str, Any]] = {}
ai_assistant_job_tasks: dict[str, asyncio.Task[Any]] = {}


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

    @app.middleware("http")
    async def enforce_security_middleware(request, call_next):
        request_path = str(request.url.path or "")
        if is_public_request_path(request_path):
            return await call_next(request)

        current_settings = getattr(app.state, "plugin_runtime", runtime).settings
        callback_path = str(current_settings.callback_path or "/messages").rstrip("/") or "/messages"
        normalized_request_path = request_path.rstrip("/") or "/"
        if request.method.upper() == "POST" and normalized_request_path == callback_path:
            verify_callback_secret(request, current_settings)
            return await call_next(request)

        verify_api_token(request, current_settings)
        return await call_next(request)

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
                    "direct_execute": normalize_plugin_module_name(item["module"]) in DIRECT_EXECUTE_PLUGIN_MODULES,
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
        now = monotonic()
        if (
            runtime._plugin_targets_cache is not None
            and now - runtime._plugin_targets_cache_at <= PLUGIN_TARGETS_CACHE_TTL_SECONDS
        ):
            return dict(runtime._plugin_targets_cache)

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

        payload = {
            "default_wxpid": wxpids[0] if wxpids else None,
            "wxpid_options": sort_option_items(wxpid_options),
            "room_options": sort_option_items(room_options),
            "label_options": sort_option_items(label_options),
        }
        runtime._plugin_targets_cache = payload
        runtime._plugin_targets_cache_at = monotonic()
        return dict(payload)

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
                "wxrobot_api_reachable": runtime.wxrobot_api_reachable,
            },
        }

    def serialize_system_settings(settings_obj: PluginServiceSettings, *, mask_secrets: bool = True) -> dict[str, Any]:
        payload = {field: getattr(settings_obj, field) for field in SYSTEM_SETTINGS_FIELDS if field != "wxrobot_api_base_url"}
        payload["api_base_url"] = settings_obj.wxrobot_api_base_url
        if mask_secrets:
            payload["api_token"] = SECRET_SETTINGS_PLACEHOLDER if str(payload.get("api_token") or "").strip() else ""
            payload["callback_secret"] = SECRET_SETTINGS_PLACEHOLDER if str(payload.get("callback_secret") or "").strip() else ""
            payload["api_token_configured"] = bool(str(getattr(settings_obj, "api_token", "") or "").strip())
            payload["callback_secret_configured"] = bool(str(getattr(settings_obj, "callback_secret", "") or "").strip())
        return payload

    def merge_secret_settings_updates(
        configured_settings: PluginServiceSettings,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        merged_updates = dict(updates)
        for field_name in ("api_token", "callback_secret"):
            incoming_value = str(merged_updates.get(field_name) or "").strip()
            if not incoming_value or incoming_value == SECRET_SETTINGS_PLACEHOLDER:
                merged_updates[field_name] = getattr(configured_settings, field_name, "")
        return merged_updates

    def build_settings_payload() -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        runtime_payload = serialize_system_settings(runtime.settings)
        configured_payload = serialize_system_settings(configured_settings)
        restart_required_fields = [
            field
            for field in RESTART_REQUIRED_FIELDS
            if getattr(runtime.settings, field) != getattr(configured_settings, field)
        ]
        return {
            "runtime": runtime_payload,
            "config": configured_payload,
            "restart_required": bool(restart_required_fields),
            "restart_required_fields": restart_required_fields,
            "api_auth_enabled": is_api_auth_enabled(configured_settings),
            "callback_auth_enabled": is_callback_auth_enabled(configured_settings),
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
        manager_reload_needed = any(field in PLUGIN_MANAGER_RELOAD_FIELDS for field in hot_reload_fields)
        light_fields = [field for field in hot_reload_fields if field in RUNTIME_LIGHT_REFRESH_FIELDS]
        if manager_reload_needed:
            await runtime.reload(configured_settings)
        elif light_fields:
            await runtime.apply_light_settings(configured_settings, light_fields)
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
        secret_updates = merge_secret_settings_updates(
            configured_settings,
            {
                "api_token": item.api_token,
                "callback_secret": item.callback_secret,
            },
        )
        next_settings = configured_settings.model_copy(
            update={
                "host": item.host,
                "port": item.port,
                "callback_path": item.callback_path,
                "wxrobot_api_base_url": item.api_base_url,
                "request_timeout": item.request_timeout,
                "worker_count": item.worker_count,
                "queue_size": item.queue_size,
                "queue_enqueue_wait_seconds": item.queue_enqueue_wait_seconds,
                "heartbeat_interval_seconds": item.heartbeat_interval_seconds,
                "api_token": secret_updates["api_token"],
                "callback_secret": secret_updates["callback_secret"],
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

    @app.get("/api/events/stream")
    async def stream_runtime_events() -> StreamingResponse:
        async def event_generator():
            queue = await runtime.event_hub.subscribe()
            try:
                connected_event = json.dumps({"type": "connected", "payload": {}}, ensure_ascii=False)
                yield f"data: {connected_event}\n\n"
                while True:
                    event = await queue.get()
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                raise
            finally:
                await runtime.event_hub.unsubscribe(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/health")
    async def health() -> dict:
        uptime_seconds = int((datetime.now().astimezone() - runtime.started_at).total_seconds()) if runtime.started_at else 0
        return {
            "status": "ok",
            "queued_messages": runtime.queue.qsize(),
            "queue_size": runtime.settings.queue_size,
            "worker_count": runtime.settings.worker_count,
            "loaded_plugin_count": len(runtime.manager.plugins),
            "enabled_plugin_count": len(runtime.settings.plugins),
            "uptime_seconds": uptime_seconds,
            "wxrobot_api_reachable": runtime.wxrobot_api_reachable,
            "heartbeat_healthy": runtime.heartbeat_healthy,
            "plugins": [plugin.name for plugin in runtime.manager.plugins],
        }

    @app.get("/api/metrics")
    async def metrics() -> dict:
        uptime_seconds = int((datetime.now().astimezone() - runtime.started_at).total_seconds()) if runtime.started_at else 0
        active_workers = sum(1 for task in runtime._workers if not task.done())
        rejected_count = runtime.message_store.count_queue_rejections()
        return {
            "uptime_seconds": uptime_seconds,
            "queue": {
                "size": runtime.queue.qsize(),
                "capacity": runtime.settings.queue_size,
                "enqueue_wait_seconds": runtime.settings.queue_enqueue_wait_seconds,
            },
            "workers": {
                "configured": runtime.settings.worker_count,
                "active": active_workers,
            },
            "messages": {
                "recent": len(runtime.recent_messages),
                "queue_rejections": rejected_count,
            },
            "plugins": {
                "loaded": len(runtime.manager.plugins),
                "enabled": len(runtime.settings.plugins),
            },
            "plugin_logs": {
                "recent": len(runtime.recent_plugin_logs),
            },
            "connectivity": {
                "wxrobot_api_reachable": runtime.wxrobot_api_reachable,
                "heartbeat_healthy": runtime.heartbeat_healthy,
            },
        }

    @app.get("/api/message-types")
    async def message_types() -> dict:
        from message_types import build_message_types_payload

        return build_message_types_payload()

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
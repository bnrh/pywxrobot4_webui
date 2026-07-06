"""AI 助手对话与异步任务状态存储。"""

from __future__ import annotations

import asyncio
import re
from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import uuid4

from ai_assistant import PROVIDER_CATALOG
from config import WebuiSettingsStore

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

__all__ = [
    "AI_ASSISTANT_CONVERSATIONS_KEY",
    "AI_ASSISTANT_CONVERSATION_LIMIT",
    "AI_ASSISTANT_MESSAGE_LIMIT",
    "AI_ASSISTANT_JOB_LIMIT",
    "AI_ASSISTANT_JOB_TERMINAL_STATUSES",
    "AI_ASSISTANT_JOB_ACTIVE_STATUSES",
    "activate_ai_assistant_conversation_payload",
    "append_ai_assistant_chat_placeholders",
    "clear_ai_assistant_conversation_payload",
    "create_ai_assistant_conversation_payload",
    "ensure_ai_assistant_conversation_payload",
    "get_ai_assistant_conversation_history",
    "get_ai_assistant_job",
    "get_ai_assistant_job_task",
    "mark_ai_assistant_job_stopped",
    "now_iso",
    "pop_ai_assistant_job_task",
    "set_ai_assistant_job",
    "set_ai_assistant_job_task",
    "update_ai_assistant_message_payload",
]


def now_iso() -> str:
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
    created_at = str(payload.get("created_at") or "").strip() or now_iso()
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
    created_at = now_iso()
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
    created_at = str(payload.get("created_at") or "").strip() or now_iso()
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


async def ensure_ai_assistant_conversation_payload() -> dict[str, Any]:
    async with ai_assistant_storage_lock:
        store = _save_ai_assistant_conversation_store(_load_ai_assistant_conversation_store())
    return _build_ai_assistant_conversation_payload(store)


async def create_ai_assistant_conversation_payload() -> dict[str, Any]:
    def mutator(store: dict[str, Any]) -> None:
        conversation = _build_new_ai_assistant_conversation()
        store["conversations"].insert(0, conversation)
        store["active_conversation_id"] = conversation["id"]

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def activate_ai_assistant_conversation_payload(conversation_id: str) -> dict[str, Any]:
    normalized_id = str(conversation_id or "").strip()

    def mutator(store: dict[str, Any]) -> None:
        conversation = _get_ai_assistant_conversation(store, normalized_id)
        if conversation is None:
            raise ValueError("未找到指定对话")
        store["active_conversation_id"] = normalized_id
        _move_ai_assistant_conversation_to_front(store, normalized_id)

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def clear_ai_assistant_conversation_payload(conversation_id: str) -> dict[str, Any]:
    normalized_id = str(conversation_id or "").strip()

    def mutator(store: dict[str, Any]) -> None:
        conversation = _get_ai_assistant_conversation(store, normalized_id)
        if conversation is None:
            raise ValueError("未找到指定对话")
        conversation["messages"] = []
        conversation["updated_at"] = now_iso()
        conversation["title"] = _default_ai_assistant_conversation_title(conversation["updated_at"])
        store["active_conversation_id"] = normalized_id
        _move_ai_assistant_conversation_to_front(store, normalized_id)

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def append_ai_assistant_chat_placeholders(
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
        now = now_iso()
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


async def update_ai_assistant_message_payload(conversation_id: str, message_id: str, updates: dict[str, Any]) -> dict[str, Any]:
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
        target_message["updated_at"] = now_iso()
        conversation["updated_at"] = target_message["updated_at"]
        if conversation.get("messages") and (not conversation.get("title") or str(conversation.get("title") or "").startswith("新对话")):
            conversation["title"] = _derive_ai_assistant_conversation_title(conversation["messages"], _default_ai_assistant_conversation_title(conversation["updated_at"]))
        _move_ai_assistant_conversation_to_front(store, normalized_conversation_id)

    _, store = await _mutate_ai_assistant_conversation_store(mutator)
    return _build_ai_assistant_conversation_payload(store)


async def get_ai_assistant_message_payload(conversation_id: str, message_id: str) -> dict[str, Any] | None:
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    async with ai_assistant_storage_lock:
        store = _load_ai_assistant_conversation_store()
    conversation = _get_ai_assistant_conversation(store, normalized_conversation_id)
    if conversation is None:
        return None
    message = next((item for item in conversation.get("messages", []) if item.get("id") == normalized_message_id), None)
    return deepcopy(message) if message is not None else None


async def get_ai_assistant_conversation_history(conversation_id: str) -> list[dict[str, Any]]:
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
    payload.setdefault("created_at", now_iso())
    payload.setdefault("updated_at", payload["created_at"])
    return payload


async def set_ai_assistant_job(job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    normalized_job_id = str(job_id or "").strip() or uuid4().hex
    async with ai_assistant_job_lock:
        current = _normalize_ai_assistant_job_payload(ai_assistant_jobs.get(normalized_job_id, {"id": normalized_job_id}))
        current.update(updates)
        current["id"] = normalized_job_id
        current["updated_at"] = now_iso()
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


async def get_ai_assistant_job(job_id: str) -> dict[str, Any] | None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        job = ai_assistant_jobs.get(normalized_job_id)
        return deepcopy(job) if job is not None else None


async def set_ai_assistant_job_task(job_id: str, task: asyncio.Task[Any]) -> None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        ai_assistant_job_tasks[normalized_job_id] = task


async def get_ai_assistant_job_task(job_id: str) -> asyncio.Task[Any] | None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        return ai_assistant_job_tasks.get(normalized_job_id)


async def pop_ai_assistant_job_task(job_id: str) -> asyncio.Task[Any] | None:
    normalized_job_id = str(job_id or "").strip()
    async with ai_assistant_job_lock:
        return ai_assistant_job_tasks.pop(normalized_job_id, None)


async def mark_ai_assistant_job_stopped(
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
    current_job = await get_ai_assistant_job(job_id)
    if current_job is not None and str(current_job.get("status") or "") == "stopped":
        return current_job

    current_message = await get_ai_assistant_message_payload(conversation_id, assistant_message_id) or {}
    preserved_content = str(current_message.get("content") or "").strip()
    await update_ai_assistant_message_payload(
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
    return await set_ai_assistant_job(
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



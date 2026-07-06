"""AI 助手页面载荷与异步聊天任务。"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from ai_assistant import (
    AI_ASSISTANT_SETTINGS_KEY,
    PROVIDER_CATALOG,
    build_ai_assistant_payload,
    get_default_ai_assistant_settings,
    normalize_ai_assistant_settings,
    run_ai_assistant,
)
from ai_assistant_store import (
    _ensure_ai_assistant_conversation_payload,
    _get_ai_assistant_conversation_history,
    _mark_ai_assistant_job_stopped,
    _pop_ai_assistant_job_task,
    _set_ai_assistant_job,
    _update_ai_assistant_message_payload,
)
from config import WebuiSettingsStore
from runtime import PluginRuntime


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
    runtime: PluginRuntime,
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

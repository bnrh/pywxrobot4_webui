"""AI 助手相关 API 路由。"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from loguru import logger

from ai_assistant import (
    AI_ASSISTANT_SETTINGS_KEY,
    PROVIDER_CATALOG,
    get_default_ai_assistant_settings,
    normalize_ai_assistant_settings,
    resolve_ai_assistant_prompt_plugin,
    run_ai_assistant,
)
from ai_assistant_jobs import build_ai_assistant_page_payload, run_ai_assistant_chat_job
from ai_assistant_store import (
    AI_ASSISTANT_JOB_ACTIVE_STATUSES,
    AI_ASSISTANT_JOB_TERMINAL_STATUSES,
    _activate_ai_assistant_conversation_payload,
    _append_ai_assistant_chat_placeholders,
    _clear_ai_assistant_conversation_payload,
    _create_ai_assistant_conversation_payload,
    _ensure_ai_assistant_conversation_payload,
    _get_ai_assistant_job,
    _get_ai_assistant_job_task,
    _mark_ai_assistant_job_stopped,
    _now_iso,
    _set_ai_assistant_job,
    _set_ai_assistant_job_task,
    _update_ai_assistant_message_payload,
)
from api_schemas import AiAssistantChatJobCreateRequest, AiAssistantChatRequest, AiAssistantSettingsUpdateRequest
from config import WebuiSettingsStore
from server_context import AppContext


def register_ai_assistant_routes(app: FastAPI, ctx: AppContext) -> None:
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
                ctx.runtime,
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
                ctx.runtime.api_client,
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

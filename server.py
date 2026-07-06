import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
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
    get_default_ai_assistant_settings,
    load_openai_compatible_model_options,
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
from app_builders import AppBuilders
from app_config import (
    FRONTEND_DIR,
    FRONTEND_INDEX_PAGE,
    LOG_DIR,
    PLUGIN_ASSET_IMAGE_EXTENSIONS,
    PLUGIN_ASSET_MAX_BYTES,
    PLUGIN_ASSET_UPLOAD_ROOT,
    SECRET_SETTINGS_PLACEHOLDER,
    STATIC_DIR,
    sanitize_stored_settings,
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
    PluginServiceSettings,
    WebuiSettingsStore,
    normalize_plugin_module_name,
)
from log_reader import build_log_payload as build_service_log_payload
from manager import PluginManager
from message import MessageEvent
from runtime_sync import sync_runtime_with_config
from upload_paths import resolve_project_relative_dir, sanitize_upload_path_segment
from runtime import RECENT_MESSAGE_LIMIT, PluginRuntime
from security import (
    is_public_request_path,
    verify_api_token,
    verify_callback_secret,
)


def create_app(settings: PluginServiceSettings | None = None) -> FastAPI:
    settings = sanitize_stored_settings(settings or PluginServiceSettings.from_storage())
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

    builders = AppBuilders(runtime)

    def with_mutation_payload(reload_state: dict[str, Any]) -> dict[str, Any]:
        return {
            **reload_state,
            "overview": builders.build_overview(),
            "plugins": builders.build_plugin_payload(),
            "settings": builders.build_settings_payload(),
        }

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_INDEX_PAGE)

    @app.get("/api/overview")
    async def overview() -> dict:
        return builders.build_overview()

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
        return builders.build_user_payload()

    @app.get("/api/plugin-targets")
    async def get_plugin_targets() -> dict:
        try:
            return await builders.build_plugin_target_payload()
        except Exception as exc:
            logger.exception("读取插件作用范围选项失败")
            raise HTTPException(status_code=502, detail=f"读取插件作用范围选项失败: {exc}") from exc

    @app.post("/api/plugins/{module_name}/model-options")
    async def get_plugin_model_options(module_name: str, item: PluginConfigUpdateRequest) -> dict:
        config = dict(item.config) if isinstance(item.config, dict) else {}
        requested_field_key = str(config.pop("__model_field_key", "") or "").strip()
        requested_parent_field_key = str(config.pop("__model_parent_field_key", "") or "").strip()
        model_field = builders.resolve_plugin_model_options_field(module_name, requested_field_key, requested_parent_field_key)
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
            target_dir = resolve_project_relative_dir(upload_dir, default="uploads")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空")
        if len(content) > PLUGIN_ASSET_MAX_BYTES:
            raise HTTPException(status_code=400, detail="图片不能超过 10MB")

        target_dir.mkdir(parents=True, exist_ok=True)
        file_stem = sanitize_upload_path_segment(Path(original_file_name).stem, fallback="image")
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
        return builders.build_settings_payload()

    @app.post("/api/settings")
    async def update_settings(item: SystemSettingsUpdateRequest) -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        secret_updates = AppBuilders.merge_secret_settings_updates(
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
        reload_state = await sync_runtime_with_config(runtime, next_settings)
        return {
            **reload_state,
            "settings": builders.build_settings_payload(),
            "overview": builders.build_overview(),
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
                runtime,
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
        return build_service_log_payload(
            LOG_DIR,
            file_name=file_name,
            limit=limit,
            time_range=time_range,
            level=level,
            module_query=module_query,
            keyword=keyword,
        )

    @app.get("/api/plugin-logs")
    async def get_plugin_logs(module_name: str | None = None, level: str = "", keyword: str = "", limit: int = 200) -> dict:
        return builders.build_plugin_log_payload(module_name, level, keyword, limit)

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
        return builders.build_overview()

    @app.get("/api/plugins")
    async def list_plugins_api() -> dict:
        return {
            "plugins": builders.build_plugin_payload(),
        }

    @app.post("/api/plugins/reload")
    async def reload_plugins() -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        reload_state = await sync_runtime_with_config(runtime,configured_settings)
        return {
            **reload_state,
            "overview": builders.build_overview(),
            "plugins": builders.build_plugin_payload(),
            "settings": builders.build_settings_payload(),
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
        reload_state = await sync_runtime_with_config(runtime, next_settings)
        return {
            **reload_state,
            "overview": builders.build_overview(),
            "plugins": builders.build_plugin_payload(),
            "settings": builders.build_settings_payload(),
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
        reload_state = await sync_runtime_with_config(runtime, next_settings)
        return {
            **reload_state,
            "overview": builders.build_overview(),
            "plugins": builders.build_plugin_payload(),
            "settings": builders.build_settings_payload(),
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
            "overview": builders.build_overview(),
            "plugins": builders.build_plugin_payload(),
            "settings": builders.build_settings_payload(),
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
            "overview": builders.build_overview(),
            "plugins": builders.build_plugin_payload(),
            "settings": builders.build_settings_payload(),
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
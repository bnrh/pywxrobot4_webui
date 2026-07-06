from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ai_assistant import load_openai_compatible_model_options
from app_builders import AppBuilders
from app_config import (
    FRONTEND_INDEX_PAGE,
    LOG_DIR,
    PLUGIN_ASSET_IMAGE_EXTENSIONS,
    PLUGIN_ASSET_MAX_BYTES,
    STATIC_DIR,
    sanitize_stored_settings,
)
from api_schemas import PluginConfigUpdateRequest, SystemSettingsUpdateRequest
from config import PROJECT_ROOT, PluginServiceSettings, normalize_plugin_module_name
from log_reader import build_log_payload as build_service_log_payload
from message import MessageEvent
from routes.ai_assistant_routes import register_ai_assistant_routes
from routes.observability_routes import register_observability_routes
from routes.plugin_admin_routes import register_plugin_admin_routes
from runtime import RECENT_MESSAGE_LIMIT, PluginRuntime
from runtime_sync import sync_runtime_with_config
from security import (
    is_public_request_path,
    verify_api_token,
    verify_callback_secret,
)
from server_context import AppContext
from upload_paths import resolve_project_relative_dir, sanitize_upload_path_segment


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
    ctx = AppContext(runtime, builders)
    register_ai_assistant_routes(app, ctx)
    register_plugin_admin_routes(app, ctx)
    register_observability_routes(app, ctx)

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
            "members": AppBuilders.sort_option_items(member_options),
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

    @app.get("/api/message-types")
    async def message_types() -> dict:
        from message_types import build_message_types_payload

        return build_message_types_payload()

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
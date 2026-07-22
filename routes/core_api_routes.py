"""概览、消息、插件配置与回调等核心 API 路由。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger

from ai_assistant import load_openai_compatible_model_options
from server.builders import AppBuilders
from server.app_config import (
    PLUGIN_ASSET_IMAGE_EXTENSIONS,
    PLUGIN_ASSET_MAX_BYTES,
)
from server.frontend_assets import render_frontend_index_html
from server.schemas import PluginConfigUpdateRequest
from core.config import PROJECT_ROOT, normalize_plugin_module_name
from messaging.event import MessageEvent
from runtime.engine import RECENT_MESSAGE_LIMIT
from server.context import AppContext
from server.upload_paths import resolve_project_relative_dir, sanitize_upload_path_segment


def register_core_api_routes(app: FastAPI, ctx: AppContext, callback_path: str) -> None:
    runtime = ctx.runtime
    builders = ctx.builders

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(render_frontend_index_html())

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

        members = AppBuilders.build_room_member_options(room_members_payload)
        return {
            "roomid": normalized_roomid,
            "wxpid": wxpid,
            "count": len(members),
            "members": members,
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

    @app.get("/api/folders/browse")
    async def browse_folders(path: str = "") -> dict:
        """浏览本地目录，返回指定路径下的子目录列表。

        用于前端「选择文件夹」按钮，支持获取完整目录路径。
        """
        # 解析目标路径：空或相对路径基于项目根目录
        raw_path = str(path or "").strip()
        if not raw_path:
            target = PROJECT_ROOT
        else:
            candidate = Path(raw_path)
            target = candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)

        try:
            target = target.resolve()
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=f"路径解析失败：{exc}") from exc

        if not target.exists():
            raise HTTPException(status_code=400, detail="指定路径不存在")
        if not target.is_dir():
            raise HTTPException(status_code=400, detail="指定路径不是目录")

        # 计算父目录用于「返回上级」
        parent_path = ""
        try:
            parent = target.parent
            # 父目录必须是真实存在的目录，且不能等于自身（盘符根目录的 parent 是自身）
            if parent.exists() and parent.is_dir() and parent != target:
                parent_path = str(parent)
        except (OSError, RuntimeError):
            parent_path = ""

        # 列出子目录
        entries = []
        try:
            for item in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if not item.is_dir():
                    continue
                # 跳过隐藏目录和系统目录
                if item.name.startswith(".") or item.name in {"$RECYCLE.BIN", "System Volume Information"}:
                    continue
                entries.append({
                    "name": item.name,
                    "path": str(item),
                })
        except (OSError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=f"读取目录失败：{exc}") from exc

        return {
            "current_path": str(target),
            "parent_path": parent_path,
            "is_root": str(target) == str(PROJECT_ROOT.resolve()) or len(target.parts) <= 1,
            "entries": entries,
        }

    @app.get("/api/message-types")
    async def message_types() -> dict:
        from messaging.types import build_message_types_payload

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
        callback_path,
        receive_message,
        methods=["POST"],
        summary="接收微信消息并投递给插件队列",
    )

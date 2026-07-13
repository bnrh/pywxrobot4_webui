"""系统设置与日志查询 API 路由。"""

from __future__ import annotations

from fastapi import FastAPI

from server.builders import AppBuilders
from server.app_config import LOG_DIR
from server.schemas import SystemSettingsUpdateRequest
from core.config import PluginServiceSettings
from server.log_reader import build_log_payload as build_service_log_payload
from runtime.sync import sync_runtime_with_config
from server.context import AppContext


def register_settings_routes(app: FastAPI, ctx: AppContext) -> None:
    @app.get("/api/settings")
    async def get_settings() -> dict:
        return ctx.builders.build_settings_payload()

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
        reload_state = await sync_runtime_with_config(ctx.runtime, next_settings)
        return ctx.with_mutation_payload(reload_state)

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
        return ctx.builders.build_plugin_log_payload(module_name, level, keyword, limit)

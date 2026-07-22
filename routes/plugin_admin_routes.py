"""插件管理相关 API 路由。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from loguru import logger

from server.schemas import PluginConfigUpdateRequest, PluginExecuteRequest, PluginToggleRequest
from core.config import PluginServiceSettings
from manager import PluginManager
from runtime.sync import sync_runtime_with_config
from server.context import AppContext


def register_plugin_admin_routes(app: FastAPI, ctx: AppContext) -> None:
    @app.get("/plugins")
    async def list_plugins() -> dict:
        return ctx.builders.build_overview()

    @app.get("/api/plugins")
    async def list_plugins_api() -> dict:
        return {
            "plugins": ctx.builders.build_plugin_payload(),
        }

    @app.post("/api/plugins/reload")
    async def reload_plugins() -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        reload_state = await sync_runtime_with_config(ctx.runtime, configured_settings)
        return ctx.with_mutation_payload(reload_state)

    @app.post("/api/plugins/reload-source")
    async def reload_plugins_from_source() -> dict:
        configured_settings = PluginServiceSettings.from_storage()
        await ctx.runtime.reload(configured_settings)
        return ctx.with_mutation_payload(
            {
                "changed_fields": ["plugins", "plugin_settings"],
                "applied_fields": ["plugins", "plugin_settings"],
                "restart_required_fields": [],
                "restart_required": False,
            }
        )

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
        reload_state = await sync_runtime_with_config(ctx.runtime, next_settings)
        return ctx.with_mutation_payload(reload_state)

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
        reload_state = await sync_runtime_with_config(ctx.runtime, next_settings)
        return ctx.with_mutation_payload(reload_state)

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
            execution = await ctx.runtime.start_manual_plugin_execution(module_name, item.config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("手动执行插件失败: {}", module_name)
            raise HTTPException(status_code=500, detail=f"执行插件失败: {exc}") from exc

        return {
            "execution": execution,
            "result": execution.get("result"),
            **ctx.with_mutation_payload({}),
        }

    @app.post("/api/plugins/{module_name}/stop")
    async def stop_plugin_execution(module_name: str) -> dict:
        available_modules = set(PluginManager.discover_plugin_modules())
        if module_name not in available_modules:
            raise HTTPException(status_code=404, detail="未找到指定插件模块")

        try:
            execution = await ctx.runtime.stop_manual_plugin_execution(module_name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("停止手动执行插件失败: {}", module_name)
            raise HTTPException(status_code=500, detail=f"停止插件失败: {exc}") from exc

        return {
            "execution": execution,
            **ctx.with_mutation_payload({}),
        }

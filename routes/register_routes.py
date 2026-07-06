"""集中注册全部 API 路由。"""

from __future__ import annotations

from fastapi import FastAPI

from routes.ai_assistant_routes import register_ai_assistant_routes
from routes.core_api_routes import register_core_api_routes
from routes.observability_routes import register_observability_routes
from routes.plugin_admin_routes import register_plugin_admin_routes
from routes.settings_routes import register_settings_routes
from server_context import AppContext


def register_app_routes(app: FastAPI, ctx: AppContext, callback_path: str) -> None:
    register_ai_assistant_routes(app, ctx)
    register_plugin_admin_routes(app, ctx)
    register_observability_routes(app, ctx)
    register_settings_routes(app, ctx)
    register_core_api_routes(app, ctx, callback_path)

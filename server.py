from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app_builders import AppBuilders
from app_config import STATIC_DIR, sanitize_stored_settings
from config import PluginServiceSettings
from routes.ai_assistant_routes import register_ai_assistant_routes
from routes.core_api_routes import register_core_api_routes
from routes.observability_routes import register_observability_routes
from routes.plugin_admin_routes import register_plugin_admin_routes
from routes.settings_routes import register_settings_routes
from runtime import PluginRuntime
from security import (
    is_public_request_path,
    verify_api_token,
    verify_callback_secret,
)
from server_context import AppContext


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
    register_settings_routes(app, ctx)
    register_core_api_routes(app, ctx, settings.callback_path)
    return app


def main() -> FastAPI:
    settings = PluginServiceSettings.from_storage()
    logger.info("请将 config.ini 中 base.post_api 设置为: {}", settings.callback_url)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, reload=False)
    return app

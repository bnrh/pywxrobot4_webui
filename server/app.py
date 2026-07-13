from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from server.builders import AppBuilders
from server.app_config import STATIC_DIR, sanitize_stored_settings
from core.config import PluginServiceSettings
from routes.register_routes import register_app_routes
from runtime.engine import PluginRuntime
from server.context import AppContext
from server.middleware import register_security_middleware


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

    register_security_middleware(app, runtime)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    ctx = AppContext(runtime, AppBuilders(runtime))
    register_app_routes(app, ctx, settings.callback_path)
    return app


def main() -> FastAPI:
    settings = PluginServiceSettings.from_storage()
    logger.info("请将 config.ini 中 base.post_api 设置为: {}", settings.callback_url)
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, reload=False)
    return app

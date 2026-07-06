"""HTTP 安全中间件。"""

from __future__ import annotations

from fastapi import FastAPI, Request

from runtime import PluginRuntime
from security import is_public_request_path, verify_api_token, verify_callback_secret


def register_security_middleware(app: FastAPI, runtime: PluginRuntime) -> None:
    @app.middleware("http")
    async def enforce_security_middleware(request: Request, call_next):
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

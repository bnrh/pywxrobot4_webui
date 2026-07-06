"""Web UI 鉴权与回调签名校验。"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from config import PluginServiceSettings

CALLBACK_SECRET_HEADER = "X-Callback-Secret"
API_TOKEN_HEADER = "Authorization"


def _normalize_secret(value: str | None) -> str:
    return str(value or "").strip()


def is_api_auth_enabled(settings: PluginServiceSettings) -> bool:
    return bool(_normalize_secret(getattr(settings, "api_token", "")))


def is_callback_auth_enabled(settings: PluginServiceSettings) -> bool:
    return bool(_normalize_secret(getattr(settings, "callback_secret", "")))


def extract_bearer_token(authorization_header: str | None) -> str:
    normalized = str(authorization_header or "").strip()
    if not normalized:
        return ""
    scheme, _, token = normalized.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def verify_api_token(request: Request, settings: PluginServiceSettings) -> None:
    expected_token = _normalize_secret(getattr(settings, "api_token", ""))
    if not expected_token:
        return

    provided_token = extract_bearer_token(request.headers.get(API_TOKEN_HEADER))
    if not provided_token:
        raise HTTPException(status_code=401, detail="缺少 API Token，请在 Authorization 头中携带 Bearer Token")
    if not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=403, detail="API Token 无效")


def verify_callback_secret(request: Request, settings: PluginServiceSettings) -> None:
    expected_secret = _normalize_secret(getattr(settings, "callback_secret", ""))
    if not expected_secret:
        return

    provided_secret = _normalize_secret(request.headers.get(CALLBACK_SECRET_HEADER))
    if not provided_secret:
        raise HTTPException(status_code=401, detail="缺少消息回调密钥，请在 X-Callback-Secret 请求头中携带")
    if not secrets.compare_digest(provided_secret, expected_secret):
        raise HTTPException(status_code=403, detail="消息回调密钥无效")


def is_public_request_path(path: str) -> bool:
    normalized = str(path or "").strip() or "/"
    if normalized in {"/", "/health", "/docs", "/openapi.json", "/redoc"}:
        return True
    return normalized.startswith("/static/")

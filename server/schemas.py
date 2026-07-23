"""Web API 请求体模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PluginToggleRequest(BaseModel):
    enabled: bool


class PluginConfigUpdateRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class PluginExecuteRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class SystemSettingsUpdateRequest(BaseModel):
    host: str
    port: int = Field(..., ge=1, le=65535)
    callback_path: str
    api_base_url: str
    request_timeout: float = Field(..., gt=0, le=120)
    worker_count: int = Field(..., ge=1, le=32)
    queue_size: int = Field(..., ge=1, le=100000)
    queue_enqueue_wait_seconds: float = Field(..., ge=0, le=30)
    heartbeat_interval_seconds: int = Field(..., ge=0, le=3600)
    api_token: str = ""
    callback_secret: str = ""
    pywxrobot_dir: str = ""
    robot_type: str = "pywxrobot"


class AiAssistantSettingsUpdateRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class AiAssistantChatMessage(BaseModel):
    role: str
    content: str = ""
    reasoning_content: str = ""


class AiAssistantChatRequest(BaseModel):
    provider: str | None = None
    provider_config_id: str | None = None
    prompt_plugin_id: str | None = None
    model: str | None = None
    messages: list[AiAssistantChatMessage] = Field(default_factory=list)


class AiAssistantChatJobCreateRequest(BaseModel):
    conversation_id: str
    prompt: str
    provider: str | None = None
    provider_config_id: str | None = None
    prompt_plugin_id: str | None = None
    model: str | None = None


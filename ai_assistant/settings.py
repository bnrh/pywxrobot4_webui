"""AI assistant settings normalization and payload builders."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .constants import (
    DEFAULT_AI_ASSISTANT_SETTINGS,
    DEFAULT_SYSTEM_PROMPT,
    PROVIDER_CATALOG,
)
from .providers import (
    _build_default_provider_config,
    _clamp_float,
    _clamp_int,
    _load_provider_model_options,
    _normalize_provider_config_entries,
    _normalize_provider_request_timeout,
)
from .tool_registry import get_tool_registry
from utils.normalize import is_truthy

def get_default_ai_assistant_settings() -> dict[str, Any]:
    defaults = deepcopy(DEFAULT_AI_ASSISTANT_SETTINGS)
    if not defaults.get("prompt_plugins"):
        defaults["prompt_plugins"] = [
            {
                "id": str(defaults.get("active_prompt_plugin_id") or "default-smart-plugin"),
                "name": "通用助手",
                "prompt": str(defaults.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT,
                "temperature": _clamp_float(defaults.get("temperature"), 0.2, 0.0, 1.5),
                "max_tool_rounds": _clamp_int(defaults.get("max_tool_rounds"), 20, 1, 500),
            }
        ]
    return defaults


def _build_default_prompt_plugin(index: int = 1) -> dict[str, Any]:
    defaults = DEFAULT_AI_ASSISTANT_SETTINGS
    return {
        "id": "default-smart-plugin" if index == 1 else f"prompt-plugin-{index}",
        "name": "通用助手" if index == 1 else f"提示词插件 {index}",
        "prompt": str(defaults.get("system_prompt") or DEFAULT_SYSTEM_PROMPT).strip() or DEFAULT_SYSTEM_PROMPT,
        "temperature": _clamp_float(defaults.get("temperature"), 0.2, 0.0, 1.5),
        "max_tool_rounds": _clamp_int(defaults.get("max_tool_rounds"), 20, 1, 500),
    }


def _normalize_prompt_plugin_entries(raw_settings: dict[str, Any], defaults: dict[str, Any]) -> list[dict[str, Any]]:
    raw_plugins = raw_settings.get("prompt_plugins") if isinstance(raw_settings.get("prompt_plugins"), list) else None
    normalized_plugins: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def append_plugin(item: dict[str, Any], index: int) -> None:
        default_plugin = _build_default_prompt_plugin(index)
        normalized_id = str(item.get("id") or default_plugin["id"]).strip() or default_plugin["id"]
        if normalized_id in seen_ids:
            normalized_id = f"{normalized_id}-{index}"
        seen_ids.add(normalized_id)
        normalized_plugins.append(
            {
                "id": normalized_id,
                "name": str(item.get("name") or item.get("plugin_name") or default_plugin["name"]).strip() or default_plugin["name"],
                "prompt": str(item.get("prompt") or item.get("system_prompt") or default_plugin["prompt"]).strip() or default_plugin["prompt"],
                "temperature": _clamp_float(item.get("temperature"), default_plugin["temperature"], 0.0, 1.5),
                "max_tool_rounds": _clamp_int(item.get("max_tool_rounds"), default_plugin["max_tool_rounds"], 1, 500),
            }
        )

    if raw_plugins is not None:
        for index, raw_plugin in enumerate(raw_plugins, start=1):
            if not isinstance(raw_plugin, dict):
                continue
            append_plugin(raw_plugin, index)

    if not normalized_plugins:
        append_plugin(
            {
                "id": raw_settings.get("active_prompt_plugin_id") or defaults.get("active_prompt_plugin_id"),
                "name": raw_settings.get("prompt_plugin_name") or "通用助手",
                "prompt": raw_settings.get("system_prompt") or defaults.get("system_prompt"),
                "temperature": raw_settings.get("temperature"),
                "max_tool_rounds": raw_settings.get("max_tool_rounds"),
            },
            1,
        )

    return normalized_plugins


def resolve_ai_assistant_prompt_plugin(settings: dict[str, Any], prompt_plugin_id: str | None = None) -> dict[str, Any]:
    prompt_plugins = settings.get("prompt_plugins") if isinstance(settings.get("prompt_plugins"), list) else []
    if not prompt_plugins:
        raise RuntimeError("当前还没有可用的提示词插件配置")

    normalized_plugin_id = str(prompt_plugin_id or settings.get("active_prompt_plugin_id") or "").strip()
    selected_plugin = next((item for item in prompt_plugins if str(item.get("id") or "") == normalized_plugin_id), None)
    if selected_plugin is None:
        selected_plugin = prompt_plugins[0]
    return selected_plugin

def normalize_ai_assistant_settings(value: Any) -> dict[str, Any]:
    defaults = get_default_ai_assistant_settings()
    raw_settings = value if isinstance(value, dict) else {}
    raw_providers = raw_settings.get("providers") if isinstance(raw_settings.get("providers"), dict) else {}
    prompt_plugins = _normalize_prompt_plugin_entries(raw_settings, defaults)
    providers: dict[str, dict[str, Any]] = {}
    for provider_key, provider_meta in PROVIDER_CATALOG.items():
        raw_provider = raw_providers.get(provider_key) if isinstance(raw_providers.get(provider_key), dict) else {}
        configs = _normalize_provider_config_entries(provider_key, provider_meta, raw_provider)
        providers[provider_key] = {
            "configured": any(bool(item.get("api_key")) for item in configs),
            "enabled": any(bool(item.get("enabled") and item.get("api_key")) for item in configs),
            "configs": configs,
        }

    active_provider = str(raw_settings.get("active_provider") or defaults["active_provider"]).strip().lower()
    if active_provider not in PROVIDER_CATALOG:
        active_provider = defaults["active_provider"]

    active_prompt_plugin_id = str(raw_settings.get("active_prompt_plugin_id") or defaults.get("active_prompt_plugin_id") or "").strip()
    if active_prompt_plugin_id not in {str(item.get("id") or "") for item in prompt_plugins}:
        active_prompt_plugin_id = str(prompt_plugins[0].get("id") or defaults.get("active_prompt_plugin_id") or "default-smart-plugin")
    selected_prompt_plugin = resolve_ai_assistant_prompt_plugin(
        {
            "prompt_plugins": prompt_plugins,
            "active_prompt_plugin_id": active_prompt_plugin_id,
        },
        active_prompt_plugin_id,
    )

    return {
        "active_provider": active_provider,
        "active_prompt_plugin_id": active_prompt_plugin_id,
        "system_prompt": str(selected_prompt_plugin.get("prompt") or defaults["system_prompt"]).strip() or defaults["system_prompt"],
        "temperature": _clamp_float(selected_prompt_plugin.get("temperature"), defaults["temperature"], 0.0, 1.5),
        "max_tool_rounds": _clamp_int(selected_prompt_plugin.get("max_tool_rounds"), defaults["max_tool_rounds"], 1, 500),
        "allow_write_tools": is_truthy(raw_settings.get("allow_write_tools"), bool(defaults.get("allow_write_tools", False))),
        "prompt_plugins": prompt_plugins,
        "providers": providers,
    }


async def build_ai_assistant_payload(settings: dict[str, Any]) -> dict[str, Any]:
    normalized_settings = normalize_ai_assistant_settings(settings)
    provider_keys = list(PROVIDER_CATALOG.keys())
    model_option_results = await asyncio.gather(
        *[_load_provider_model_options(provider_key, normalized_settings["providers"][provider_key]) for provider_key in provider_keys]
    )
    providers = []
    for provider_index, provider_key in enumerate(provider_keys):
        provider_meta = PROVIDER_CATALOG[provider_key]
        provider_settings = normalized_settings["providers"][provider_key]
        model_options = model_option_results[provider_index]
        config_states = model_options.get("configs") if isinstance(model_options.get("configs"), dict) else {}
        config_payloads = []
        for provider_config in provider_settings["configs"]:
            config_state = config_states.get(provider_config["id"], {"options": [], "error": ""})
            config_payloads.append(
                {
                    "id": provider_config["id"],
                    "name": provider_config["name"],
                    "enabled": provider_config["enabled"],
                    "configured": bool(provider_config["api_key"]),
                    "base_url": provider_config["base_url"],
                    "base_url_editable": bool(provider_meta.get("allow_custom_base_url")),
                    "model_options": config_state.get("options") if isinstance(config_state.get("options"), list) else [],
                    "model_fetch_error": str(config_state.get("error") or "").strip(),
                }
            )
        providers.append(
            {
                **provider_meta,
                "enabled": provider_settings["enabled"],
                "configured": provider_settings["configured"],
                "default_config_id": next(
                    (
                        item["id"]
                        for item in provider_settings["configs"]
                        if item.get("enabled") and item.get("api_key")
                    ),
                    provider_settings["configs"][0]["id"] if provider_settings["configs"] else "",
                ),
                "configs": config_payloads,
                "model_options": model_options["options"],
                "model_fetch_error": model_options["error"],
            }
        )
    return {
        "settings": normalized_settings,
        "providers": providers,
        "tools": list_available_tools(allow_write_tools=bool(normalized_settings.get("allow_write_tools"))),
        "notes": [
            "配置会保存在本地 SQLite 的 system_settings 表中。",
            "固定厂商的网关地址、请求路径和附加参数均写死在代码中；通用 OpenAI 仅需额外填写 Base URL。",
            "提示词插件配置和模型 API Key 配置相互独立；多个提示词插件会共享同一批模型配置。",
            "默认仅开放只读工具；如需发消息、改标签等写操作，请在设置中显式启用。",
        ],
    }


def list_available_tools(*, allow_write_tools: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "name": definition["name"],
            "description": definition["description"],
            "read_only": definition["read_only"],
        }
        for definition in get_tool_registry().values()
        if allow_write_tools or definition.get("read_only", True)
    ]


def get_tool_schemas(*, allow_write_tools: bool = True) -> list[dict[str, Any]]:
    return [
        definition["schema"]
        for definition in get_tool_registry().values()
        if allow_write_tools or definition.get("read_only", True)
    ]


def is_write_tool(tool_name: str) -> bool:
    definition = get_tool_registry().get(str(tool_name or "").strip())
    if not isinstance(definition, dict):
        return True
    return not bool(definition.get("read_only", True))

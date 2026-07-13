"""OpenAI-compatible provider HTTP adapters."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib import error, request

from .openai_messages import (
    _normalize_message_content,
    _normalize_message_image_items,
    _normalize_openai_request_messages,
    _normalize_reasoning_content,
)
from .constants import (
    DEFAULT_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_RETRY_COUNT,
    DEFAULT_PROVIDER_RETRY_DELAY_SECONDS,
    MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    PROVIDER_CATALOG,
    RETRYABLE_PROVIDER_STATUS_CODES,
)

def _normalize_provider_base_url(value: Any, default: str) -> str:
    normalized = str(value or default).strip()
    return normalized.rstrip("/") or default


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, numeric))


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, numeric))


def _normalize_provider_request_timeout(value: Any, default: float = DEFAULT_PROVIDER_REQUEST_TIMEOUT_SECONDS) -> float:
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError):
        return default
    if timeout_seconds <= 0:
        return default
    return min(MAX_PROVIDER_REQUEST_TIMEOUT_SECONDS, max(1.0, timeout_seconds))


def _is_timeout_reason(reason: Any) -> bool:
    if isinstance(reason, TimeoutError):
        return True
    normalized_reason = str(reason or "").strip().lower()
    return bool(normalized_reason) and ("timed out" in normalized_reason or "timeout" in normalized_reason)


def _build_default_provider_config(provider_key: str, provider_meta: dict[str, Any], index: int = 1) -> dict[str, Any]:
    return {
        "id": f"{provider_key}-config-{index}",
        "name": f"{provider_meta['label']} 配置 {index}",
        "enabled": False,
        "api_key": "",
        "base_url": provider_meta["default_base_url"],
    }


def _normalize_provider_config_entries(provider_key: str, provider_meta: dict[str, Any], raw_provider: dict[str, Any]) -> list[dict[str, Any]]:
    raw_configs = raw_provider.get("configs") if isinstance(raw_provider.get("configs"), list) else None
    normalized_configs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def append_config(item: dict[str, Any], index: int) -> None:
        default_item = _build_default_provider_config(provider_key, provider_meta, index)
        normalized_id = str(item.get("id") or default_item["id"]).strip() or default_item["id"]
        if normalized_id in seen_ids:
            normalized_id = f"{normalized_id}-{index}"
        seen_ids.add(normalized_id)
        api_key = str(item.get("api_key") or "").strip()
        enabled_raw = item.get("enabled")
        enabled = bool(enabled_raw) if enabled_raw is not None else bool(api_key)
        normalized_configs.append(
            {
                "id": normalized_id,
                "name": str(item.get("name") or default_item["name"]).strip() or default_item["name"],
                "enabled": enabled,
                "api_key": api_key,
                "base_url": _normalize_provider_base_url(
                    item.get("base_url"),
                    provider_meta["default_base_url"],
                ) if provider_meta.get("allow_custom_base_url") else provider_meta["default_base_url"],
            }
        )

    if raw_configs is not None:
        for index, raw_config in enumerate(raw_configs, start=1):
            if not isinstance(raw_config, dict):
                continue
            append_config(raw_config, index)
    elif any(key in raw_provider for key in {"enabled", "api_key", "base_url", "id", "name"}):
        append_config(
            {
                "id": raw_provider.get("id") or f"{provider_key}-config-1",
                "name": raw_provider.get("name") or f"{provider_meta['label']} 默认配置",
                "enabled": raw_provider.get("enabled"),
                "api_key": raw_provider.get("api_key"),
                "base_url": raw_provider.get("base_url"),
            },
            1,
        )

    return normalized_configs


def _get_provider_runtime_base_url(provider_key: str, provider_config: dict[str, Any]) -> str:
    provider_meta = PROVIDER_CATALOG[provider_key]
    if provider_meta.get("allow_custom_base_url"):
        return _normalize_provider_base_url(provider_config.get("base_url"), provider_meta["default_base_url"])
    return provider_meta["default_base_url"]


def _build_provider_request_headers(provider_key: str, api_key: str) -> dict[str, str]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    custom_headers = provider_meta.get("custom_headers") if isinstance(provider_meta.get("custom_headers"), dict) else {}
    for header_key, header_value in custom_headers.items():
        normalized_header_key = str(header_key or "").strip()
        if normalized_header_key:
            headers[normalized_header_key] = str(header_value or "")
    return headers


def _merge_provider_extra_body(provider_key: str, request_payload: dict[str, Any]) -> dict[str, Any]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    extra_body = provider_meta.get("extra_body") if isinstance(provider_meta.get("extra_body"), dict) else {}
    return {**request_payload, **extra_body}


def _resolve_provider_runtime_config(settings: dict[str, Any], provider_key: str, provider_config_id: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    provider_settings = settings.get("providers", {}).get(provider_key) if isinstance(settings.get("providers"), dict) else {}
    configs = provider_settings.get("configs") if isinstance(provider_settings.get("configs"), list) else []
    normalized_config_id = str(provider_config_id or "").strip()
    selected_config = next((item for item in configs if str(item.get("id") or "") == normalized_config_id), None)
    if selected_config is None:
        selected_config = next((item for item in configs if item.get("enabled") and item.get("api_key")), None)
    if selected_config is None:
        selected_config = next((item for item in configs if item.get("api_key")), None)
    if selected_config is None:
        raise RuntimeError("当前 AI 厂商还没有可用的 API Key 配置")
    return provider_meta, selected_config

def _build_provider_url(base_url: str, chat_path: str) -> str:
    normalized_path = str(chat_path or "/chat/completions").strip() or "/chat/completions"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    return f"{base_url.rstrip('/')}{normalized_path}"


def _request_provider_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float = DEFAULT_PROVIDER_REQUEST_TIMEOUT_SECONDS,
    retry_count: int = DEFAULT_PROVIDER_RETRY_COUNT,
    retry_delay_seconds: float = DEFAULT_PROVIDER_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    request_timeout = _normalize_provider_request_timeout(timeout)
    max_retries = _clamp_int(retry_count, DEFAULT_PROVIDER_RETRY_COUNT, 0, 3)
    retry_delay = _clamp_float(retry_delay_seconds, DEFAULT_PROVIDER_RETRY_DELAY_SECONDS, 0.0, 10.0)
    request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(max_retries + 1):
        req = request.Request(url, data=request_body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=request_timeout) as response:
                response_text = response.read().decode("utf-8")
            break
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code in RETRYABLE_PROVIDER_STATUS_CODES and attempt < max_retries:
                if retry_delay > 0:
                    time.sleep(retry_delay)
                continue
            raise RuntimeError(f"AI 接口调用失败，HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            if _is_timeout_reason(exc.reason):
                if attempt < max_retries:
                    if retry_delay > 0:
                        time.sleep(retry_delay)
                    continue
                raise RuntimeError(f"AI 接口调用超时({request_timeout:.1f}s)") from exc
            raise RuntimeError(f"AI 接口调用失败: {exc.reason}") from exc
        except TimeoutError as exc:
            if attempt < max_retries:
                if retry_delay > 0:
                    time.sleep(retry_delay)
                continue
            raise RuntimeError(f"AI 接口调用超时({request_timeout:.1f}s)") from exc

    try:
        payload_json = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AI 接口返回了非 JSON 响应: {response_text}") from exc

    if isinstance(payload_json, dict) and payload_json.get("error"):
        raise RuntimeError(f"AI 接口返回错误: {payload_json['error']}")
    if not isinstance(payload_json, dict):
        raise RuntimeError("AI 接口返回格式异常")
    return payload_json

def _merge_model_names(*values: Any) -> list[str]:
    items: list[str] = []
    for value in values:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized and normalized not in items:
                items.append(normalized)
            continue
        for item in value if isinstance(value, list) else []:
            normalized = str(item or "").strip()
            if normalized and normalized not in items:
                items.append(normalized)
    return items


def _parse_provider_model_names(payload: Any) -> list[str]:
    container = payload if isinstance(payload, dict) else {}
    raw_items = container.get("data") if isinstance(container.get("data"), list) else container.get("models")
    items = raw_items if isinstance(raw_items, list) else []
    model_names: list[str] = []
    for item in items:
        if isinstance(item, dict):
            candidate = item.get("id") or item.get("model") or item.get("name")
        else:
            candidate = item
        normalized = str(candidate or "").strip()
        if normalized and normalized not in model_names:
            model_names.append(normalized)
    return model_names


def _request_provider_models(
    base_url: str,
    api_key: str,
    headers: dict[str, str] | None = None,
    models_path: str = "/models",
    timeout: float = 30.0,
) -> list[str]:
    url = _build_provider_url(base_url, models_path)
    req = request.Request(
        url,
        headers=dict(headers or _build_provider_request_headers("openai", api_key)),
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            response_text = response.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(f"读取模型列表失败: {exc}") from exc
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"模型列表返回了非 JSON 响应: {response_text}") from exc
    model_names = _parse_provider_model_names(payload)
    if not model_names:
        raise RuntimeError("模型列表为空")
    return model_names


async def _load_provider_config_model_options(provider_key: str, provider_config: dict[str, Any]) -> dict[str, Any]:
    provider_meta = PROVIDER_CATALOG[provider_key]
    default_model = provider_meta["default_model"]
    model_names: list[str] = []
    error_message = ""
    if provider_config.get("api_key"):
        try:
            model_names = await asyncio.to_thread(
                _request_provider_models,
                _get_provider_runtime_base_url(provider_key, provider_config),
                str(provider_config.get("api_key") or ""),
                _build_provider_request_headers(provider_key, str(provider_config.get("api_key") or "")),
                provider_meta.get("models_path") or "/models",
            )
        except Exception as exc:
            error_message = str(exc)
    merged_names = _merge_model_names(model_names, default_model if provider_config.get("api_key") else [])
    option_items = [
        {
            "label": f"{provider_config['name']} / {model_name}",
            "value": model_name,
            "config_id": provider_config["id"],
            "config_name": provider_config["name"],
        }
        for model_name in merged_names
    ]
    return {
        "config_id": provider_config["id"],
        "config_name": provider_config["name"],
        "options": option_items,
        "error": error_message,
    }


async def _load_provider_model_options(provider_key: str, provider_settings: dict[str, Any]) -> dict[str, Any]:
    configs = provider_settings.get("configs") if isinstance(provider_settings.get("configs"), list) else []
    model_results = await asyncio.gather(
        *[_load_provider_config_model_options(provider_key, provider_config) for provider_config in configs]
    ) if configs else []

    options: list[dict[str, Any]] = []
    config_payloads: dict[str, dict[str, Any]] = {}
    error_messages: list[str] = []
    for result in model_results:
        config_id = str(result.get("config_id") or "")
        config_payloads[config_id] = {
            "options": result.get("options") if isinstance(result.get("options"), list) else [],
            "error": str(result.get("error") or "").strip(),
        }
        options.extend(config_payloads[config_id]["options"])
        if config_payloads[config_id]["error"]:
            error_messages.append(f"{result.get('config_name')}: {config_payloads[config_id]['error']}")
    return {
        "options": options,
        "error": "；".join(error_messages),
        "configs": config_payloads,
    }


def _build_model_option_items(model_names: list[str]) -> list[dict[str, str]]:
    return [
        {
            "label": model_name,
            "value": model_name,
            "search_text": model_name,
        }
        for model_name in model_names
    ]


async def load_openai_compatible_model_options(
    base_url: str,
    api_key: str,
    current_model: str | None = None,
) -> dict[str, Any]:
    normalized_base_url = _normalize_provider_base_url(base_url, PROVIDER_CATALOG["openai"]["default_base_url"])
    normalized_api_key = str(api_key or "").strip()
    fallback_models: list[str] = []
    normalized_current_model = str(current_model or "").strip()
    if normalized_current_model:
        fallback_models.append(normalized_current_model)

    model_names = _merge_model_names([], fallback_models)
    error_message = ""
    if normalized_api_key:
        try:
            loaded_model_names = await asyncio.to_thread(
                _request_provider_models,
                normalized_base_url,
                normalized_api_key,
                _build_provider_request_headers("openai", normalized_api_key),
                PROVIDER_CATALOG["openai"].get("models_path") or "/models",
            )
            model_names = _merge_model_names(loaded_model_names, fallback_models)
        except Exception as exc:
            error_message = str(exc)

    return {
        "base_url": normalized_base_url,
        "options": _build_model_option_items(model_names),
        "error": error_message,
    }


async def run_openai_compatible_chat_completion(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]] | None,
    system_prompt: str = "",
    temperature: float | None = None,
) -> dict[str, Any]:
    normalized_api_key = str(api_key or "").strip()
    if not normalized_api_key:
        raise RuntimeError("未配置 API Key")

    normalized_base_url = _normalize_provider_base_url(base_url, PROVIDER_CATALOG["openai"]["default_base_url"])
    normalized_model = str(model or "").strip() or PROVIDER_CATALOG["openai"]["default_model"]
    normalized_messages = _normalize_openai_request_messages(messages)
    if not normalized_messages:
        raise RuntimeError("缺少可发送给模型的消息")

    request_messages: list[dict[str, Any]] = []
    normalized_system_prompt = str(system_prompt or "").strip()
    if normalized_system_prompt:
        request_messages.append({"role": "system", "content": normalized_system_prompt})
    request_messages.extend(normalized_messages)

    request_payload = {
        "model": normalized_model,
        "messages": request_messages,
        "stream": False,
    }
    if temperature is not None:
        request_payload["temperature"] = _clamp_float(temperature, 0.2, 0.0, 1.5)

    response_payload = await asyncio.to_thread(
        _request_provider_json,
        _build_provider_url(normalized_base_url, PROVIDER_CATALOG["openai"]["chat_path"]),
        request_payload,
        _build_provider_request_headers("openai", normalized_api_key),
    )
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"AI 接口返回异常：{response_payload}")

    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    assistant_content = _normalize_message_content(message.get("content"))
    assistant_images = _normalize_message_image_items(message.get("content"))
    if not assistant_images:
        assistant_images = _normalize_message_image_items(message.get("images"))
    if not assistant_images:
        assistant_images = _normalize_message_image_items(message.get("image"))
    if not assistant_images:
        assistant_images = _normalize_message_image_items(message.get("image_url"))
    assistant_reasoning_content = _normalize_reasoning_content(message.get("reasoning_content"))
    if not assistant_content and not assistant_images:
        raise RuntimeError("模型未返回可展示的回复")

    return {
        "content": assistant_content,
        "image_items": assistant_images,
        "reasoning_content": assistant_reasoning_content,
        "model": normalized_model,
        "base_url": normalized_base_url,
    }

"""Plugin metadata and scope normalization helpers."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from types import ModuleType
from typing import Any, Callable

from loguru import logger

from config import PLUGIN_PACKAGE, normalize_plugin_module_name
from message import MessageEvent
from message_types import MESSAGE_FILTER_ALIASES
from plugin_base import PluginContext, PluginExecutionContext, PluginLogger, PluginResult, PluginStateStore
from plugins._global_blacklist import (
    BLACKLIST_MEMBERS_NAMESPACE,
    BLACKLIST_PLUGIN_MODULE,
    BLACKLIST_PLUGIN_NAME,
    resolve_blacklist_subject_wxid,
)
from utils.normalize import normalize_text as _normalize_text
from utils.normalize import normalize_wxpid as _normalize_wxpid

from .constants import (
    FRIEND_LABEL_CACHE_TTL_SECONDS,
    PLUGIN_DIR,
    PLUGIN_SCOPE_BIZ_MODE,
    PLUGIN_SCOPE_FRIEND_LABELS,
    PLUGIN_SCOPE_FRIEND_MODE,
    PLUGIN_SCOPE_ROOM_IDS,
    PLUGIN_SCOPE_ROOM_MODE,
    PYTHON_SDK_VERSION,
    SCOPE_TARGET_ALIASES,
)

@dataclass(slots=True)
class PluginSpec:
    module_name: str
    path: Path
    stem: str


def _normalize_event_filters(value: Any) -> tuple[str, ...]:
    raw_items = value if isinstance(value, list) else ([value] if value else [])
    normalized_items: list[str] = []
    for item in raw_items:
        normalized = str(item or "").strip().lower()
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
    return tuple(normalized_items)


def _normalize_config_schema(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [deepcopy(item) for item in value if isinstance(item, dict)]


def _normalize_scope_targets(value: Any) -> tuple[str, ...]:
    raw_items = value if isinstance(value, (list, tuple, set)) else ([value] if value else [])
    normalized_items: list[str] = []
    for item in raw_items:
        normalized = SCOPE_TARGET_ALIASES.get(str(item or "").strip().lower(), "")
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
    return tuple(normalized_items)


def _normalize_scope_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.split(",")
    elif value in (None, ""):
        raw_items = []
    else:
        raw_items = [value]

    normalized_items: list[str] = []
    for item in raw_items:
        normalized = str(item or "").strip()
        if normalized and normalized not in normalized_items:
            normalized_items.append(normalized)
    return tuple(normalized_items)


def _normalize_scope_mode(value: Any, *, allow_selected: bool = True, default: str = "all") -> str:
    normalized = str(value or "").strip().lower()
    allowed = {"all", "none"}
    if allow_selected:
        allowed.add("selected")
    return normalized if normalized in allowed else default


def _is_biz_conversation_wxid(wxid: str) -> bool:
    normalized = str(wxid or "").strip().lower()
    return bool(normalized) and normalized.startswith("gh_")


def _resolve_login_account_wxid(accounts: list[dict[str, Any]] | None, wxpid: int | None) -> str:
    if wxpid is None:
        return ""
    for item in accounts if isinstance(accounts, list) else []:
        if not isinstance(item, dict):
            continue
        if _normalize_wxpid(item.get("wxpid") or item.get("pid")) != wxpid:
            continue
        wxid = _normalize_text(item.get("wxid"))
        if wxid:
            return wxid
    return ""


def _resolve_module_attr(module: ModuleType, *names: str, default: Any = None) -> Any:
    for name in names:
        if hasattr(module, name):
            return getattr(module, name)
    return default


def _resolve_schedule(module: ModuleType, capabilities: dict[str, Any]) -> dict[str, Any]:
    if not capabilities.get("tick_hook"):
        return {}

    raw_schedule = _resolve_module_attr(module, "schedule", default={})
    schedule = dict(raw_schedule) if isinstance(raw_schedule, dict) else {}
    interval_field = str(
        schedule.get("interval_field")
        or _resolve_module_attr(module, "tick_interval_field", "tickIntervalField", default="interval_seconds")
        or "interval_seconds"
    ).strip() or "interval_seconds"
    default_interval_value = schedule.get(
        "default_interval_seconds",
        _resolve_module_attr(module, "tick_interval_seconds", "tickIntervalSeconds", default=None),
    )
    try:
        default_interval_seconds = float(default_interval_value) if default_interval_value is not None else None
    except (TypeError, ValueError):
        default_interval_seconds = None
    return {
        "interval_field": interval_field,
        "default_interval_seconds": default_interval_seconds,
    }


def _resolve_bool_flag(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _describe_python_module(module: ModuleType, spec: PluginSpec) -> dict[str, Any]:
    declared_category = str(_resolve_module_attr(module, "category", default="") or "").strip().lower()
    raw_message_dependent = _resolve_module_attr(module, "message_dependent", "messageDependent", default=None)
    if isinstance(raw_message_dependent, bool):
        message_dependent = raw_message_dependent
    else:
        message_dependent = declared_category not in {"functional", "utility"}
    category = "message" if message_dependent else "functional"
    event_filters = _normalize_event_filters(_resolve_module_attr(module, "event_filters", "eventFilters", "eventFilter", default=[]))
    config_schema = _normalize_config_schema(_resolve_module_attr(module, "config_schema", "configSchema", default=[]))
    scope_targets = _normalize_scope_targets(
        _resolve_module_attr(module, "scope_targets", "scopeTargets", "supported_scopes", "supportedScopes", default=[])
    )
    capabilities = {
        "logger": True,
        "persistent_state": True,
        "hot_reload": True,
        "message_hook": callable(_resolve_module_attr(module, "handle_message", "handleMessage", default=None)),
        "execute_hook": callable(_resolve_module_attr(module, "execute", default=None)),
        "startup_hook": callable(_resolve_module_attr(module, "startup", default=None)),
        "shutdown_hook": callable(_resolve_module_attr(module, "shutdown", default=None)),
        "hot_reload_hook": callable(_resolve_module_attr(module, "on_hot_reload", "onHotReload", default=None)),
        "tick_hook": callable(_resolve_module_attr(module, "tick", default=None)),
    }
    return {
        "name": str(_resolve_module_attr(module, "name", default=spec.stem) or spec.stem),
        "description": str(_resolve_module_attr(module, "description", default="") or ""),
        "runtime": "python",
        "sdk_version": str(_resolve_module_attr(module, "sdk_version", "sdkVersion", default=PYTHON_SDK_VERSION) or PYTHON_SDK_VERSION),
        "category": category,
        "message_dependent": message_dependent,
        "event_filters": list(event_filters),
        "capabilities": capabilities,
        "config_schema": config_schema,
        "scope_targets": list(scope_targets),
        "schedule": _resolve_schedule(module, capabilities),
        "direct_execute": _resolve_bool_flag(
            _resolve_module_attr(module, "direct_execute", "directExecute", default=False),
            default=False,
        ),
        "message_summary": _resolve_bool_flag(
            _resolve_module_attr(module, "message_summary", "messageSummary", default=False),
            default=False,
        ),
    }


async def _await_if_needed(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value

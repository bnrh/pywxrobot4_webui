"""Python plugin wrapper."""

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

from core.config import PLUGIN_PACKAGE, normalize_plugin_module_name
from messaging.event import MessageEvent
from messaging.types import MESSAGE_FILTER_ALIASES
from manager.plugin_base import PluginContext, PluginExecutionContext, PluginLogger, PluginResult, PluginStateStore
from plugins._global_blacklist import (
    BLACKLIST_MEMBERS_NAMESPACE,
    BLACKLIST_PLUGIN_MODULE,
    BLACKLIST_PLUGIN_NAME,
    resolve_blacklist_subject_wxid,
)

from .constants import (
    FRIEND_LABEL_CACHE_TTL_SECONDS,
    PLUGIN_SCOPE_BIZ_MODE,
    PLUGIN_SCOPE_FRIEND_LABELS,
    PLUGIN_SCOPE_FRIEND_MODE,
    PLUGIN_SCOPE_ROOM_IDS,
    PLUGIN_SCOPE_ROOM_MODE,
    PYTHON_SDK_VERSION,
)
from .normalize import (
    PluginSpec,
    _await_if_needed,
    _describe_python_module,
    _is_biz_conversation_wxid,
    _normalize_config_schema,
    _normalize_event_filters,
    _normalize_scope_mode,
    _normalize_scope_targets,
    _normalize_scope_values,
    _normalize_text,
    _normalize_wxpid,
    _resolve_login_account_wxid,
    _resolve_module_attr,
    _resolve_schedule,
)

class PythonPlugin:
    runtime = "python"

    def __init__(
        self,
        spec: PluginSpec,
        config: dict[str, Any] | None,
        module: ModuleType,
        metadata: dict[str, Any],
        plugin_log_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.spec = spec
        self.module_name = spec.module_name
        self.config = dict(config or {})
        self._module = module
        self._plugin_log_sink = plugin_log_sink
        self._state = PluginStateStore(self.module_name)
        self.name = spec.stem
        self.description = ""
        self.sdk_version = PYTHON_SDK_VERSION
        self.capabilities: dict[str, Any] = {}
        self.category = "message"
        self.message_dependent = True
        self.event_filters: tuple[str, ...] = ()
        self.config_schema: list[dict[str, Any]] = []
        self.scope_targets: tuple[str, ...] = ()
        self.schedule: dict[str, Any] = {}
        self._logger = PluginLogger(self.module_name, self.name, self._plugin_log_sink)
        self._apply_metadata(metadata)
        self._loaded_revision = self._current_revision()

    def _current_revision(self) -> int:
        # 冻结打包后可能没有独立 .py 文件，用 0 表示不可热重载源文件
        if not self.spec.path.exists():
            return 0
        return self.spec.path.stat().st_mtime_ns

    def _apply_metadata(self, metadata: dict[str, Any]) -> None:
        self.name = str(metadata.get("name") or self.spec.stem or self.module_name)
        self.description = str(metadata.get("description") or "")
        self.sdk_version = str(metadata.get("sdk_version") or PYTHON_SDK_VERSION)
        self.category = str(metadata.get("category") or "message").strip().lower() or "message"
        self.message_dependent = bool(metadata.get("message_dependent", True))
        self.event_filters = tuple(_normalize_event_filters(metadata.get("event_filters") or []))
        self.capabilities = dict(metadata.get("capabilities") or {})
        self.config_schema = _normalize_config_schema(metadata.get("config_schema") or [])
        self.scope_targets = _normalize_scope_targets(metadata.get("scope_targets") or [])
        self.schedule = dict(metadata.get("schedule") or {})
        self._logger = PluginLogger(self.module_name, self.name, self._plugin_log_sink)

    @staticmethod
    def _preview_text(value: Any, limit: int = 120) -> str:
        normalized = " ".join(str(value or "").split())
        if not normalized:
            return ""
        return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."

    @classmethod
    def _summarize_log_value(cls, value: Any, depth: int = 0) -> Any:
        if value in (None, "", [], {}):
            return value
        if isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return cls._preview_text(value, 200)
        if isinstance(value, dict):
            if depth >= 1:
                keys = [str(key) for key in list(value.keys())[:10]]
                if len(value) > 10:
                    keys.append(f"...({len(value) - 10} more)")
                return {"type": "dict", "size": len(value), "keys": keys}
            summary: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 10:
                    summary["__truncated_items__"] = len(value) - 10
                    break
                summary[str(key)] = cls._summarize_log_value(item, depth + 1)
            return summary
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            summary = [cls._summarize_log_value(item, depth + 1) for item in items[:5]]
            if len(items) > 5:
                summary.append(f"...({len(items) - 5} more)")
            return summary
        return cls._preview_text(value, 200)

    def _build_plugin_log_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "module": self.module_name,
            "plugin": self.name,
            "category": self.category,
            "message_dependent": self.message_dependent,
            "event_filters": list(self.event_filters),
            "scope_targets": list(self.scope_targets),
            "config_keys": sorted(str(key) for key in self.config.keys()),
        }
        if self.supports_tick:
            data["tick_interval_seconds"] = self.get_tick_interval_seconds()
        description = self._preview_text(self.description, 160)
        if description:
            data["description"] = description
        return data

    def _build_event_log_data(self, event: MessageEvent) -> dict[str, Any]:
        return {
            "msgid": event.normalized_msgid,
            "wxpid": event.normalized_wxpid,
            "conversation_wxid": event.conversation_wxid,
            "sender_wxid": event.sender_wxid,
            "current_account_wxid": event.current_account_wxid,
            "is_group_message": event.is_group_message,
            "is_self_message": event.is_self_message,
            "msg_type": event.normalized_msg_type,
            "local_type": event.normalized_local_type,
            "content_preview": self._preview_text(event.normalized_content, 160),
        }

    def _build_result_log_data(self, result: PluginResult) -> dict[str, Any]:
        data: dict[str, Any] = {
            "handled": result.handled,
            "stop_processing": result.stop_processing,
        }
        detail = self._preview_text(result.detail, 200)
        if detail:
            data["detail"] = detail
        if result.data:
            data["data"] = self._summarize_log_value(result.data)
            data["data_keys"] = sorted(str(key) for key in result.data.keys())
        return data

    @staticmethod
    def _build_error_log_data(exc: Exception) -> dict[str, Any]:
        return {
            "error_type": exc.__class__.__name__,
            "error": str(exc),
        }

    def log_scope_skip(self, event: MessageEvent, reason: str) -> None:
        message_logger = self._logger.scope("message")
        payload = self._build_event_log_data(event)
        payload["reason"] = reason
        message_logger.info("消息命中过滤器，但未命中插件作用范围", payload)

    def _matches_event_filter(self, event: MessageEvent, event_filter: str) -> bool:
        normalized_filter = str(event_filter or "").strip().lower()
        if not normalized_filter:
            return True
        if normalized_filter == "group":
            return event.is_group_message
        if normalized_filter in {"direct", "private", "single"}:
            return not event.is_group_message
        if normalized_filter == "image":
            return event.is_image
        if normalized_filter in MESSAGE_FILTER_ALIASES:
            expected_type = MESSAGE_FILTER_ALIASES[normalized_filter]
            return event.normalized_msg_type == expected_type or event.normalized_local_type == expected_type
        try:
            expected_type = int(normalized_filter, 16) if normalized_filter.startswith("0x") else int(normalized_filter)
        except ValueError:
            return False
        return event.normalized_msg_type == expected_type or event.normalized_local_type == expected_type

    def should_handle_message(self, event: MessageEvent) -> bool:
        if not self.message_dependent:
            return False
        if not self.event_filters:
            return True
        return any(self._matches_event_filter(event, event_filter) for event_filter in self.event_filters)

    def _build_hot_reload_info(
        self,
        *,
        changed: bool,
        reason: str,
        current_revision: int,
        previous_revision: int | None,
    ) -> dict[str, Any]:
        return {
            "enabled": True,
            "changed": changed,
            "reason": reason,
            "current_revision": current_revision,
            "previous_revision": previous_revision,
        }

    def _build_execution_context(self, context: PluginContext, hot_reload: dict[str, Any] | None = None) -> PluginExecutionContext:
        return PluginExecutionContext(
            settings=context.settings,
            api=context.api_client,
            config=dict(self.config),
            logger=self._logger,
            state=self._state,
            plugin_name=self.name,
            plugin_module=self.module_name,
            hot_reload=deepcopy(hot_reload) if hot_reload else None,
            login_account_cache_getter=context.login_account_cache_getter,
            login_account_cache_refresher=context.login_account_cache_refresher,
            login_account_serializer=context.login_account_serializer,
        )

    def _resolve_hook(self, *names: str) -> Callable[..., Any] | None:
        for name in names:
            candidate = getattr(self._module, name, None)
            if callable(candidate):
                return candidate
        return None

    async def _call_hook(
        self,
        hook_names: tuple[str, ...],
        context: PluginContext,
        *args: Any,
        hot_reload: dict[str, Any] | None = None,
    ) -> Any:
        hook = self._resolve_hook(*hook_names)
        if hook is None:
            return None
        execution_context = self._build_execution_context(context, hot_reload)
        return await _await_if_needed(hook(*args, execution_context))

    async def startup(self, context: PluginContext) -> None:
        lifecycle_logger = self._logger.scope("lifecycle")
        lifecycle_payload = self._build_plugin_log_data()
        lifecycle_payload["hook"] = "startup"
        try:
            await self._call_hook(
                ("startup",),
                context,
                hot_reload=self._build_hot_reload_info(
                    changed=False,
                    reason="startup",
                    current_revision=self._loaded_revision,
                    previous_revision=self._loaded_revision,
                ),
            )
        except Exception as exc:
            lifecycle_logger.error("插件启动失败", {**lifecycle_payload, **self._build_error_log_data(exc)})
            raise
        lifecycle_logger.info("插件启动完成", lifecycle_payload)

    async def shutdown(self, context: PluginContext) -> None:
        lifecycle_logger = self._logger.scope("lifecycle")
        lifecycle_payload = self._build_plugin_log_data()
        lifecycle_payload["hook"] = "shutdown"
        try:
            await self._call_hook(
                ("shutdown",),
                context,
                hot_reload=self._build_hot_reload_info(
                    changed=False,
                    reason="shutdown",
                    current_revision=self._loaded_revision,
                    previous_revision=self._loaded_revision,
                ),
            )
        except Exception as exc:
            lifecycle_logger.error("插件关闭失败", {**lifecycle_payload, **self._build_error_log_data(exc)})
            raise
        lifecycle_logger.info("插件关闭完成", lifecycle_payload)

    async def _refresh_if_needed(self, context: PluginContext) -> dict[str, Any]:
        current_revision = self._current_revision()
        hot_reload = self._build_hot_reload_info(
            changed=current_revision != self._loaded_revision,
            reason="file-changed" if current_revision != self._loaded_revision else "steady",
            current_revision=current_revision,
            previous_revision=self._loaded_revision,
        )
        if current_revision == self._loaded_revision:
            return hot_reload

        previous_name = self.name
        previous_description = self.description
        self._module = PluginManager._load_python_module(self.spec, force_reload=True)
        metadata = _describe_python_module(self._module, self.spec)
        self._apply_metadata(metadata)
        hot_reload.update(
            {
                "previous_name": previous_name,
                "previous_description": previous_description,
            }
        )
        hot_reload_logger = self._logger.scope("hot-reload")
        hot_reload_payload = {
            "previous_name": previous_name,
            "previous_description": self._preview_text(previous_description, 160),
            "current_name": self.name,
            "current_description": self._preview_text(self.description, 160),
            "current_revision": current_revision,
            "previous_revision": self._loaded_revision,
        }
        try:
            await self._call_hook(("on_hot_reload", "onHotReload"), context, hot_reload, hot_reload=hot_reload)
        except Exception as exc:
            hot_reload_logger.error("插件热重载失败", {**hot_reload_payload, **self._build_error_log_data(exc)})
            raise
        hot_reload_logger.info("插件已热重载", hot_reload_payload)
        logger.info("Python 插件已热重载: {}", self.module_name)
        self._loaded_revision = current_revision
        return hot_reload

    @staticmethod
    def _normalize_result(result: Any) -> PluginResult:
        if isinstance(result, PluginResult):
            return result
        if result is None:
            return PluginResult.skipped("")
        if isinstance(result, dict):
            return PluginResult(
                handled=bool(result.get("handled")),
                stop_processing=bool(result.get("stop_processing") or result.get("stopProcessing")),
                detail=str(result.get("detail") or ""),
                data=result.get("data") if isinstance(result.get("data"), dict) else {},
            )
        return PluginResult.skipped(str(result))

    async def handle_message(self, event: MessageEvent, context: PluginContext) -> PluginResult:
        hot_reload = await self._refresh_if_needed(context)
        message_logger = self._logger.scope("message")
        event_payload = self._build_event_log_data(event)
        event_payload["hot_reload_changed"] = bool(hot_reload.get("changed"))
        message_logger.debug("插件开始处理消息", event_payload)
        try:
            result = await self._call_hook(("handle_message", "handleMessage"), context, event, hot_reload=hot_reload)
        except Exception as exc:
            message_logger.error("插件处理消息失败", {**event_payload, **self._build_error_log_data(exc)})
            raise
        normalized_result = self._normalize_result(result)
        if normalized_result.handled or normalized_result.stop_processing or normalized_result.detail:
            message_logger.info("插件消息处理完成", {**event_payload, **self._build_result_log_data(normalized_result)})
        else:
            message_logger.debug("插件消息处理完成", {**event_payload, **self._build_result_log_data(normalized_result)})
        return normalized_result

    @property
    def supports_tick(self) -> bool:
        return bool(self.capabilities.get("tick_hook"))

    def get_tick_interval_seconds(self) -> float:
        interval_field = str(self.schedule.get("interval_field") or "interval_seconds").strip() or "interval_seconds"
        configured_value = self.config.get(interval_field)
        if configured_value not in (None, ""):
            try:
                return max(0.0, float(configured_value))
            except (TypeError, ValueError):
                return 0.0
        default_value = self.schedule.get("default_interval_seconds")
        try:
            return max(0.0, float(default_value)) if default_value is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    async def tick(self, context: PluginContext) -> PluginResult:
        hot_reload = await self._refresh_if_needed(context)
        tick_logger = self._logger.scope("tick")
        tick_payload = self._build_plugin_log_data()
        tick_payload["hot_reload_changed"] = bool(hot_reload.get("changed"))
        try:
            result = await self._call_hook(("tick",), context, hot_reload=hot_reload)
        except Exception as exc:
            tick_logger.error("插件周期执行失败", {**tick_payload, **self._build_error_log_data(exc)})
            raise
        normalized_result = self._normalize_result(result)
        if normalized_result.handled or normalized_result.detail or tick_payload["hot_reload_changed"]:
            tick_logger.info("插件周期执行完成", {**tick_payload, **self._build_result_log_data(normalized_result)})
        return normalized_result

    async def execute(self, context: PluginContext) -> PluginResult:
        hot_reload = self._build_hot_reload_info(
            changed=False,
            reason="manual-execute",
            current_revision=self._loaded_revision,
            previous_revision=self._loaded_revision,
        )
        execute_logger = self._logger.scope("manual")
        execute_payload = self._build_plugin_log_data()
        if self.capabilities.get("execute_hook"):
            execute_mode = "execute_hook"
        elif self.capabilities.get("startup_hook"):
            execute_mode = "startup_hook"
        elif self.supports_tick:
            execute_mode = "tick_hook"
        else:
            execute_mode = "unsupported"
        execute_payload["execute_mode"] = execute_mode
        execute_logger.info("插件开始手动执行", execute_payload)
        try:
            if self.capabilities.get("execute_hook"):
                result = await self._call_hook(("execute",), context, hot_reload=hot_reload)
                normalized_result = self._normalize_result(result)
            elif self.capabilities.get("startup_hook"):
                await self._call_hook(("startup",), context, hot_reload=hot_reload)
                normalized_result = PluginResult.handled_result("插件执行完成")
            elif self.supports_tick:
                normalized_result = await self.tick(context)
            else:
                normalized_result = PluginResult.skipped("插件未提供可执行入口")
        except Exception as exc:
            execute_logger.error("插件手动执行失败", {**execute_payload, **self._build_error_log_data(exc)})
            raise
        execute_logger.info("插件手动执行完成", {**execute_payload, **self._build_result_log_data(normalized_result)})
        return normalized_result

"""PluginManager — discovery, load, dispatch."""

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
from server.app_config import LEGACY_PLUGIN_ALIAS_MODULES, resolve_canonical_plugin_module

from .constants import (
    FRIEND_LABEL_CACHE_TTL_SECONDS,
    PLUGIN_DIR,
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
    _normalize_scope_mode,
    _normalize_scope_values,
    _normalize_text,
    _normalize_wxpid,
    _resolve_login_account_wxid,
    _resolve_module_attr,
)
from .python_plugin import PythonPlugin

class PluginManager:
    def __init__(
        self,
        context: PluginContext,
        module_names: list[str],
        plugin_settings: dict[str, dict],
        plugin_log_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.context = context
        self.module_names = module_names
        self.plugin_settings = plugin_settings
        self.plugin_log_sink = plugin_log_sink
        self._plugins: list[PythonPlugin] = []
        self._periodic_tasks: list[asyncio.Task] = []
        self._friend_label_cache: dict[int, tuple[float, dict[str, set[str]]]] = {}
        self._friend_label_locks: dict[int, asyncio.Lock] = {}
        self._blacklist_state = PluginStateStore(BLACKLIST_PLUGIN_MODULE, namespace=BLACKLIST_MEMBERS_NAMESPACE)

    @property
    def plugins(self) -> tuple[PythonPlugin, ...]:
        return tuple(self._plugins)

    @staticmethod
    def discover_plugin_modules() -> list[str]:
        specs = PluginManager._discover_plugin_specs()
        if not specs:
            return []
        return sorted(specs)

    @staticmethod
    def _discover_plugin_specs() -> dict[str, PluginSpec]:
        if not PLUGIN_DIR.exists():
            return {}
        specs: dict[str, PluginSpec] = {}
        for path in sorted(PLUGIN_DIR.glob("*.py")):
            if not path.is_file() or path.stem == "__init__" or path.stem.startswith("_"):
                continue
            module_name = f"{PLUGIN_PACKAGE}.{path.stem}"
            normalized_module_name = normalize_plugin_module_name(module_name)
            if normalized_module_name in LEGACY_PLUGIN_ALIAS_MODULES:
                continue
            specs[normalized_module_name] = PluginSpec(
                module_name=normalized_module_name,
                path=path,
                stem=path.stem,
            )
        return specs

    @classmethod
    def _resolve_plugin_spec(cls, module_name: str) -> PluginSpec:
        discovered = cls._discover_plugin_specs()
        normalized_module_name = resolve_canonical_plugin_module(module_name)
        spec = discovered.get(normalized_module_name)
        if spec is None:
            raise FileNotFoundError(f"未找到 Python 插件文件: {module_name}")
        return spec

    @staticmethod
    def _load_python_module(spec: PluginSpec, force_reload: bool = False) -> ModuleType:
        importlib.invalidate_caches()
        if force_reload and spec.module_name in sys.modules:
            return importlib.reload(sys.modules[spec.module_name])
        if spec.module_name in sys.modules:
            return sys.modules[spec.module_name]
        return importlib.import_module(spec.module_name)

    @classmethod
    def describe_plugin(cls, spec: PluginSpec, *, force_reload: bool = False) -> dict[str, Any]:
        module = cls._load_python_module(spec, force_reload=force_reload)
        return _describe_python_module(module, spec)

    @classmethod
    def _describe_python_plugin(cls, spec: PluginSpec, *, force_reload: bool = False) -> dict[str, Any]:
        return cls.describe_plugin(spec, force_reload=force_reload)

    def _resolve_plugin_config(self, module_name: str, plugin_name: str | None = None) -> dict[str, Any]:
        plugin_config = self.plugin_settings.get(module_name, {})
        if not plugin_config and plugin_name:
            plugin_config = self.plugin_settings.get(plugin_name, {})
        return plugin_config

    @classmethod
    def describe_modules(cls, module_names: list[str]) -> list[dict[str, Any]]:
        descriptions: list[dict[str, Any]] = []
        for module_name in module_names:
            try:
                spec = cls._resolve_plugin_spec(module_name)
                metadata = cls._describe_python_plugin(spec, force_reload=False)
                descriptions.append(
                    {
                        "module": module_name,
                        "name": metadata.get("name", module_name),
                        "description": metadata.get("description", ""),
                        "runtime": "python",
                        "sdk_version": metadata.get("sdk_version", PYTHON_SDK_VERSION),
                        "category": str(metadata.get("category") or "message"),
                        "message_dependent": bool(metadata.get("message_dependent", True)),
                        "event_filters": metadata.get("event_filters") if isinstance(metadata.get("event_filters"), list) else [],
                        "capabilities": metadata.get("capabilities") if isinstance(metadata.get("capabilities"), dict) else {},
                        "config_schema": metadata.get("config_schema") if isinstance(metadata.get("config_schema"), list) else [],
                        "scope_targets": metadata.get("scope_targets") if isinstance(metadata.get("scope_targets"), list) else [],
                        "direct_execute": bool(metadata.get("direct_execute", False)),
                        "message_summary": bool(metadata.get("message_summary", False)),
                        "loadable": True,
                        "error": "",
                    }
                )
            except Exception as exc:
                descriptions.append(
                    {
                        "module": module_name,
                        "name": module_name.rsplit(".", 1)[-1],
                        "description": "",
                        "runtime": "python",
                        "sdk_version": PYTHON_SDK_VERSION,
                        "category": "message",
                        "message_dependent": True,
                        "event_filters": [],
                        "capabilities": {},
                        "config_schema": [],
                        "scope_targets": [],
                        "direct_execute": False,
                        "message_summary": False,
                        "loadable": False,
                        "error": str(exc),
                    }
                )
        return descriptions

    @staticmethod
    def _wxpid_cache_key(wxpid: int | None) -> int:
        if wxpid in (None, ""):
            return -1
        try:
            return int(wxpid)
        except (TypeError, ValueError):
            return -1

    def _get_friend_label_lock(self, wxpid: int | None) -> asyncio.Lock:
        key = self._wxpid_cache_key(wxpid)
        lock = self._friend_label_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._friend_label_locks[key] = lock
        return lock

    async def _get_friend_labels_by_user(self, wxpid: int | None) -> dict[str, set[str]]:
        key = self._wxpid_cache_key(wxpid)
        cached_entry = self._friend_label_cache.get(key)
        if cached_entry is not None and monotonic() - cached_entry[0] < FRIEND_LABEL_CACHE_TTL_SECONDS:
            return cached_entry[1]

        lock = self._get_friend_label_lock(wxpid)
        async with lock:
            cached_entry = self._friend_label_cache.get(key)
            if cached_entry is not None and monotonic() - cached_entry[0] < FRIEND_LABEL_CACHE_TTL_SECONDS:
                return cached_entry[1]

            label_payload = await self.context.api_client.get_labels(wxpid=wxpid)
            label_id_to_name: dict[str, str] = {}
            if isinstance(label_payload, dict):
                for label_name, label_id in label_payload.items():
                    normalized_name = str(label_name or "").strip()
                    normalized_id = str(label_id or "").strip()
                    if normalized_name and normalized_id:
                        label_id_to_name[normalized_id] = normalized_name

            user_payload = await self.context.api_client.get_user_list(wxpid=wxpid)
            next_cache: dict[str, set[str]] = {}
            if isinstance(user_payload, list):
                for item in user_payload:
                    wxid = str(item.get("wxid") or "").strip()
                    if not wxid:
                        continue
                    raw_label_ids = item.get("labels") or item.get("label_ids") or item.get("labelIds") or []
                    label_ids = _normalize_scope_values(raw_label_ids)
                    next_cache[wxid] = {
                        label_id_to_name[label_id]
                        for label_id in label_ids
                        if label_id in label_id_to_name
                    }

            self._friend_label_cache[key] = (monotonic(), next_cache)
            return next_cache

    def _needs_friend_label_scope(self) -> bool:
        return any("friend_labels" in (plugin.scope_targets or ()) for plugin in self._plugins)

    async def _matches_plugin_scope(
        self,
        plugin: PythonPlugin,
        event: MessageEvent,
        friend_labels_by_user: dict[str, set[str]] | None = None,
    ) -> bool:
        if not plugin.scope_targets:
            return True

        config = plugin.config if isinstance(plugin.config, dict) else {}

        if event.is_group_message:
            if "rooms" not in plugin.scope_targets:
                return True
            room_mode = _normalize_scope_mode(config.get(PLUGIN_SCOPE_ROOM_MODE), default="all")
            if room_mode == "all":
                return True
            if room_mode == "none":
                return False
            allowed_room_ids = set(_normalize_scope_values(config.get(PLUGIN_SCOPE_ROOM_IDS)))
            return bool(event.conversation_wxid) and event.conversation_wxid in allowed_room_ids

        if _is_biz_conversation_wxid(event.conversation_wxid):
            if "biz" not in plugin.scope_targets:
                return True
            biz_mode = _normalize_scope_mode(config.get(PLUGIN_SCOPE_BIZ_MODE), allow_selected=False, default="all")
            return biz_mode == "all"

        if "friend_labels" not in plugin.scope_targets:
            return True

        friend_mode = _normalize_scope_mode(config.get(PLUGIN_SCOPE_FRIEND_MODE), default="all")
        if friend_mode == "all":
            return True
        if friend_mode == "none":
            return False

        selected_labels = set(_normalize_scope_values(config.get(PLUGIN_SCOPE_FRIEND_LABELS)))
        if not selected_labels:
            return False

        target_wxid = str(event.conversation_wxid or event.sender_wxid or "").strip()
        if not target_wxid:
            return False

        try:
            labels_source = friend_labels_by_user
            if labels_source is None:
                labels_source = await self._get_friend_labels_by_user(event.normalized_wxpid)
            user_labels = labels_source.get(target_wxid, set())
        except Exception:
            logger.exception("读取插件 {} 的好友标签白名单失败", plugin.name)
            return False
        return bool(user_labels & selected_labels)

    async def _resolve_event_self_wxid(self, event: MessageEvent) -> str:
        current_account_wxid = _normalize_text(event.current_account_wxid)
        if current_account_wxid:
            return current_account_wxid

        wxpid = event.normalized_wxpid
        if wxpid is None:
            return ""

        cached_accounts = self.context.get_cached_login_accounts()
        resolved_wxid = _resolve_login_account_wxid(cached_accounts, wxpid)
        if resolved_wxid:
            return resolved_wxid

        refreshed_accounts = await self.context.refresh_cached_login_accounts()
        return _resolve_login_account_wxid(refreshed_accounts, wxpid)

    async def _is_self_sent_message(self, event: MessageEvent) -> bool:
        if event.is_self_message:
            return True

        sender_wxid = _normalize_text(event.sender_wxid)
        if not sender_wxid:
            return False

        self_wxid = await self._resolve_event_self_wxid(event)
        return bool(self_wxid) and sender_wxid == self_wxid

    def _build_blacklist_block_result(self, subject_wxid: str) -> list[dict[str, Any]]:
        blacklist_record = self._blacklist_state.get(subject_wxid, {})
        display_name = _normalize_text(blacklist_record.get("display_name")) if isinstance(blacklist_record, dict) else ""
        resolved_name = display_name or subject_wxid
        return [
            {
                "plugin": BLACKLIST_PLUGIN_NAME,
                "handled": True,
                "stop_processing": True,
                "detail": f"黑名单成员消息已忽略: {resolved_name}",
                "data": {
                    "wxid": subject_wxid,
                    "display_name": resolved_name,
                },
            }
        ]

    async def load_plugins(self) -> None:
        self._plugins.clear()
        for module_name in self.module_names:
            plugin = self._load_plugin(module_name)
            await plugin.startup(self.context)
            self._plugins.append(plugin)
            if plugin.supports_tick and plugin.get_tick_interval_seconds() > 0:
                self._periodic_tasks.append(
                    asyncio.create_task(self._periodic_tick_loop(plugin), name=f"plugin-tick-{plugin.module_name}")
                )
            logger.info("已加载插件: {}", plugin.name)

    async def shutdown(self) -> None:
        for task in self._periodic_tasks:
            task.cancel()
        if self._periodic_tasks:
            await asyncio.gather(*self._periodic_tasks, return_exceptions=True)
        self._periodic_tasks.clear()
        for plugin in reversed(self._plugins):
            try:
                await plugin.shutdown(self.context)
            except Exception:
                logger.exception("关闭插件 {} 失败", plugin.name)
        self._plugins.clear()

    async def _periodic_tick_loop(self, plugin: PythonPlugin) -> None:
        interval_seconds = plugin.get_tick_interval_seconds()
        if interval_seconds <= 0:
            return
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                result = await plugin.tick(self.context)
                if result.handled or result.detail:
                    logger.info("周期插件执行完成: {} | {}", plugin.name, result.detail or "已执行")
                interval_seconds = plugin.get_tick_interval_seconds()
                if interval_seconds <= 0:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("周期插件 {} 执行失败", plugin.name)

    async def dispatch(self, event: MessageEvent) -> list[dict[str, Any]]:
        if await self._is_self_sent_message(event):
            return []

        blacklist_subject_wxid = resolve_blacklist_subject_wxid(event)
        if blacklist_subject_wxid and self._blacklist_state.has(blacklist_subject_wxid):
            return self._build_blacklist_block_result(blacklist_subject_wxid)

        results: list[dict[str, Any]] = []
        friend_labels_by_user: dict[str, set[str]] | None = None
        if not event.is_group_message and self._needs_friend_label_scope():
            try:
                friend_labels_by_user = await self._get_friend_labels_by_user(event.normalized_wxpid)
            except Exception:
                logger.exception("预取好友标签缓存失败")
                friend_labels_by_user = {}

        candidates = [plugin for plugin in self._plugins if plugin.should_handle_message(event)]
        scope_matches = await asyncio.gather(
            *[self._matches_plugin_scope(plugin, event, friend_labels_by_user) for plugin in candidates],
            return_exceptions=True,
        )

        for plugin, scope_match in zip(candidates, scope_matches):
            if isinstance(scope_match, Exception):
                logger.exception("插件 {} 作用域检查失败", plugin.name)
                continue
            if not scope_match:
                plugin.log_scope_skip(event, "scope_mismatch")
                continue
            try:
                result = await plugin.handle_message(event, self.context)
            except Exception as exc:
                logger.exception("插件 {} 处理消息失败", plugin.name)
                result = PluginResult.skipped(str(exc))

            if result.handled or result.stop_processing or result.detail or result.data:
                results.append(
                    {
                        "plugin": plugin.name,
                        "handled": result.handled,
                        "stop_processing": result.stop_processing,
                        "detail": result.detail,
                        "data": result.data,
                    }
                )
            if result.stop_processing:
                break
        return results

    async def execute_plugin(self, module_name: str, config_override: dict[str, Any] | None = None) -> dict[str, Any]:
        plugin = self._load_plugin(module_name, config_override)
        if plugin.message_dependent:
            raise ValueError("消息插件不支持手动执行")

        try:
            result = await plugin.execute(self.context)
        finally:
            try:
                await plugin.shutdown(self.context)
            except Exception:
                logger.exception("手动执行插件 {} 后清理资源失败", plugin.name)

        return {
            "module": plugin.module_name,
            "plugin": plugin.name,
            "handled": result.handled,
            "stop_processing": result.stop_processing,
            "detail": result.detail,
            "data": result.data,
        }

    def _load_plugin(self, module_name: str, config_override: dict[str, Any] | None = None) -> PythonPlugin:
        spec = self._resolve_plugin_spec(module_name)
        module = self._load_python_module(spec, force_reload=True)
        metadata = _describe_python_module(module, spec)
        resolved_config = self._resolve_plugin_config(module_name, str(metadata.get("name") or spec.stem))
        if config_override:
            resolved_config = {
                **resolved_config,
                **dict(config_override),
            }
        return PythonPlugin(
            spec,
            resolved_config,
            module,
            metadata,
            self.plugin_log_sink,
        )